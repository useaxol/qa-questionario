"""Persistência em SQLite: schema, migrações simples e consultas."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

from .models import Alert, Observation, Watch, iso

SCHEMA_VERSION = 1

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

CREATE TABLE IF NOT EXISTS observations (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    watch_id         INTEGER REFERENCES watches(id) ON DELETE SET NULL,
    origin           TEXT NOT NULL,
    destination      TEXT NOT NULL,
    departure_date   TEXT NOT NULL,
    return_date      TEXT,
    trip_type        TEXT NOT NULL,
    cabin            TEXT NOT NULL,
    passengers       INTEGER NOT NULL DEFAULT 1,
    currency         TEXT NOT NULL,
    price            REAL NOT NULL,
    price_per_pax    REAL NOT NULL,
    airline          TEXT,
    stops            INTEGER,
    duration_minutes INTEGER,
    provider         TEXT NOT NULL,
    source           TEXT NOT NULL DEFAULT 'quote',
    weight           REAL NOT NULL DEFAULT 1.0,
    observed_at      TEXT NOT NULL,
    days_to_departure INTEGER
);

CREATE INDEX IF NOT EXISTS idx_obs_route
    ON observations (origin, destination, trip_type, cabin, currency, departure_date);
CREATE INDEX IF NOT EXISTS idx_obs_watch
    ON observations (watch_id, observed_at);
CREATE INDEX IF NOT EXISTS idx_obs_observed
    ON observations (observed_at);

CREATE TABLE IF NOT EXISTS alerts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    watch_id       INTEGER REFERENCES watches(id) ON DELETE CASCADE,
    observation_id INTEGER REFERENCES observations(id) ON DELETE SET NULL,
    created_at     TEXT NOT NULL,
    verdict        TEXT NOT NULL,
    severity       INTEGER NOT NULL DEFAULT 0,
    price          REAL NOT NULL,
    expected_price REAL NOT NULL,
    discount_pct   REAL NOT NULL,
    z_score        REAL NOT NULL,
    percentile     REAL NOT NULL,
    confidence     TEXT NOT NULL,
    deal_score     REAL NOT NULL DEFAULT 0,
    message        TEXT NOT NULL DEFAULT '',
    payload        TEXT,
    notified       INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_alerts_watch ON alerts (watch_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_created ON alerts (created_at DESC);
"""


