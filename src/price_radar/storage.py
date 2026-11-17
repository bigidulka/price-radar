"""SQLite storage: products, tracked competitor links and price history."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Iterator

from .models import Offer, Product, Watch

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    sku TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    brand TEXT NOT NULL DEFAULT '',
    oem TEXT NOT NULL DEFAULT '',
    cost REAL NOT NULL DEFAULT 0,
    price REAL NOT NULL DEFAULT 0,
    min_margin_pct REAL NOT NULL DEFAULT 15,
    max_price REAL,
    channel TEXT NOT NULL DEFAULT 'ozon',
    commission_pct REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS watches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT NOT NULL REFERENCES products(sku) ON DELETE CASCADE,
    source TEXT NOT NULL,
    url TEXT NOT NULL,
    UNIQUE (sku, url)
);
CREATE TABLE IF NOT EXISTS offers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    watch_id INTEGER NOT NULL REFERENCES watches(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    seller TEXT NOT NULL,
    price REAL NOT NULL,
    in_stock INTEGER NOT NULL,
    seen_at TEXT NOT NULL,
    UNIQUE (watch_id, seen_at)
);
CREATE INDEX IF NOT EXISTS offers_watch_time ON offers (watch_id, seen_at DESC);
CREATE TABLE IF NOT EXISTS price_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT NOT NULL REFERENCES products(sku) ON DELETE CASCADE,
    old_price REAL NOT NULL,
    new_price REAL NOT NULL,
    reason TEXT NOT NULL,
    changed_at TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._conn:
            yield self._conn

    # products -------------------------------------------------------------
    def upsert_product(self, p: Product) -> None:
        data = asdict(p)
        cols = ", ".join(data)
        marks = ", ".join(f":{k}" for k in data)
        updates = ", ".join(f"{k}=excluded.{k}" for k in data if k != "sku")
        with self.tx() as c:
            c.execute(f"INSERT INTO products ({cols}) VALUES ({marks}) "
                      f"ON CONFLICT(sku) DO UPDATE SET {updates}", data)

    def product(self, sku: str) -> Product | None:
        row = self._conn.execute("SELECT * FROM products WHERE sku = ?", (sku,)).fetchone()
        return Product(**dict(row)) if row else None

    def products(self) -> list[Product]:
        rows = self._conn.execute("SELECT * FROM products ORDER BY sku").fetchall()
        return [Product(**dict(r)) for r in rows]

    def delete_product(self, sku: str) -> bool:
        with self.tx() as c:
            return c.execute("DELETE FROM products WHERE sku = ?", (sku,)).rowcount > 0

    def set_price(self, sku: str, new_price: float, reason: str, at: datetime) -> None:
        with self.tx() as c:
            row = c.execute("SELECT price FROM products WHERE sku = ?", (sku,)).fetchone()
            if row is None:
                raise KeyError(sku)
            c.execute("UPDATE products SET price = ? WHERE sku = ?", (new_price, sku))
            c.execute("INSERT INTO price_changes (sku, old_price, new_price, reason, changed_at) "
                      "VALUES (?, ?, ?, ?, ?)", (sku, row["price"], new_price, reason, at.isoformat()))

    def price_changes(self, sku: str | None = None, limit: int = 50) -> list[dict]:
        q = "SELECT * FROM price_changes"
        args: tuple = ()
        if sku:
            q += " WHERE sku = ?"
            args = (sku,)
        q += " ORDER BY changed_at DESC, id DESC LIMIT ?"
        return [dict(r) for r in self._conn.execute(q, (*args, limit)).fetchall()]

    # watches --------------------------------------------------------------
    def add_watch(self, sku: str, source: str, url: str) -> Watch:
        if self.product(sku) is None:
            raise KeyError(f"unknown sku {sku}")
        with self.tx() as c:
            c.execute("INSERT OR IGNORE INTO watches (sku, source, url) VALUES (?, ?, ?)", (sku, source, url))
            row = c.execute("SELECT * FROM watches WHERE sku = ? AND url = ?", (sku, url)).fetchone()
        return Watch(**dict(row))

    def watches(self, sku: str | None = None) -> list[Watch]:
        if sku:
            rows = self._conn.execute("SELECT * FROM watches WHERE sku = ? ORDER BY id", (sku,)).fetchall()
        else:
            rows = self._conn.execute("SELECT * FROM watches ORDER BY id").fetchall()
        return [Watch(**dict(r)) for r in rows]

    def remove_watch(self, watch_id: int) -> bool:
        with self.tx() as c:
            return c.execute("DELETE FROM watches WHERE id = ?", (watch_id,)).rowcount > 0

    # offers ---------------------------------------------------------------
    def record_offer(self, watch: Watch, offer: Offer) -> bool:
        """Store an observation. Returns False for a duplicate (same watch and timestamp)."""
        with self.tx() as c:
            cur = c.execute(
                "INSERT OR IGNORE INTO offers (watch_id, title, seller, price, in_stock, seen_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (watch.id, offer.title, offer.seller, offer.price, int(offer.in_stock), offer.seen_at.isoformat()),
            )
            return cur.rowcount > 0

    def latest_offers(self, sku: str) -> list[Offer]:
        rows = self._conn.execute(
            """
            SELECT w.source, w.url, o.title, o.seller, o.price, o.in_stock, o.seen_at
            FROM watches w
            JOIN offers o ON o.id = (
                SELECT id FROM offers WHERE watch_id = w.id ORDER BY seen_at DESC, id DESC LIMIT 1
            )
            WHERE w.sku = ?
            ORDER BY o.price
            """,
            (sku,),
        ).fetchall()
        return [self._offer(r) for r in rows]

    def history(self, sku: str, limit: int = 500) -> list[Offer]:
        rows = self._conn.execute(
            """
            SELECT w.source, w.url, o.title, o.seller, o.price, o.in_stock, o.seen_at
            FROM offers o JOIN watches w ON w.id = o.watch_id
            WHERE w.sku = ? ORDER BY o.seen_at, o.id LIMIT ?
            """,
            (sku, limit),
        ).fetchall()
        return [self._offer(r) for r in rows]

    @staticmethod
    def _offer(r: sqlite3.Row) -> Offer:
        return Offer(source=r["source"], url=r["url"], title=r["title"], seller=r["seller"],
                     price=r["price"], in_stock=bool(r["in_stock"]),
                     seen_at=datetime.fromisoformat(r["seen_at"]))
