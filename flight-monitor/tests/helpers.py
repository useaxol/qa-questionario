"""Apoio aos testes: banco em memória, config previsível e cesta sintética."""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flightwatch import benchmarks, db, indexing  # noqa: E402
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
        notify_console=False,
        notify_file=None,
        webhook_url=None,
    )
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


def quiet_provider(**overrides) -> SyntheticProvider:
    """Simulador sem ruído, promoção nem deriva: preço = benchmark exato."""
    defaults = dict(
        noise_sigma=0.0, sale_probability=0.0,
        market_amplitude=0.0, destination_amplitude=0.0,
    )
    defaults.update(overrides)
    return SyntheticProvider(**defaults)


def make_watch(destination="LIS", days_ahead=90, nights=10, **overrides) -> Watch:
    departure = date.today() + timedelta(days=days_ahead)
    watch = Watch(
        label=overrides.pop("label", "Teste"),
        origin="GRU",
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


def synthetic_basket(index_by_destination=None, days_ahead=60, default_index=100.0):
    """Monta uma cesta com os índices exatos que o teste pedir."""
    index_by_destination = index_by_destination or {}
    departure = date.today() + timedelta(days=days_ahead)
    readings = []
    for code in benchmarks.BASKET:
        target = index_by_destination.get(code, default_index)
        price = benchmarks.benchmark(code, departure, days_ahead).price * target / 100.0
        readings.append(indexing.build_reading(code, price, departure, days_ahead))
    return indexing.build_basket(readings), readings
