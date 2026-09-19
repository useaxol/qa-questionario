"""Apoio aos testes: banco em memória e histórico sintético."""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flightwatch import db, seed  # noqa: E402
from flightwatch.config import Config  # noqa: E402
from flightwatch.models import Watch  # noqa: E402
from flightwatch.providers.synthetic import SyntheticProvider  # noqa: E402


def memory_db():
    conn = db.connect(":memory:")
    db.init_db(conn)
    return conn


def test_config(**overrides) -> Config:
    config = Config(
        db_path=":memory:",
        provider="synthetic",
        currency="BRL",
        notify_console=False,
        notify_file=None,
        webhook_url=None,
    )
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


def make_watch(
    origin="GRU", destination="LIS", days_ahead=120, nights=14, **overrides
) -> Watch:
    departure = date.today() + timedelta(days=days_ahead)
    watch = Watch(
        label=overrides.pop("label", "Teste"),
        origin=origin,
        destination=destination,
        departure_date=departure,
        return_date=departure + timedelta(days=nights),
        trip_type="round",
        cabin="ECONOMY",
        passengers=1,
        currency="BRL",
        active=True,
        created_at=datetime.now(),
    )
    for key, value in overrides.items():
        setattr(watch, key, value)
    return watch


def seeded_route(conn, origin="GRU", destination="LIS", days_back=420, step_days=6) -> int:
    return seed.backfill_route(
        conn,
        SyntheticProvider(),
        origin,
        destination,
        currency="BRL",
        nights=14,
        days_back=days_back,
        step_days=step_days,
    )
