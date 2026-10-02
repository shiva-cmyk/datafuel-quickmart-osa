import sqlite3
from pathlib import Path


DB_PATH = Path("osa.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS stores (
            store_id TEXT PRIMARY KEY,
            city TEXT NOT NULL,
            name TEXT NOT NULL,
            is_active INTEGER NOT NULL,
            is_serviceable INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sweeps (
            as_of TEXT PRIMARY KEY,
            ist_date TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS store_sweeps (
            as_of TEXT NOT NULL,
            store_id TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('complete', 'incomplete')),
            reason TEXT,
            item_count INTEGER NOT NULL DEFAULT 0,
            fetched_at TEXT NOT NULL,
            PRIMARY KEY (as_of, store_id),
            FOREIGN KEY (as_of) REFERENCES sweeps(as_of),
            FOREIGN KEY (store_id) REFERENCES stores(store_id)
        );

        CREATE TABLE IF NOT EXISTS observations (
            as_of TEXT NOT NULL,
            store_id TEXT NOT NULL,
            sku_id TEXT NOT NULL,
            name TEXT NOT NULL,
            in_stock INTEGER NOT NULL,
            qty INTEGER,
            price REAL,
            observed_at TEXT NOT NULL,
            PRIMARY KEY (as_of, store_id, sku_id),
            FOREIGN KEY (as_of) REFERENCES sweeps(as_of),
            FOREIGN KEY (store_id) REFERENCES stores(store_id)
        );

        CREATE INDEX IF NOT EXISTS idx_sweeps_ist_date
            ON sweeps(ist_date);

        CREATE INDEX IF NOT EXISTS idx_observations_lookup
            ON observations(as_of, store_id);

        CREATE INDEX IF NOT EXISTS idx_store_sweeps_lookup
            ON store_sweeps(as_of, store_id);
        """
    )
    conn.commit()