def connect(db_path: str) -> sqlite3.Connection:
    directory = os.path.dirname(os.path.abspath(db_path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(db_path, detect_types=0, timeout=30)
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
            watch.label,
            watch.origin.upper(),
            watch.destination.upper(),
            iso(watch.departure_date),
            iso(watch.return_date),
            watch.flex_days,
            watch.trip_type,
            watch.cabin,
            watch.passengers,
            watch.currency.upper(),
            watch.max_stops,
            watch.target_price,
            1 if watch.active else 0,
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


# ----------------------------------------------------------- observations


def insert_observation(conn: sqlite3.Connection, obs: Observation, commit: bool = True) -> int:
    cur = conn.execute(
        """
        INSERT INTO observations (watch_id, origin, destination, departure_date, return_date,
                                  trip_type, cabin, passengers, currency, price, price_per_pax,
                                  airline, stops, duration_minutes, provider, source, weight,
                                  observed_at, days_to_departure)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            obs.watch_id,
            obs.origin.upper(),
            obs.destination.upper(),
            iso(obs.departure_date),
            iso(obs.return_date),
            obs.trip_type,
            obs.cabin,
            obs.passengers,
            obs.currency.upper(),
            obs.price,
            obs.price_per_pax,
            obs.airline,
            obs.stops,
            obs.duration_minutes,
            obs.provider,
            obs.source,
            obs.weight,
            iso(obs.observed_at or datetime.now()),
            obs.days_to_departure,
        ),
    )
    if commit:
        conn.commit()
    return int(cur.lastrowid)


def insert_observations(conn: sqlite3.Connection, rows: Iterable[Observation]) -> int:
    count = 0
    for obs in rows:
        insert_observation(conn, obs, commit=False)
        count += 1
    conn.commit()
    return count


def route_history(
    conn: sqlite3.Connection,
    origin: str,
    destination: str,
    trip_type: str,
    cabin: str,
    currency: str,
    before: Optional[datetime] = None,
    exclude_id: Optional[int] = None,
    limit: int = 20000,
) -> List[Observation]:
    """Histórico comparável de uma rota (mesmo tipo de viagem, cabine e moeda)."""
    sql = [
        "SELECT * FROM observations",
        "WHERE origin = ? AND destination = ? AND trip_type = ? AND cabin = ? AND currency = ?",
    ]
    params: List[Any] = [
        origin.upper(),
        destination.upper(),
        trip_type,
        cabin,
        currency.upper(),
    ]
    if before is not None:
        sql.append("AND observed_at < ?")
        params.append(iso(before))
    if exclude_id is not None:
        sql.append("AND id <> ?")
        params.append(exclude_id)
    sql.append("ORDER BY observed_at DESC LIMIT ?")
    params.append(limit)
    return [Observation.from_row(r) for r in conn.execute(" ".join(sql), params)]


def watch_history(
    conn: sqlite3.Connection, watch_id: int, limit: int = 2000
) -> List[Observation]:
    rows = conn.execute(
        "SELECT * FROM observations WHERE watch_id = ? ORDER BY observed_at ASC LIMIT ?",
        (watch_id, limit),
    )
    return [Observation.from_row(r) for r in rows]


def latest_observation(conn: sqlite3.Connection, watch_id: int) -> Optional[Observation]:
    row = conn.execute(
        "SELECT * FROM observations WHERE watch_id = ? ORDER BY observed_at DESC LIMIT 1",
        (watch_id,),
    ).fetchone()
    return Observation.from_row(row) if row else None


def observation_stats(conn: sqlite3.Connection) -> Dict[str, Any]:
    row = conn.execute(
        "SELECT COUNT(*) AS n, MIN(observed_at) AS first, MAX(observed_at) AS last "
        "FROM observations"
    ).fetchone()
    routes = conn.execute(
        "SELECT COUNT(DISTINCT origin || destination) AS n FROM observations"
    ).fetchone()
    return {
        "observations": row["n"] or 0,
        "first_observed_at": row["first"],
        "last_observed_at": row["last"],
        "routes": routes["n"] or 0,
    }


# ---------------------------------------------------------------- alerts


def insert_alert(conn: sqlite3.Connection, alert: Alert) -> int:
    cur = conn.execute(
        """
        INSERT INTO alerts (watch_id, observation_id, created_at, verdict, severity, price,
                            expected_price, discount_pct, z_score, percentile, confidence,
                            deal_score, message, payload, notified)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            alert.watch_id,
            alert.observation_id,
            iso(alert.created_at or datetime.now()),
            alert.verdict,
            alert.severity,
            alert.price,
            alert.expected_price,
            alert.discount_pct,
            alert.z_score,
            alert.percentile,
            alert.confidence,
            alert.deal_score,
            alert.message,
            json.dumps(alert.payload, ensure_ascii=False, default=str),
            1 if alert.notified else 0,
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def mark_alert_notified(conn: sqlite3.Connection, alert_id: int) -> None:
    conn.execute("UPDATE alerts SET notified = 1 WHERE id = ?", (alert_id,))
    conn.commit()


def last_alert_for_watch(conn: sqlite3.Connection, watch_id: int) -> Optional[Alert]:
    row = conn.execute(
        "SELECT * FROM alerts WHERE watch_id = ? ORDER BY created_at DESC LIMIT 1",
        (watch_id,),
    ).fetchone()
    return Alert.from_row(row) if row else None


def list_alerts(
    conn: sqlite3.Connection, limit: int = 100, watch_id: Optional[int] = None
) -> List[Alert]:
    if watch_id is None:
        rows = conn.execute(
            "SELECT * FROM alerts ORDER BY created_at DESC LIMIT ?", (limit,)
        )
    else:
        rows = conn.execute(
            "SELECT * FROM alerts WHERE watch_id = ? ORDER BY created_at DESC LIMIT ?",
            (watch_id, limit),
        )
    return [Alert.from_row(r) for r in rows]


def count_alerts_since(conn: sqlite3.Connection, since: datetime) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM alerts WHERE created_at >= ?", (iso(since),)
    ).fetchone()
    return int(row["n"] or 0)


def purge_old_observations(conn: sqlite3.Connection, keep_days: int) -> int:
    cutoff = datetime.now() - timedelta(days=keep_days)
    cur = conn.execute("DELETE FROM observations WHERE observed_at < ?", (iso(cutoff),))
    conn.commit()
    return cur.rowcount
