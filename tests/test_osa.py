import pytest

import app
from db import get_connection, init_db


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"

    monkeypatch.setattr(
        "db.DB_PATH",
        db_path,
    )

    conn = get_connection()
    init_db(conn)

    stores = [
        (
            "MUM-001",
            "Mumbai",
            "QuickMart Mumbai #1",
            1,
            1,
        ),
        (
            "MUM-002",
            "Mumbai",
            "QuickMart Mumbai #2",
            1,
            1,
        ),
    ]

    conn.executemany(
        """
        INSERT INTO stores
        (store_id, city, name, is_active, is_serviceable)
        VALUES (?, ?, ?, ?, ?)
        """,
        stores,
    )

    # 19:00 UTC on Sep 27 = 00:30 IST on Sep 28.
    # Therefore this sweep belongs to the IST date 2026-09-28.
    conn.execute(
        """
        INSERT INTO sweeps
        (as_of, ist_date, started_at, finished_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            "2026-09-27T19:00:00Z",
            "2026-09-28",
            "2026-09-27T19:00:00Z",
            "2026-09-27T19:05:00Z",
        ),
    )

    conn.executemany(
        """
        INSERT INTO store_sweeps
        (as_of, store_id, status, reason, item_count, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "2026-09-27T19:00:00Z",
                "MUM-001",
                "complete",
                None,
                2,
                "2026-09-27T19:05:00Z",
            ),
            (
                "2026-09-27T19:00:00Z",
                "MUM-002",
                "complete",
                None,
                1,
                "2026-09-27T19:05:00Z",
            ),
        ],
    )

    conn.executemany(
        """
        INSERT INTO observations
        (
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
        """,
        [
            (
                "2026-09-27T19:00:00Z",
                "MUM-001",
                "SKU-0001",
                "Milk",
                1,
                0,
                20.0,
                "2026-09-27T19:05:00Z",
            ),
            (
                "2026-09-27T19:00:00Z",
                "MUM-001",
                "SKU-0002",
                "Bread",
                0,
                0,
                30.0,
                "2026-09-27T19:05:00Z",
            ),
            (
                "2026-09-27T19:00:00Z",
                "MUM-002",
                "SKU-0001",
                "Milk",
                1,
                5,
                20.0,
                "2026-09-27T19:05:00Z",
            ),
        ],
    )

    conn.commit()
    conn.close()

    return db_path


def test_osa_uses_in_stock_not_qty(test_db):
    """
    in_stock is the official availability field.

    Here Milk has in_stock=1 but qty=0.
    It must still count as in stock.
    """

    result = app.osa(
        city="Mumbai",
        date="2026-09-28",
    )

    # 2 in-stock observations out of 3.
    assert result["observations"] == 3
    assert result["osa_pct"] == 66.67


def test_osa_is_weighted_across_all_observations(test_db):
    """
    OSA must be:

        total in-stock observations
        ---------------------------- x 100
        total observations

    It must NOT average the percentages of stores.
    """

    conn = get_connection()
    init_db(conn)

    # Add a second sweep for the same IST day.
    conn.execute(
        """
        INSERT INTO sweeps
        (as_of, ist_date, started_at, finished_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            "2026-09-28T04:30:00Z",
            "2026-09-28",
            "2026-09-28T04:30:00Z",
            "2026-09-28T04:35:00Z",
        ),
    )

    conn.executemany(
        """
        INSERT INTO store_sweeps
        (as_of, store_id, status, reason, item_count, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "2026-09-28T04:30:00Z",
                "MUM-001",
                "complete",
                None,
                10,
                "2026-09-28T04:35:00Z",
            ),
            (
                "2026-09-28T04:30:00Z",
                "MUM-002",
                "complete",
                None,
                2,
                "2026-09-28T04:35:00Z",
            ),
        ],
    )

    # Store 1: 9/10 in stock = 90%.
    for i in range(10):
        conn.execute(
            """
            INSERT INTO observations
            (
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
            """,
            (
                "2026-09-28T04:30:00Z",
                "MUM-001",
                f"SKU-A{i}",
                f"Product A{i}",
                1 if i < 9 else 0,
                1 if i < 9 else 0,
                10.0,
                "2026-09-28T04:35:00Z",
            ),
        )

    # Store 2: 1/2 in stock = 50%.
    for i in range(2):
        conn.execute(
            """
            INSERT INTO observations
            (
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
            """,
            (
                "2026-09-28T04:30:00Z",
                "MUM-002",
                f"SKU-B{i}",
                f"Product B{i}",
                1 if i == 0 else 0,
                1 if i == 0 else 0,
                10.0,
                "2026-09-28T04:35:00Z",
            ),
        )

    conn.commit()
    conn.close()

    result = app.osa(
        city="Mumbai",
        date="2026-09-28",
    )

    # Across BOTH sweeps there are:
    # first sweep: 2 in stock / 3 observations
    # second sweep: 10 in stock / 12 observations
    #
    # Total = 12 in stock / 15 observations = 80%.
    assert result["observations"] == 15
    assert result["osa_pct"] == 80.0


def test_incomplete_store_is_excluded_from_osa(test_db):
    """
    An incomplete store-sweep must not contribute observations
    to the OSA calculation.
    """

    conn = get_connection()
    init_db(conn)

    # Mark MUM-002's sweep as incomplete.
    conn.execute(
        """
        UPDATE store_sweeps
        SET status = 'incomplete',
            reason = 'test incomplete store'
        WHERE as_of = ?
          AND store_id = ?
        """,
        (
            "2026-09-27T19:00:00Z",
            "MUM-002",
        ),
    )

    conn.commit()
    conn.close()

    result = app.osa(
        city="Mumbai",
        date="2026-09-28",
    )

    # Only MUM-001 should contribute:
    # 1 in stock / 2 observations = 50%.
    assert result["observations"] == 2
    assert result["osa_pct"] == 50.0

    assert result["status"] == "partial_data"

    assert any(
        item["store_id"] == "MUM-002"
        for item in result["coverage"]["incomplete"]
    )


def test_utc_sweep_is_mapped_to_correct_ist_day(test_db):
    """
    2026-09-27T19:00:00Z is 2026-09-28T00:30:00 IST.

    Therefore the sweep must appear when requesting
    the IST date 2026-09-28.
    """

    result = app.osa(
        city="Mumbai",
        date="2026-09-28",
    )

    assert result["date"] == "2026-09-28"
    assert result["status"] == "ok"
    assert result["observations"] == 3


def test_no_data_does_not_return_zero(test_db):
    """
    No data must be clearly reported as no_data.

    It must NOT be reported as 0% OSA.
    """

    result = app.osa(
        city="Mumbai",
        date="2026-09-26",
    )

    assert result["status"] == "no_data"
    assert result["osa_pct"] is None


def test_invalid_city():
    with pytest.raises(Exception) as exc_info:
        app.osa(
            city="Hyderabad",
            date="2026-09-28",
        )

    assert getattr(
        exc_info.value,
        "status_code",
        None,
    ) == 400


def test_invalid_date(test_db):
    with pytest.raises(Exception) as exc_info:
        app.osa(
            city="Mumbai",
            date="28-09-2026",
        )

    assert getattr(
        exc_info.value,
        "status_code",
        None,
    ) == 400