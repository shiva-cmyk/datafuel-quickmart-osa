
"""
review_me.py: written by an AI coding assistant in one shot and merged without review.

Your job (write it in REVIEW.md):
  1. Find at least 5 real problems, most serious first. For each, say what goes wrong,
     with a concrete example (not just "bad practice").
  2. Fix the 2-3 most serious ones in this file.
Don't rewrite it from scratch. Reviewing is the skill being tested.
"""
import sqlite3
import time
from datetime import date, datetime, timedelta

import requests

PORTAL = "http://127.0.0.1:8765"
HEADERS = {"X-Api-Key": "dfhire-2026"}

MAX_RETRIES = 5
REQUEST_TIMEOUT = 5


# def fetch_inventory(store_id, as_of, cursor="0", results=None):
#     """Fetch every inventory page for a store with bounded retries."""

#     if results is None:
#         results = []

#     for attempt in range(1, MAX_RETRIES + 1):
#         try:
#             r = requests.get(
#                 f"{PORTAL}/v1/stores/{store_id}/inventory",
#                 params={"as_of": as_of, "cursor": cursor},
#                 headers=HEADERS,
#                 timeout=REQUEST_TIMEOUT,
#             )

#             if r.status_code == 429:
#                 retry_after = r.headers.get("Retry-After", "2")

#                 try:
#                     wait_seconds = float(retry_after)
#                 except ValueError:
#                     wait_seconds = 2.0

#                 time.sleep(wait_seconds)
#                 continue

#             if r.status_code in (500, 503):
#                 wait_seconds = min(2 ** (attempt - 1), 8)
#                 time.sleep(wait_seconds)
#                 continue

#             r.raise_for_status()
#             break

#         except requests.Timeout:
#             if attempt == MAX_RETRIES:
#                 raise

#             wait_seconds = min(2 ** (attempt - 1), 8)
#             time.sleep(wait_seconds)

#         except requests.RequestException:
#             if attempt == MAX_RETRIES:
#                 raise

#             wait_seconds = min(2 ** (attempt - 1), 8)
#             time.sleep(wait_seconds)

#     body = r.json()

#     results.extend(body["items"])

#     if body["next_cursor"]:
#         return fetch_inventory(
#             store_id,
#             as_of,
#             body["next_cursor"],
#             results,
#         )

#     return results

def fetch_inventory(store_id, as_of, cursor="0", results=None):
    """Fetch every inventory page for a store with bounded retries."""

    if results is None:
        results = []

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(
                f"{PORTAL}/v1/stores/{store_id}/inventory",
                params={"as_of": as_of, "cursor": cursor},
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT,
            )

        except requests.Timeout:
            if attempt == MAX_RETRIES:
                raise

            wait_seconds = min(2 ** (attempt - 1), 8)
            time.sleep(wait_seconds)
            continue

        except requests.ConnectionError:
            if attempt == MAX_RETRIES:
                raise

            wait_seconds = min(2 ** (attempt - 1), 8)
            time.sleep(wait_seconds)
            continue

        if r.status_code == 429:
            retry_after = r.headers.get("Retry-After", "2")

            try:
                wait_seconds = float(retry_after)
            except ValueError:
                wait_seconds = 2.0

            time.sleep(wait_seconds)
            continue

        if r.status_code in (500, 503):
            if attempt == MAX_RETRIES:
                r.raise_for_status()

            wait_seconds = min(2 ** (attempt - 1), 8)
            time.sleep(wait_seconds)
            continue

        # 200 succeeds.
        # 400/401/404 and other permanent HTTP errors fail immediately.
        r.raise_for_status()
        break

    body = r.json()

    results.extend(body["items"])

    if body["next_cursor"]:
        return fetch_inventory(
            store_id,
            as_of,
            body["next_cursor"],
            results,
        )

    return results
def save(conn, store_id, items):
    for it in items:
        conn.execute(
            """
            INSERT INTO inventory (
                store_id,
                sku_id,
                name,
                in_stock,
                qty,
                observed_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                store_id,
                it["sku_id"],
                it["name"],
                int(it["in_stock"]),
                it["qty"],
                it["observed_at"],
            ),
        )

    conn.commit()


def city_osa(conn, city, day=None):
    """On-shelf availability for a city on a day. Defaults to yesterday."""

    day = day or (
        date.today() - timedelta(days=1)
    ).isoformat()

    stores = [
        r[0]
        for r in conn.execute(
            "SELECT store_id FROM stores WHERE city = ?",
            (city,),
        )
    ]

    per_store = []

    for s in stores:
        rows = conn.execute(
            """
            SELECT qty
            FROM inventory
            WHERE store_id = ?
              AND substr(observed_at, 1, 10) = ?
            """,
            (s, day),
        ).fetchall()

        in_stock = sum(
            1
            for (qty,) in rows
            if qty > 0
        )

        per_store.append(
            in_stock / len(rows)
            if rows
            else 0.0
        )

    return round(
        100 * sum(per_store) / len(per_store),
        2,
    )


if __name__ == "__main__":
    conn = sqlite3.connect("osa.db")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS stores (
            store_id TEXT,
            city TEXT
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS inventory (
            store_id TEXT,
            sku_id TEXT,
            name TEXT,
            in_stock INT,
            qty INT,
            observed_at TEXT
        )
        """
    )

    for sid in ["MUM-001", "MUM-002"]:
        save(
            conn,
            sid,
            fetch_inventory(
                sid,
                datetime.utcnow().isoformat(),
            ),
        )

    print(
        city_osa(
            conn,
            "Mumbai",
        )
    )