"""Recalibração: manter a tabela de benchmark honesta com o tempo.

A tabela nasce escrita à mão, e isso é uma escolha — é o que faz o app
funcionar no primeiro minuto. Mas preço de passagem envelhece: câmbio muda,
companhia entra ou sai da rota, capacidade aumenta. Se o benchmark não
acompanhar, todo destino acaba parecendo caro (ou barato) para sempre.

A recalibração inverte a fórmula do benchmark em cada cotação já coletada:

    base_implícita = preço / (sazonalidade × antecedência × cabine × origem × pax)

Tirar esses fatores põe cotações de meses e antecedências diferentes na mesma
régua. A mediana das bases implícitas é o que o mercado diz que a base deveria
ser. A base vigente caminha até lá — nunca mais que 20% de uma vez, para não
perseguir um período atípico.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Dict, List, Optional, Sequence

from . import benchmarks, db
from .benchmarks import BASKET, Calibration
from .models import BaseOverride, Quote


def implied_base_of(quote: Quote) -> Optional[float]:
    """Base implícita de uma cotação já gravada.

    Usa o benchmark e a base que a própria cotação registrou: a razão entre
    eles é exatamente o produto dos fatores aplicados na hora.
    """
    if not quote.price or quote.price <= 0:
        return None
    if quote.base_used and quote.benchmark and quote.benchmark > 0:
        factors = quote.benchmark / quote.base_used
        return quote.price / factors if factors > 0 else None

    # Cotação antiga sem base registrada: recalcula os fatores.
    try:
        breakdown = benchmarks.benchmark(
            quote.destination,
            quote.departure_date,
            quote.days_to_departure,
            origin=quote.origin,
            cabin=quote.cabin,
            passengers=quote.passengers,
        )
    except KeyError:
        return None
    return benchmarks.implied_base(quote.price, breakdown)


def propose_for_destination(
    conn: sqlite3.Connection,
    destination: str,
    since_days: int = 180,
    current_base: Optional[float] = None,
) -> Calibration:
    quotes = db.all_quotes_for_calibration(conn, destination, since_days=since_days)
    bases, months = [], []
    for quote in quotes:
        base = implied_base_of(quote)
        if base and base > 0:
            bases.append(base)
            if quote.departure_date:
                months.append(quote.departure_date.month)
    return benchmarks.propose_calibration(destination, bases, months, current_base)


def propose_all(
    conn: sqlite3.Connection,
    destinations: Sequence[str] = BASKET,
    since_days: int = 180,
) -> List[Calibration]:
    overrides = db.load_base_overrides(conn)
    return [
        propose_for_destination(
            conn, destination, since_days=since_days,
            current_base=overrides.get(destination.upper()),
        )
        for destination in destinations
    ]


def apply(
    conn: sqlite3.Connection,
    calibrations: Sequence[Calibration],
    note: str = "recalibrado a partir das cotações coletadas",
) -> List[Calibration]:
    """Grava as propostas viáveis como override do preço-base."""
    applied: List[Calibration] = []
    for calibration in calibrations:
        if not calibration.is_actionable:
            continue
        db.upsert_base_override(
            conn,
            BaseOverride(
                destination=calibration.destination,
                base_price=calibration.proposed_base,
                updated_at=datetime.now(),
                n_quotes=calibration.n_quotes,
                change_pct=calibration.change_pct,
                note=note,
            ),
        )
        calibration.applied = True
        applied.append(calibration)
    return applied


def effective_bases(conn: sqlite3.Connection) -> Dict[str, dict]:
    """Base em vigor para cada destino: da tabela ou recalibrada."""
    overrides = {o.destination: o for o in db.list_base_overrides(conn)}
    result: Dict[str, dict] = {}
    for iata, dest in benchmarks.DESTINATIONS.items():
        override = overrides.get(iata)
        result[iata] = {
            "destination": iata,
            "table_base": dest.base_price,
            "base": override.base_price if override else dest.base_price,
            "calibrated": override is not None,
            "change_pct": override.change_pct if override else 0.0,
            "n_quotes": override.n_quotes if override else 0,
            "updated_at": override.updated_at if override else None,
        }
    return result
