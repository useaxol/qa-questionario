"""Persistência em SQLite: cotações, índice de mercado, alertas e calibração."""
from __future__ import annotations

import json
import os
import sqlite3
from collections import OrderedDict
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .models import (
    Alert, BaseOverride, BasketSnapshot, KIND_BASKET, KIND_WATCH, Quote, Watch, iso,
)

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS watches (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    label           TEXT    DEFAULT '',
    origin          TEXT    NOT NULL,
    destination     TEXT    NOT NULL,
    departure_date  TEXT,
    return_date     TEXT,
    flex_days       INTEGER DEFAULT 0,
    trip_type       TEXT    NOT NULL DEFAULT 'round',
    cabin           TEXT    NOT NULL DEFAULT 'ECONOMY',
    passengers      INTEGER NOT NULL DEFAULT 1,
    currency        TEXT    NOT NULL DEFAULT 'BRL',
    max_stops       INTEGER,
    target_price    REAL,
    active          INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT    NOT NULL,
    last_checked_at TEXT
);

CREATE TABLE IF NOT EXISTS quotes (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    watch_id          INTEGER REFERENCES watches(id) ON DELETE SET NULL,
    kind              TEXT NOT NULL DEFAULT 'basket',
    round_id          TEXT NOT NULL DEFAULT '',
    origin            TEXT NOT NULL,
    destination       TEXT NOT NULL,
    departure_date    TEXT NOT NULL,
    return_date       TEXT,
    days_to_departure INTEGER NOT NULL DEFAULT 0,
    cabin             TEXT NOT NULL DEFAULT 'ECONOMY',
    passengers        INTEGER NOT NULL DEFAULT 1,
    currency          TEXT NOT NULL,
    price             REAL NOT NULL,
    benchmark         REAL NOT NULL,
    index_value       REAL NOT NULL,
    base_used         REAL,
    airline           TEXT,
    stops             INTEGER,
    duration_minutes  INTEGER,
    provider          TEXT NOT NULL,
    collected_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_quotes_dest ON quotes (destination, collected_at DESC);
CREATE INDEX IF NOT EXISTS idx_quotes_watch ON quotes (watch_id, collected_at);
CREATE INDEX IF NOT EXISTS idx_quotes_round ON quotes (round_id);
CREATE INDEX IF NOT EXISTS idx_quotes_kind ON quotes (kind, collected_at DESC);

CREATE TABLE IF NOT EXISTS basket_snapshots (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    round_id     TEXT NOT NULL UNIQUE,
    collected_at TEXT NOT NULL,
    index_value  REAL NOT NULL,
    dispersion   REAL NOT NULL DEFAULT 0,
    size         INTEGER NOT NULL DEFAULT 0,
    currency     TEXT NOT NULL DEFAULT 'BRL'
);

CREATE INDEX IF NOT EXISTS idx_snapshots_time ON basket_snapshots (collected_at DESC);

CREATE TABLE IF NOT EXISTS alerts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    watch_id     INTEGER REFERENCES watches(id) ON DELETE CASCADE,
    quote_id     INTEGER REFERENCES quotes(id) ON DELETE SET NULL,
    created_at   TEXT NOT NULL,
    destination  TEXT NOT NULL,
    kind         TEXT NOT NULL DEFAULT 'basket',
    level        INTEGER NOT NULL DEFAULT 0,
    driver       TEXT NOT NULL DEFAULT 'none',
    price        REAL NOT NULL,
    benchmark    REAL NOT NULL,
    index_value  REAL NOT NULL,
    basket_index REAL,
    distortion   REAL,
    signal       REAL NOT NULL DEFAULT 0,
    score        REAL NOT NULL DEFAULT 0,
    currency     TEXT NOT NULL DEFAULT 'BRL',
    message      TEXT NOT NULL DEFAULT '',
    payload      TEXT,
    notified     INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_alerts_time ON alerts (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_dest ON alerts (destination, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_watch ON alerts (watch_id, created_at DESC);

CREATE TABLE IF NOT EXISTS base_overrides (
    destination TEXT PRIMARY KEY,
    base_price  REAL NOT NULL,
    updated_at  TEXT NOT NULL,
    n_quotes    INTEGER NOT NULL DEFAULT 0,
    change_pct  REAL NOT NULL DEFAULT 0,
    note        TEXT DEFAULT ''
);
"""


def connect(db_path: str) -> sqlite3.Connection:
    directory = os.path.dirname(os.path.abspath(db_path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT INTO meta (key, value) VALUES ('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()


@contextmanager
def session(db_path: str):
    conn = connect(db_path)
    try:
        init_db(conn)
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------- watches


def insert_watch(conn: sqlite3.Connection, watch: Watch) -> int:
    cur = conn.execute(
        """
        INSERT INTO watches (label, origin, destination, departure_date, return_date,
                             flex_days, trip_type, cabin, passengers, currency,
                             max_stops, target_price, active, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            watch.label, watch.origin.upper(), watch.destination.upper(),
            iso(watch.departure_date), iso(watch.return_date), watch.flex_days,
            watch.trip_type, watch.cabin, watch.passengers, watch.currency.upper(),
            watch.max_stops, watch.target_price, 1 if watch.active else 0,
            iso(watch.created_at or datetime.now()),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def get_watch(conn: sqlite3.Connection, watch_id: int) -> Optional[Watch]:
    row = conn.execute("SELECT * FROM watches WHERE id = ?", (watch_id,)).fetchone()
    return Watch.from_row(row) if row else None


def list_watches(conn: sqlite3.Connection, only_active: bool = False) -> List[Watch]:
    sql = "SELECT * FROM watches"
    if only_active:
        sql += " WHERE active = 1"
    sql += " ORDER BY departure_date IS NULL, departure_date, id"
    return [Watch.from_row(row) for row in conn.execute(sql)]


def set_watch_active(conn: sqlite3.Connection, watch_id: int, active: bool) -> None:
    conn.execute("UPDATE watches SET active = ? WHERE id = ?", (1 if active else 0, watch_id))
    conn.commit()


def delete_watch(conn: sqlite3.Connection, watch_id: int) -> None:
    conn.execute("DELETE FROM watches WHERE id = ?", (watch_id,))
    conn.commit()


def touch_watch(conn: sqlite3.Connection, watch_id: int, when: datetime) -> None:
    conn.execute("UPDATE watches SET last_checked_at = ? WHERE id = ?", (iso(when), watch_id))
    conn.commit()


# ----------------------------------------------------------------- quotes


def insert_quote(conn: sqlite3.Connection, quote: Quote, commit: bool = True) -> int:
    cur = conn.execute(
        """
        INSERT INTO quotes (watch_id, kind, round_id, origin, destination, departure_date,
                            return_date, days_to_departure, cabin, passengers, currency,
                            price, benchmark, index_value, base_used, airline, stops,
                            duration_minutes, provider, collected_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            quote.watch_id, quote.kind, quote.round_id, quote.origin.upper(),
            quote.destination.upper(), iso(quote.departure_date), iso(quote.return_date),
            quote.days_to_departure, quote.cabin, quote.passengers, quote.currency.upper(),
            quote.price, quote.benchmark, quote.index_value, quote.base_used,
            quote.airline, quote.stops, quote.duration_minutes, quote.provider,
            iso(quote.collected_at or datetime.now()),
        ),
    )
    if commit:
        conn.commit()
    return int(cur.lastrowid)


def insert_quotes(conn: sqlite3.Connection, quotes: Iterable[Quote]) -> List[int]:
    ids = [insert_quote(conn, quote, commit=False) for quote in quotes]
    conn.commit()
    return ids


def quotes_for_round(conn: sqlite3.Connection, round_id: str) -> List[Quote]:
    rows = conn.execute(
        "SELECT * FROM quotes WHERE round_id = ? ORDER BY destination", (round_id,)
    )
    return [Quote.from_row(r) for r in rows]


def watch_history(conn: sqlite3.Connection, watch_id: int, limit: int = 2000) -> List[Quote]:
    rows = conn.execute(
        "SELECT * FROM quotes WHERE watch_id = ? ORDER BY collected_at ASC LIMIT ?",
        (watch_id, limit),
    )
    return [Quote.from_row(r) for r in rows]


def latest_quote(conn: sqlite3.Connection, watch_id: int) -> Optional[Quote]:
    row = conn.execute(
        "SELECT * FROM quotes WHERE watch_id = ? ORDER BY collected_at DESC LIMIT 1",
        (watch_id,),
    ).fetchone()
    return Quote.from_row(row) if row else None


def destination_history(
    conn: sqlite3.Connection,
    destination: str,
    kind: Optional[str] = KIND_BASKET,
    limit: int = 400,
) -> List[Quote]:
    sql = "SELECT * FROM quotes WHERE destination = ?"
    params: List[Any] = [destination.upper()]
    if kind:
        sql += " AND kind = ?"
        params.append(kind)
    sql += " ORDER BY collected_at ASC LIMIT ?"
    params.append(limit)
    return [Quote.from_row(r) for r in conn.execute(sql, params)]


def all_quotes_for_calibration(
    conn: sqlite3.Connection, destination: str, since_days: int = 180
) -> List[Quote]:
    """Cotações recentes de um destino, de qualquer origem da coleta."""
    cutoff = datetime.now() - timedelta(days=since_days)
    rows = conn.execute(
        "SELECT * FROM quotes WHERE destination = ? AND collected_at >= ? "
        "ORDER BY collected_at DESC",
        (destination.upper(), iso(cutoff)),
    )
    return [Quote.from_row(r) for r in rows]


def quote_stats(conn: sqlite3.Connection) -> Dict[str, Any]:
    row = conn.execute(
        "SELECT COUNT(*) AS n, MIN(collected_at) AS first, MAX(collected_at) AS last FROM quotes"
    ).fetchone()
    rounds = conn.execute("SELECT COUNT(*) AS n FROM basket_snapshots").fetchone()
    return {
        "quotes": row["n"] or 0,
        "first_collected_at": row["first"],
        "last_collected_at": row["last"],
        "rounds": rounds["n"] or 0,
    }


# ------------------------------------------------------- basket snapshots


def insert_snapshot(conn: sqlite3.Connection, snapshot: BasketSnapshot) -> int:
    cur = conn.execute(
        """
        INSERT INTO basket_snapshots (round_id, collected_at, index_value, dispersion, size, currency)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(round_id) DO UPDATE SET
            index_value = excluded.index_value,
            dispersion  = excluded.dispersion,
            size        = excluded.size
        """,
        (
            snapshot.round_id, iso(snapshot.collected_at or datetime.now()),
            snapshot.index_value, snapshot.dispersion, snapshot.size, snapshot.currency,
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def latest_snapshot(conn: sqlite3.Connection) -> Optional[BasketSnapshot]:
    row = conn.execute(
        "SELECT * FROM basket_snapshots ORDER BY collected_at DESC LIMIT 1"
    ).fetchone()
    return BasketSnapshot.from_row(row) if row else None


def snapshot_history(conn: sqlite3.Connection, limit: int = 180) -> List[BasketSnapshot]:
    rows = conn.execute(
        "SELECT * FROM basket_snapshots ORDER BY collected_at DESC LIMIT ?", (limit,)
    )
    return list(reversed([BasketSnapshot.from_row(r) for r in rows]))


def destination_index_series(
    conn: sqlite3.Connection, destination: str, limit: int = 180
) -> List[Tuple[datetime, float]]:
    """Índice de um destino por rodada — mediana das sondagens daquela rodada."""
    from .models import parse_datetime
    from .stats import median

    rows = conn.execute(
        "SELECT round_id, collected_at, index_value FROM quotes "
        "WHERE destination = ? AND kind = ? ORDER BY collected_at DESC LIMIT ?",
        (destination.upper(), KIND_BASKET, limit * 4),
    ).fetchall()

    grouped: "OrderedDict[str, Tuple[datetime, List[float]]]" = OrderedDict()
    for row in rows:
        key = row["round_id"] or row["collected_at"]
        moment, values = grouped.setdefault(
            key, (parse_datetime(row["collected_at"]), [])
        )
        values.append(row["index_value"])

    series = [(moment, median(values)) for moment, values in grouped.values()]
    series.sort(key=lambda item: item[0])
    return series[-limit:]


# ----------------------------------------------------------------- alerts


def insert_alert(conn: sqlite3.Connection, alert: Alert) -> int:
    cur = conn.execute(
        """
        INSERT INTO alerts (watch_id, quote_id, created_at, destination, kind, level, driver,
                            price, benchmark, index_value, basket_index, distortion, signal,
                            score, currency, message, payload, notified)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            alert.watch_id, alert.quote_id, iso(alert.created_at or datetime.now()),
            alert.destination.upper(), alert.kind, alert.level, alert.driver,
            alert.price, alert.benchmark, alert.index_value, alert.basket_index,
            alert.distortion, alert.signal, alert.score, alert.currency, alert.message,
            json.dumps(alert.payload, ensure_ascii=False, default=str),
            1 if alert.notified else 0,
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def mark_alert_notified(conn: sqlite3.Connection, alert_id: int) -> None:
    conn.execute("UPDATE alerts SET notified = 1 WHERE id = ?", (alert_id,))
    conn.commit()


def last_alert_for(
    conn: sqlite3.Connection,
    destination: str,
    watch_id: Optional[int] = None,
    kind: str = KIND_BASKET,
) -> Optional[Alert]:
    if watch_id is not None:
        row = conn.execute(
            "SELECT * FROM alerts WHERE watch_id = ? ORDER BY created_at DESC LIMIT 1",
            (watch_id,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM alerts WHERE destination = ? AND kind = ? AND watch_id IS NULL "
            "ORDER BY created_at DESC LIMIT 1",
            (destination.upper(), kind),
        ).fetchone()
    return Alert.from_row(row) if row else None


def list_alerts(
    conn: sqlite3.Connection,
    limit: int = 100,
    watch_id: Optional[int] = None,
    destination: Optional[str] = None,
) -> List[Alert]:
    sql = "SELECT * FROM alerts"
    clauses, params = [], []
    if watch_id is not None:
        clauses.append("watch_id = ?")
        params.append(watch_id)
    if destination:
        clauses.append("destination = ?")
        params.append(destination.upper())
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    return [Alert.from_row(r) for r in conn.execute(sql, params)]


def count_alerts_since(conn: sqlite3.Connection, since: datetime) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM alerts WHERE created_at >= ?", (iso(since),)
    ).fetchone()
    return int(row["n"] or 0)


# ------------------------------------------------------------- calibração


def upsert_base_override(conn: sqlite3.Connection, override: BaseOverride) -> None:
    conn.execute(
        """
        INSERT INTO base_overrides (destination, base_price, updated_at, n_quotes, change_pct, note)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(destination) DO UPDATE SET
            base_price = excluded.base_price,
            updated_at = excluded.updated_at,
            n_quotes   = excluded.n_quotes,
            change_pct = excluded.change_pct,
            note       = excluded.note
        """,
        (
            override.destination.upper(), override.base_price,
            iso(override.updated_at or datetime.now()), override.n_quotes,
            override.change_pct, override.note,
        ),
    )
    conn.commit()


def load_base_overrides(conn: sqlite3.Connection) -> Dict[str, float]:
    return {
        row["destination"]: row["base_price"]
        for row in conn.execute("SELECT * FROM base_overrides")
    }


def list_base_overrides(conn: sqlite3.Connection) -> List[BaseOverride]:
    return [
        BaseOverride.from_row(row)
        for row in conn.execute("SELECT * FROM base_overrides ORDER BY destination")
    ]


def clear_base_overrides(conn: sqlite3.Connection) -> int:
    cur = conn.execute("DELETE FROM base_overrides")
    conn.commit()
    return cur.rowcount


def purge_old_quotes(conn: sqlite3.Connection, keep_days: int) -> int:
    cutoff = datetime.now() - timedelta(days=keep_days)
    cur = conn.execute("DELETE FROM quotes WHERE collected_at < ?", (iso(cutoff),))
    conn.execute("DELETE FROM basket_snapshots WHERE collected_at < ?", (iso(cutoff),))
    conn.commit()
    return cur.rowcount
