"""Construção de histórico: backfill, bootstrap por estatísticas e demo.

Sem histórico não existe "preço padrão". Este módulo oferece três caminhos:

* ``backfill_route`` — reconstrói meses de cotações usando um provedor capaz de
  cotar datas passadas (o simulador). É o que torna o app avaliável de imediato.
* ``bootstrap_from_metrics`` — usa quartis históricos publicados pelo provedor
  real (Amadeus) como referência inicial, com peso menor que cotações próprias.
* ``seed_demo`` — monta uma carteira de rotas pelo mundo já com história.
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, time, timedelta
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from . import db
from .config import Config
from .models import Observation, Watch
from .providers import Provider, ProviderError, SearchQuery

#: Antecedências (em dias) cotadas em cada data passada. Cobrir várias
#: antecedências é o que permite separar o efeito "época do ano" do efeito
#: "comprei em cima da hora".
DEFAULT_HORIZONS: Tuple[int, ...] = (10, 24, 45, 75, 115, 165, 240, 320)


def backfill_route(
    conn: sqlite3.Connection,
    provider: Provider,
    origin: str,
    destination: str,
    *,
    trip_type: str = "round",
    cabin: str = "ECONOMY",
    currency: str = "BRL",
    passengers: int = 1,
    nights: int = 10,
    days_back: int = 420,
    step_days: int = 6,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    watch_id: Optional[int] = None,
    until: Optional[date] = None,
    max_offers: int = 8,
) -> int:
    """Reconstrói o histórico de uma rota cotando datas passadas.

    Para cada data de consulta no passado, cota várias datas de ida à frente.
    O resultado cobre o ano inteiro em datas de viagem e toda a curva de
    antecedência — exatamente o que o modelo precisa para separar os efeitos.
    """
    if not provider.supports_backfill:
        raise ProviderError(
            f"O provedor '{provider.name}' não cota datas passadas. "
            "Use o provedor 'synthetic' para backfill ou 'bootstrap' com a Amadeus."
        )

    end = until or date.today()
    start = end - timedelta(days=days_back)
    inserted = 0
    batch: List[Observation] = []

    observed_day = start
    while observed_day <= end:
        for horizon in horizons:
            departure = observed_day + timedelta(days=horizon)
            ret = departure + timedelta(days=nights) if trip_type == "round" else None
            query = SearchQuery(
                origin=origin,
                destination=destination,
                departure_date=departure,
                return_date=ret,
                trip_type=trip_type,
                cabin=cabin,
                passengers=passengers,
                currency=currency,
                max_offers=max_offers,
                as_of=observed_day,
            )
            offer = provider.cheapest(query)
            if offer is None:
                continue
            batch.append(
                Observation(
                    watch_id=watch_id,
                    origin=origin.upper(),
                    destination=destination.upper(),
                    departure_date=departure,
                    return_date=ret,
                    trip_type=trip_type,
                    cabin=cabin,
                    passengers=passengers,
                    currency=currency.upper(),
                    price=offer.price,
                    price_per_pax=offer.price_per_pax(passengers),
                    airline=offer.airline,
                    stops=offer.stops,
                    duration_minutes=offer.duration_minutes,
                    provider=provider.name,
                    source="seed",
                    weight=1.0,
                    observed_at=datetime.combine(observed_day, time(9, 0)),
                    days_to_departure=horizon,
                )
            )
            inserted += 1
        observed_day += timedelta(days=step_days)

    db.insert_observations(conn, batch)
    return inserted


def backfill_series(
    conn: sqlite3.Connection,
    provider: Provider,
    watch: Watch,
    *,
    days_back: int = 240,
    step_days: int = 3,
    until: Optional[date] = None,
    max_offers: int = 8,
) -> int:
    """Reconstrói a série da *viagem exata* monitorada, dia a dia.

    É o que o gráfico da rota mostra: como o preço daquela ida-e-volta
    específica se moveu conforme a data foi se aproximando.
    """
    if not provider.supports_backfill or watch.departure_date is None:
        return 0

    end = until or date.today()
    start = end - timedelta(days=days_back)
    batch: List[Observation] = []

    observed_day = start
    while observed_day <= end:
        days_to_departure = (watch.departure_date - observed_day).days
        if days_to_departure < 0:
            observed_day += timedelta(days=step_days)
            continue
        query = SearchQuery(
            origin=watch.origin,
            destination=watch.destination,
            departure_date=watch.departure_date,
            return_date=watch.return_date,
            trip_type=watch.trip_type,
            cabin=watch.cabin,
            passengers=watch.passengers,
            currency=watch.currency,
            max_stops=watch.max_stops,
            max_offers=max_offers,
            as_of=observed_day,
        )
        offer = provider.cheapest(query)
        if offer is not None:
            batch.append(
                Observation(
                    watch_id=watch.id,
                    origin=watch.origin,
                    destination=watch.destination,
                    departure_date=watch.departure_date,
                    return_date=watch.return_date,
                    trip_type=watch.trip_type,
                    cabin=watch.cabin,
                    passengers=watch.passengers,
                    currency=watch.currency,
                    price=offer.price,
                    price_per_pax=offer.price_per_pax(watch.passengers),
                    airline=offer.airline,
                    stops=offer.stops,
                    duration_minutes=offer.duration_minutes,
                    provider=provider.name,
                    source="seed",
                    weight=1.0,
                    observed_at=datetime.combine(observed_day, time(9, 0)),
                    days_to_departure=days_to_departure,
                )
            )
        observed_day += timedelta(days=step_days)

    db.insert_observations(conn, batch)
    return len(batch)


def backfill_watch(
    conn: sqlite3.Connection,
    provider: Provider,
    watch: Watch,
    *,
    series_days: int = 240,
    series_step: int = 3,
    **kwargs,
) -> int:
    """Histórico completo de uma rota monitorada: a malha da rota + a série da viagem."""
    nights = watch.trip_length_days() or 10
    total = backfill_route(
        conn,
        provider,
        watch.origin,
        watch.destination,
        trip_type=watch.trip_type,
        cabin=watch.cabin,
        currency=watch.currency,
        passengers=1,
        nights=nights,
        **kwargs,
    )
    total += backfill_series(
        conn, provider, watch, days_back=series_days, step_days=series_step
    )
    return total


#: Peso das observações derivadas de estatísticas externas. Vale menos que uma
#: cotação própria: é um resumo de mercado, não um preço observado.
METRIC_WEIGHT = 0.6
METRIC_QUANTILES = ("min", "q1", "median", "q3", "max")


def bootstrap_from_metrics(
    conn: sqlite3.Connection,
    provider: Provider,
    watch: Watch,
    now: Optional[datetime] = None,
) -> int:
    """Semeia o histórico com os quartis históricos publicados pelo provedor."""
    if watch.departure_date is None:
        return 0
    now = now or datetime.now()
    query = SearchQuery(
        origin=watch.origin,
        destination=watch.destination,
        departure_date=watch.departure_date,
        return_date=watch.return_date,
        trip_type=watch.trip_type,
        cabin=watch.cabin,
        passengers=1,
        currency=watch.currency,
        as_of=now.date(),
    )
    metrics = provider.price_metrics(query)
    if not metrics:
        return 0

    rows: List[Observation] = []
    for key in METRIC_QUANTILES:
        value = metrics.get(key)
        if not value or value <= 0:
            continue
        rows.append(
            Observation(
                watch_id=None,
                origin=watch.origin,
                destination=watch.destination,
                departure_date=watch.departure_date,
                return_date=watch.return_date,
                trip_type=watch.trip_type,
                cabin=watch.cabin,
                passengers=1,
                currency=watch.currency,
                price=float(value),
                price_per_pax=float(value),
                provider=f"{provider.name}:metrics",
                source="metric",
                weight=METRIC_WEIGHT,
                observed_at=now,
                days_to_departure=watch.days_to_departure(now.date()),
            )
        )
    return db.insert_observations(conn, rows)


#: Carteira de demonstração: rotas de perfis bem diferentes (longo curso,
#: regional, alta estação europeia, Ásia, doméstico brasileiro).
DEMO_WATCHES: Tuple[Dict[str, object], ...] = (
    {"label": "Férias em Lisboa", "origin": "GRU", "destination": "LIS",
     "nights": 14, "days_ahead": 120, "cabin": "ECONOMY", "target_price": 4200.0},
    {"label": "Tóquio na primavera", "origin": "GRU", "destination": "HND",
     "nights": 12, "days_ahead": 175, "cabin": "ECONOMY"},
    {"label": "Nova York no outono", "origin": "GIG", "destination": "JFK",
     "nights": 8, "days_ahead": 95, "cabin": "ECONOMY"},
    {"label": "Buenos Aires de fim de semana", "origin": "GRU", "destination": "EZE",
     "nights": 4, "days_ahead": 45, "cabin": "ECONOMY"},
    {"label": "Recife com a família", "origin": "CGH", "destination": "REC",
     "nights": 7, "days_ahead": 70, "cabin": "ECONOMY", "flex_days": 2},
    {"label": "Cidade do Cabo", "origin": "GRU", "destination": "CPT",
     "nights": 15, "days_ahead": 210, "cabin": "ECONOMY"},
    {"label": "Paris na executiva", "origin": "GRU", "destination": "CDG",
     "nights": 10, "days_ahead": 150, "cabin": "BUSINESS"},
)


def seed_demo(
    conn: sqlite3.Connection,
    config: Config,
    provider: Provider,
    days_back: int = 420,
    step_days: int = 6,
    verbose: bool = True,
) -> Dict[str, int]:
    """Cria a carteira de demonstração já com histórico reconstruído."""
    today = date.today()
    created = 0
    observations = 0

    for spec in DEMO_WATCHES:
        departure = today + timedelta(days=int(spec["days_ahead"]))
        nights = int(spec["nights"])
        watch = Watch(
            label=str(spec["label"]),
            origin=str(spec["origin"]),
            destination=str(spec["destination"]),
            departure_date=departure,
            return_date=departure + timedelta(days=nights),
            flex_days=int(spec.get("flex_days", 0)),
            trip_type="round",
            cabin=str(spec.get("cabin", "ECONOMY")),
            passengers=int(spec.get("passengers", 1)),
            currency=config.currency,
            max_stops=spec.get("max_stops"),
            target_price=spec.get("target_price"),
            active=True,
            created_at=datetime.now(),
        )
        watch.id = db.insert_watch(conn, watch)
        created += 1
        if verbose:
            print(f"  • {watch.display_name} ({watch.route}) — reconstruindo histórico...")
        observations += backfill_watch(
            conn, provider, watch, days_back=days_back, step_days=step_days
        )

    return {"watches": created, "observations": observations}
