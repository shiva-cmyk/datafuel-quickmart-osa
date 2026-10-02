from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException, Query

from db import get_connection, init_db


app = FastAPI(title="DataFuel OSA API")


IST = timezone(timedelta(hours=5, minutes=30))

VALID_CITIES = {
    "Mumbai",
    "Delhi",
    "Bengaluru",
}


def utc_to_ist_date(as_of):
    """
    Convert a UTC/ISO timestamp to its IST calendar date.
    """
    dt = datetime.fromisoformat(
        as_of.replace("Z", "+00:00")
    )

    return dt.astimezone(IST).date().isoformat()


def get_requested_date(date_value):
    """
    Validate the requested date.

    If no date is supplied, use yesterday's date in IST.
    """
    if date_value is not None:
        try:
            parsed = datetime.strptime(
                date_value,
                "%Y-%m-%d",
            )
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="date must be YYYY-MM-DD",
            )

        return parsed.date()

    # Default = yesterday in IST.
    now_ist = datetime.now(IST)

    return now_ist.date() - timedelta(days=1)


def get_sweeps_for_date(conn, date_value):
    """
    Return all sweep timestamps belonging to an IST calendar day.
    """
    rows = conn.execute(
        """
        SELECT as_of
        FROM sweeps
        WHERE ist_date = ?
        ORDER BY as_of
        """,
        (date_value,),
    ).fetchall()

    return [row["as_of"] for row in rows]


@app.get("/osa")
def osa(
    city: str = Query(...),
    date: str | None = Query(None),
):
    # Only the three assignment cities are valid.
    if city not in VALID_CITIES:
        raise HTTPException(
            status_code=400,
            detail=(
                "city must be one of "
                "Mumbai, Delhi or Bengaluru"
            ),
        )

    requested_date = get_requested_date(date)
    date_text = requested_date.isoformat()

    conn = get_connection()
    init_db(conn)

    try:
        # Find sweeps that belong to the requested IST calendar day.
        sweep_rows = conn.execute(
            """
            SELECT as_of
            FROM sweeps
            WHERE ist_date = ?
            ORDER BY as_of
            """,
            (date_text,),
        ).fetchall()

        sweep_times = [
            row["as_of"]
            for row in sweep_rows
        ]

        # No sweeps means we have no data.
        # Never turn this into 0% OSA.
        if not sweep_times:
            return {
                "city": city,
                "date": date_text,
                "status": "no_data",
                "osa_pct": None,
                "observations": 0,
                "coverage": {
                    "stores_expected": 0,
                    "stores_complete": 0,
                    "incomplete": [],
                },
                "skus": [],
            }

        # Expected stores are active stores in this city.
        expected_store_rows = conn.execute(
            """
            SELECT store_id
            FROM stores
            WHERE city = ?
              AND is_active = 1
            ORDER BY store_id
            """,
            (city,),
        ).fetchall()

        expected_stores = {
            row["store_id"]
            for row in expected_store_rows
        }

        incomplete = []

        # Store/sweep pairs that are safe to use for OSA.
        complete_store_sweeps = set()

        for as_of in sweep_times:
            rows = conn.execute(
                """
                SELECT
                    ss.store_id,
                    ss.status,
                    ss.reason
                FROM store_sweeps ss
                JOIN stores s
                  ON s.store_id = ss.store_id
                WHERE ss.as_of = ?
                  AND s.city = ?
                  AND s.is_active = 1
                """,
                (as_of, city),
            ).fetchall()

            seen_store_ids = set()

            for row in rows:
                store_id = row["store_id"]

                seen_store_ids.add(store_id)

                if row["status"] == "complete":
                    complete_store_sweeps.add(
                        (as_of, store_id)
                    )

                else:
                    incomplete.append(
                        {
                            "store_id": store_id,
                            "sweep": as_of,
                            "reason": (
                                row["reason"]
                                or "unknown reason"
                            ),
                        }
                    )

            # If an expected store has no result at all,
            # that store/sweep is incomplete.
            missing = expected_stores - seen_store_ids

            for store_id in sorted(missing):
                incomplete.append(
                    {
                        "store_id": store_id,
                        "sweep": as_of,
                        "reason": "no sweep result recorded",
                    }
                )

        # Read observations ONLY from complete store/sweep pairs.
        #
        # as_of is selected here because it is needed to determine
        # the latest name of a SKU.
        observation_rows = []

        for as_of, store_id in complete_store_sweeps:
            rows = conn.execute(
                """
                SELECT
                    as_of,
                    sku_id,
                    name,
                    in_stock
                FROM observations
                WHERE as_of = ?
                  AND store_id = ?
                """,
                (as_of, store_id),
            ).fetchall()

            observation_rows.extend(rows)

        observations_count = len(observation_rows)

        # OSA must use QuickMart's in_stock field.
        #
        # Do NOT use qty because the assignment intentionally
        # contains ghost-stock cases where:
        #
        # in_stock = true
        # qty = 0
        total_in_stock = sum(
            1
            for row in observation_rows
            if row["in_stock"] == 1
        )

        if observations_count == 0:
            # No observations means no reliable OSA number.
            osa_pct = None
            status = "no_data"

        else:
            # Weighted OSA:
            #
            # total in-stock observations
            # -------------------------------- × 100
            # total observations
            #
            # This avoids incorrectly averaging store percentages.
            osa_pct = round(
                total_in_stock
                / observations_count
                * 100,
                2,
            )

            status = (
                "ok"
                if not incomplete
                else "partial_data"
            )

        # ---------------------------------------------------------
        # SKU aggregation
        # ---------------------------------------------------------
        #
        # The mock API intentionally changes the name of SKU-0001
        # after 2026-09-28T00:00:00Z.
        #
        # Therefore we must return the name from the latest
        # observation, rather than whichever row happens to be
        # processed first.
        sku_stats = {}

        for row in observation_rows:
            sku_id = row["sku_id"]

            if sku_id not in sku_stats:
                sku_stats[sku_id] = {
                    "sku_id": sku_id,
                    "name": row["name"],
                    "latest_as_of": row["as_of"],
                    "observations": 0,
                    "in_stock": 0,
                }

            sku_stats[sku_id]["observations"] += 1

            if row["in_stock"] == 1:
                sku_stats[sku_id]["in_stock"] += 1

            # Keep the latest SKU name.
            if row["as_of"] > sku_stats[sku_id]["latest_as_of"]:
                sku_stats[sku_id]["latest_as_of"] = row["as_of"]
                sku_stats[sku_id]["name"] = row["name"]

        skus = []

        for sku_id in sorted(sku_stats):
            item = sku_stats[sku_id]

            item["osa_pct"] = round(
                item["in_stock"]
                / item["observations"]
                * 100,
                2,
            )

            # latest_as_of is only an internal helper.
            # It should not appear in the API response.
            item.pop("latest_as_of", None)

            skus.append(item)

        # A store is considered complete only if it has a
        # complete result for EVERY sweep belonging to this day.
        stores_complete = sum(
            1
            for store_id in expected_stores
            if all(
                (as_of, store_id) in complete_store_sweeps
                for as_of in sweep_times
            )
        )

        return {
            "city": city,
            "date": date_text,
            "status": status,
            "osa_pct": osa_pct,
            "observations": observations_count,
            "coverage": {
                "stores_expected": len(expected_stores),
                "stores_complete": stores_complete,
                "incomplete": incomplete,
            },
            "skus": skus,
        }

    finally:
        conn.close()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
    )