import argparse
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests

from db import get_connection, init_db


PORTAL = "http://127.0.0.1:8765"
API_KEY = "dfhire-2026"

HEADERS = {
    "X-Api-Key": API_KEY
}

IST = ZoneInfo("Asia/Kolkata")

REQUEST_TIMEOUT = 5
REQUEST_DELAY = 0.45

MAX_RETRIES = 6
MAX_SOFT_BAN_RETRIES = 3


def parse_as_of(value):
    """Parse an ISO-8601 timestamp and return UTC datetime."""

    try:
        dt = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise ValueError(
            "as-of must be a valid ISO-8601 timestamp"
        ) from exc

    if dt.tzinfo is None:
        raise ValueError("as-of must include a timezone")

    return dt.astimezone(timezone.utc)


def utc_now():
    return datetime.now(timezone.utc)


def utc_iso(dt):
    return dt.astimezone(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def normalize_observed_at(value):
    """Convert an API observed_at timestamp to UTC."""

    try:
        dt = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise ValueError(
            "observed_at must be a valid ISO-8601 timestamp"
        ) from exc

    if dt.tzinfo is None:
        raise ValueError(
            "observed_at must include a timezone"
        )

    return utc_iso(dt)

def fetch_with_retry(session, url, params):
    """
    Fetch one HTTP page safely.

    Retries only temporary failures:
    - timeout
    - connection errors
    - 429
    - 500
    - 503

    Permanent HTTP errors such as 400, 401 and 404
    are not retried.
    """

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.get(
                url,
                params=params,
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT,
            )

        except requests.Timeout as exc:
            last_error = exc

            wait_seconds = min(
                2 ** (attempt - 1),
                8,
            )

            print(
                f"  timeout; retry {attempt}/{MAX_RETRIES} "
                f"in {wait_seconds}s"
            )

            time.sleep(wait_seconds)
            continue

        except requests.ConnectionError as exc:
            last_error = exc

            wait_seconds = min(
                2 ** (attempt - 1),
                8,
            )

            print(
                f"  connection error; retry {attempt}/{MAX_RETRIES} "
                f"in {wait_seconds}s"
            )

            time.sleep(wait_seconds)
            continue

        # -----------------------------------------------------
        # HTTP response was received successfully.
        #
        # From this point onward, HTTP errors are NOT caught
        # by the network-error retry handlers.
        # -----------------------------------------------------

        if response.status_code == 200:
            return response

        if response.status_code == 429:
            retry_after = response.headers.get(
                "Retry-After",
                "2",
            )

            try:
                wait_seconds = float(retry_after)
            except ValueError:
                wait_seconds = 2.0

            print(
                f"  429 rate limited; waiting "
                f"{wait_seconds:.1f}s"
            )

            time.sleep(wait_seconds)
            continue

        if response.status_code in (500, 503):
            wait_seconds = min(
                2 ** (attempt - 1),
                8,
            )

            print(
                f"  HTTP {response.status_code}; "
                f"retry {attempt}/{MAX_RETRIES} "
                f"in {wait_seconds}s"
            )

            time.sleep(wait_seconds)
            continue

        # 400, 401, 404 and other non-temporary errors.
        # Do NOT retry them.
        response.raise_for_status()

    if last_error:
        raise RuntimeError(
            f"request failed after {MAX_RETRIES} attempts: "
            f"{last_error}"
        )

    raise RuntimeError(
        f"request failed after {MAX_RETRIES} attempts"
    )


def fetch_store_list(session):
    """Fetch the complete QuickMart store roster."""

    stores = []
    page = 1

    while True:
        time.sleep(REQUEST_DELAY)

        response = fetch_with_retry(
            session,
            f"{PORTAL}/v1/stores",
            {"page": page},
        )

        body = response.json()

        stores.extend(
            body.get("stores", [])
        )

        next_page = body.get("next_page")

        if next_page is None:
            break

        page = next_page

    return stores


def save_stores(conn, stores):
    """Store/update the latest QuickMart store roster."""

    for store in stores:
        conn.execute(
            """
            INSERT INTO stores (
                store_id,
                city,
                name,
                is_active,
                is_serviceable
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(store_id) DO UPDATE SET
                city = excluded.city,
                name = excluded.name,
                is_active = excluded.is_active,
                is_serviceable = excluded.is_serviceable
            """,
            (
                store["store_id"],
                store["city"],
                store["name"],
                int(store["is_active"]),
                int(store["is_serviceable"]),
            ),
        )

    conn.commit()


def fetch_inventory_pages(session, store_id, as_of):
    """
    Fetch all inventory pages for one store.

    Returns:
        ("complete", items, None)
        or
        ("incomplete", items, reason)

    Items are deduplicated by sku_id.
    """

    all_items = {}
    cursor = "0"

    soft_ban_attempt = 0

    while True:
        time.sleep(REQUEST_DELAY)

        response = fetch_with_retry(
            session,
            f"{PORTAL}/v1/stores/{store_id}/inventory",
            {
                "as_of": utc_iso(as_of),
                "cursor": cursor,
            },
        )

        body = response.json()

        meta = body.get("meta") or {}

        # The mock server uses meta.source=edge
        # for a soft-banned degraded response.
        if meta.get("source") == "edge":
            soft_ban_attempt += 1

            if soft_ban_attempt > MAX_SOFT_BAN_RETRIES:
                return (
                    "incomplete",
                    list(all_items.values()),
                    "soft ban persisted after retries",
                )

            print(
                f"  {store_id}: soft ban detected; "
                f"pausing before retry"
            )

            # Give the server time to recover before
            # restarting this store from cursor 0.
            time.sleep(25)

            cursor = "0"
            all_items.clear()

            continue

        # A response explicitly marked partial is not
        # a complete inventory snapshot.
        if body.get("partial") is True:
            return (
                "incomplete",
                list(all_items.values()),
                "portal returned partial snapshot",
            )

        for item in body.get("items", []):
            sku_id = item.get("sku_id")

            if not sku_id:
                return (
                    "incomplete",
                    list(all_items.values()),
                    "inventory item missing sku_id",
                )

            # Deduplicate pages using stable sku_id.
            all_items[sku_id] = item

        next_cursor = body.get("next_cursor")

        if next_cursor is None:
            break

        cursor = str(next_cursor)

    return "complete", list(all_items.values()), None


def save_sweep(conn, as_of, started_at, finished_at):
    """Create/update the sweep record."""

    ist_date = as_of.astimezone(
        IST
    ).date().isoformat()

    conn.execute(
        """
        INSERT INTO sweeps (
            as_of,
            ist_date,
            started_at,
            finished_at
        )
        VALUES (?, ?, ?, ?)
        ON CONFLICT(as_of) DO UPDATE SET
            ist_date = excluded.ist_date,
            started_at = excluded.started_at,
            finished_at = excluded.finished_at
        """,
        (
            utc_iso(as_of),
            ist_date,
            utc_iso(started_at),
            utc_iso(finished_at),
        ),
    )

    conn.commit()


def save_store_result(
    conn,
    as_of,
    store_id,
    status,
    reason,
    items,
):
    """
    Save one store's complete/incomplete result.

    Complete results replace previous observations for the
    same sweep/store.

    Incomplete results do not delete previously valid
    observations.
    """

    as_of_text = utc_iso(as_of)
    fetched_at = utc_iso(utc_now())

    # Only replace observations when the snapshot is complete.
    # Incomplete data must never be stored as a valid snapshot.
    if status == "complete":

        conn.execute(
            """
            DELETE FROM observations
            WHERE as_of = ?
              AND store_id = ?
            """,
            (as_of_text, store_id),
        )

        for item in items:
            price = item.get("price")

            if isinstance(price, str):
                price = float(price)

            # QuickMart can return observed_at in UTC or IST.
            # Normalize every timestamp to UTC before storing.
            observed_at = normalize_observed_at(
                item["observed_at"]
            )

            conn.execute(
                """
                INSERT INTO observations (
                    as_of,
                    store_id,
                    sku_id,
                    name,
                    in_stock,
                    qty,
                    price,
                    observed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(as_of, store_id, sku_id)
                DO UPDATE SET
                    name = excluded.name,
                    in_stock = excluded.in_stock,
                    qty = excluded.qty,
                    price = excluded.price,
                    observed_at = excluded.observed_at
                """,
                (
                    as_of_text,
                    store_id,
                    item["sku_id"],
                    item["name"],
                    int(bool(item["in_stock"])),
                    item.get("qty"),
                    price,
                    observed_at,
                ),
            )

    conn.execute(
        """
        INSERT INTO store_sweeps (
            as_of,
            store_id,
            status,
            reason,
            item_count,
            fetched_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(as_of, store_id)
        DO UPDATE SET
            status = excluded.status,
            reason = excluded.reason,
            item_count = excluded.item_count,
            fetched_at = excluded.fetched_at
        """,
        (
            as_of_text,
            store_id,
            status,
            reason,
            len(items),
            fetched_at,
        ),
    )

    conn.commit()


def run_sweep(as_of):
    conn = get_connection()
    init_db(conn)

    started_at = utc_now()

    session = requests.Session()

    print(
        f"Starting sweep: {utc_iso(as_of)}"
    )

    try:
        stores = fetch_store_list(session)

        save_stores(
            conn,
            stores,
        )

        active_stores = [
            store
            for store in stores
            if store["is_active"]
        ]

        print(
            f"Stores: {len(stores)} total, "
            f"{len(active_stores)} active"
        )

        # Create the sweep before store results so
        # foreign keys can reference it.
        save_sweep(
            conn,
            as_of,
            started_at,
            utc_now(),
        )

        complete_count = 0
        incomplete_count = 0

        for index, store in enumerate(
            active_stores,
            start=1,
        ):
            store_id = store["store_id"]

            print(
                f"[{index}/{len(active_stores)}] "
                f"{store_id}..."
            )

            try:
                status, items, reason = (
                    fetch_inventory_pages(
                        session,
                        store_id,
                        as_of,
                    )
                )

                save_store_result(
                    conn,
                    as_of,
                    store_id,
                    status,
                    reason,
                    items,
                )

                if status == "complete":
                    complete_count += 1

                    print(
                        f"  complete: {len(items)} items"
                    )

                else:
                    incomplete_count += 1

                    print(
                        f"  incomplete: {reason}"
                    )

            except Exception as exc:
                incomplete_count += 1

                reason = f"scrape error: {exc}"

                save_store_result(
                    conn,
                    as_of,
                    store_id,
                    "incomplete",
                    reason,
                    [],
                )

                print(
                    f"  incomplete: {reason}"
                )

        finished_at = utc_now()

        save_sweep(
            conn,
            as_of,
            started_at,
            finished_at,
        )

        duration = (
            finished_at - started_at
        ).total_seconds()

        print()

        print(
            f"Sweep complete: "
            f"{len(active_stores)} stores: "
            f"{complete_count} complete, "
            f"{incomplete_count} incomplete "
            f"· {duration:.1f}s"
        )

    finally:
        session.close()
        conn.close()


def main():

    parser = argparse.ArgumentParser(
        description="QuickMart inventory sweep"
    )

    parser.add_argument(
        "--as-of",
        required=True,
        help="UTC/ISO-8601 sweep timestamp",
    )

    args = parser.parse_args()

    try:
        as_of = parse_as_of(
            args.as_of
        )

    except ValueError as exc:
        parser.error(
            str(exc)
        )

    run_sweep(as_of)


if __name__ == "__main__":
    main()