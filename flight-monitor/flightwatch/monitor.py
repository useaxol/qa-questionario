"""A rodada de coleta: medir a cesta, calcular o índice e julgar.

Uma rodada faz duas coisas, nesta ordem:

1. **Mede o mercado.** Cota os 10 destinos da cesta com a mesma metodologia —
   mesma origem, mesmas antecedências, mesma cabine — e calcula o índice de
   mercado. Metodologia fixa é o que torna as rodadas comparáveis entre si;
   mudar a régua no meio invalidaria a série.
2. **Julga.** Cada destino da cesta e cada viagem acompanhada pelo usuário é
   avaliado contra seu benchmark e contra a cesta recém-medida.
"""
from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

from . import benchmarks, db, indexing
from .benchmarks import BASE_ORIGIN, BASKET
from .config import Config
from .indexing import Basket, Reading, Verdict
from .models import (
    Alert, BasketSnapshot, KIND_BASKET, KIND_WATCH, Quote, Watch,
)
from .notifier import Notifier, alert_payload, headline
from .providers import Offer, Provider, ProviderError, SearchQuery
from .stats import median


@dataclass
class ProbeSpec:
    """A metodologia fixa da cesta. Mudá-la quebra a comparabilidade da série."""

    origin: str = BASE_ORIGIN
    #: Antecedências sondadas em cada rodada. A contagem é ímpar de propósito:
    #: assim a mediana das sondagens é uma delas, e o índice mostrado no painel
    #: corresponde a uma cotação que existe de verdade.
    horizons: Tuple[int, ...] = (30, 60, 120)
    nights: int = 10
    cabin: str = "ECONOMY"
    passengers: int = 1
    max_stops: Optional[int] = None

    @classmethod
    def from_config(cls, config: Config) -> "ProbeSpec":
        return cls(
            origin=config.basket_origin,
            horizons=tuple(config.probe_horizons),
            nights=config.probe_nights,
        )

    def describe(self) -> str:
        days = " e ".join(str(h) for h in self.horizons)
        return (
            f"{self.origin} → cesta · ida e volta de {self.nights} noites · "
            f"econômica, 1 passageiro · sondagem a {days} dias da partida"
        )


@dataclass
class DestinationProbe:
    """O resultado da sondagem de um destino em uma rodada."""

    destination: str
    readings: List[Reading] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return bool(self.readings)

    @property
    def index(self) -> float:
        return median([r.index for r in self.readings]) if self.readings else 100.0

    @property
    def representative(self) -> Optional[Reading]:
        """A sondagem mediana — com contagem ímpar, preço e índice são os mesmos
        números que o painel, o alerta e a série histórica mostram."""
        if not self.readings:
            return None
        ordered = sorted(self.readings, key=lambda r: r.index)
        return ordered[len(ordered) // 2]


@dataclass
class WatchResult:
    watch: Watch
    quote: Optional[Quote] = None
    reading: Optional[Reading] = None
    verdict: Optional[Verdict] = None
    alert: Optional[Alert] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class RoundResult:
    """Tudo o que uma rodada produziu."""

    round_id: str
    collected_at: datetime
    basket: Basket
    snapshot: Optional[BasketSnapshot] = None
    verdicts: List[Verdict] = field(default_factory=list)
    alerts: List[Alert] = field(default_factory=list)
    probes: List[DestinationProbe] = field(default_factory=list)
    watch_results: List[WatchResult] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def market_index(self) -> float:
        return self.basket.index

    @property
    def alert_count(self) -> int:
        return len(self.alerts) + sum(1 for r in self.watch_results if r.alert)


# --------------------------------------------------------------- sondagem


def probe_destination(
    provider: Provider,
    destination: str,
    spec: ProbeSpec,
    today: date,
    base_overrides: Dict[str, float],
    collected_at: datetime,
    max_offers: int = 12,
) -> DestinationProbe:
    """Cota um destino nas antecedências da metodologia."""
    probe = DestinationProbe(destination=destination.upper())
    errors: List[str] = []

    for horizon in spec.horizons:
        departure = today + timedelta(days=horizon)
        return_date = departure + timedelta(days=spec.nights)
        query = SearchQuery(
            origin=spec.origin,
            destination=destination,
            departure_date=departure,
            return_date=return_date,
            trip_type="round",
            cabin=spec.cabin,
            passengers=spec.passengers,
            currency=benchmarks.BENCHMARK_CURRENCY,
            max_stops=spec.max_stops,
            max_offers=max_offers,
            as_of=today,
        )
        try:
            offer = provider.cheapest(query)
        except ProviderError as exc:
            errors.append(str(exc))
            continue
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            continue
        if offer is None:
            continue

        probe.readings.append(
            indexing.build_reading(
                destination,
                offer.price,
                departure,
                horizon,
                origin=spec.origin,
                cabin=spec.cabin,
                passengers=spec.passengers,
                base_override=base_overrides.get(destination.upper()),
                return_date=return_date,
                currency=offer.currency or benchmarks.BENCHMARK_CURRENCY,
                airline=offer.airline,
                stops=offer.stops,
                collected_at=collected_at,
            )
        )

    if not probe.readings:
        probe.error = errors[0] if errors else "nenhuma oferta retornada"
    return probe


def measure_basket(
    provider: Provider,
    spec: ProbeSpec,
    base_overrides: Dict[str, float],
    now: datetime,
    destinations: Sequence[str] = BASKET,
) -> Tuple[Basket, List[DestinationProbe], List[str]]:
    """Mede a cesta inteira em um instante. O índice é a mediana dos destinos."""
    probes, errors = [], []
    for destination in destinations:
        probe = probe_destination(
            provider, destination, spec, now.date(), base_overrides, now
        )
        probes.append(probe)
        if probe.error:
            errors.append(f"{destination}: {probe.error}")

    representatives = [p.representative for p in probes if p.representative is not None]
    basket = indexing.build_basket(representatives, collected_at=now)
    return basket, probes, errors


# ---------------------------------------------------------------- alertas


def _should_alert(
    conn: sqlite3.Connection,
    config: Config,
    verdict: Verdict,
    now: datetime,
    watch_id: Optional[int] = None,
    kind: str = KIND_BASKET,
) -> bool:
    """Evita repetir o mesmo alerta: só repete se piorar o preço ou vencer a carência."""
    if verdict.level < 1:
        return False
    previous = db.last_alert_for(conn, verdict.destination, watch_id=watch_id, kind=kind)
    if previous is None or previous.created_at is None:
        return True
    if now - previous.created_at >= timedelta(hours=config.alert_cooldown_hours):
        return True
    if verdict.level > previous.level:
        return True
    return verdict.price <= previous.price * (1.0 - config.alert_improve_pct / 100.0)


def emit_alert(
    conn: sqlite3.Connection,
    config: Config,
    verdict: Verdict,
    quote: Optional[Quote],
    *,
    watch: Optional[Watch] = None,
    kind: str = KIND_BASKET,
    notifier: Optional[Notifier] = None,
    now: Optional[datetime] = None,
) -> Optional[Alert]:
    now = now or datetime.now()
    watch_id = watch.id if watch else None
    if not _should_alert(conn, config, verdict, now, watch_id=watch_id, kind=kind):
        return None

    alert = Alert(
        watch_id=watch_id,
        quote_id=quote.id if quote else None,
        created_at=now,
        destination=verdict.destination,
        kind=kind,
        level=verdict.level,
        driver=verdict.driver,
        price=verdict.price,
        benchmark=verdict.benchmark,
        index_value=verdict.index,
        basket_index=verdict.basket_index,
        distortion=verdict.distortion,
        signal=verdict.signal,
        score=verdict.score,
        currency=verdict.currency,
        message=headline(verdict, watch),
        payload=alert_payload(verdict, quote, watch),
    )
    alert.id = db.insert_alert(conn, alert)

    if notifier is not None:
        notifier.send(verdict, quote, watch, alert)
        db.mark_alert_notified(conn, alert.id)
        alert.notified = True
    return alert


# ------------------------------------------------------- viagens do usuário


def _return_for(watch: Watch, departure: date) -> Optional[date]:
    if watch.trip_type != "round" or watch.return_date is None or watch.departure_date is None:
        return watch.return_date
    return departure + timedelta(days=(watch.return_date - watch.departure_date).days)


def candidate_dates(watch: Watch, today: date) -> List[date]:
    if watch.departure_date is None:
        return []
    flex = max(0, min(7, watch.flex_days or 0))
    days = {watch.departure_date}
    for delta in range(1, flex + 1):
        days.add(watch.departure_date - timedelta(days=delta))
        days.add(watch.departure_date + timedelta(days=delta))
    return sorted(d for d in days if d >= today)


def collect_watch(
    conn: sqlite3.Connection,
    config: Config,
    provider: Provider,
    watch: Watch,
    basket: Optional[Basket] = None,
    *,
    round_id: str = "",
    notifier: Optional[Notifier] = None,
    now: Optional[datetime] = None,
    base_overrides: Optional[Dict[str, float]] = None,
) -> WatchResult:
    """Cota uma viagem acompanhada e a julga contra benchmark e cesta."""
    now = now or datetime.now()
    result = WatchResult(watch=watch)
    overrides = base_overrides if base_overrides is not None else db.load_base_overrides(conn)

    if not benchmarks.is_covered(watch.destination):
        result.error = (
            f"{watch.destination} não está na cesta — sem benchmark para comparar. "
            f"Destinos cobertos: {', '.join(sorted(BASKET))}."
        )
        return result

    dates = candidate_dates(watch, now.date())
    if not dates:
        result.error = "Sem data de ida futura para cotar."
        return result

    best: Optional[Tuple[Reading, Offer, date]] = None
    errors: List[str] = []
    for departure in dates:
        dtd = (departure - now.date()).days
        query = SearchQuery(
            origin=watch.origin,
            destination=watch.destination,
            departure_date=departure,
            return_date=_return_for(watch, departure),
            trip_type=watch.trip_type,
            cabin=watch.cabin,
            passengers=watch.passengers,
            currency=watch.currency,
            max_stops=watch.max_stops,
            max_offers=config.max_offers,
            as_of=now.date(),
        )
        try:
            offer = provider.cheapest(query)
        except ProviderError as exc:
            errors.append(str(exc))
            continue
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            continue
        if offer is None:
            continue

        reading = indexing.build_reading(
            watch.destination,
            offer.price,
            departure,
            dtd,
            origin=watch.origin,
            cabin=watch.cabin,
            passengers=watch.passengers,
            base_override=overrides.get(watch.destination.upper()),
            return_date=query.return_date,
            currency=offer.currency or watch.currency,
            airline=offer.airline,
            stops=offer.stops,
            collected_at=now,
        )
        # Entre datas flexíveis vence o menor índice, não o menor preço: uma
        # data mais barata só por ser baixa estação não é uma oportunidade.
        if best is None or reading.index < best[0].index:
            best = (reading, offer, departure)

    if best is None:
        result.error = errors[0] if errors else "Nenhuma oferta retornada pelo provedor."
        return result

    reading, offer, departure = best
    quote = Quote(
        watch_id=watch.id,
        kind=KIND_WATCH,
        round_id=round_id,
        origin=watch.origin,
        destination=watch.destination,
        departure_date=departure,
        return_date=reading.return_date,
        days_to_departure=reading.days_to_departure,
        cabin=watch.cabin,
        passengers=watch.passengers,
        currency=reading.currency,
        price=reading.price,
        benchmark=reading.benchmark,
        index_value=reading.index,
        base_used=reading.breakdown.base if reading.breakdown else 0.0,
        airline=offer.airline,
        stops=offer.stops,
        duration_minutes=offer.duration_minutes,
        provider=provider.name,
        collected_at=now,
    )
    quote.id = db.insert_quote(conn, quote)
    if watch.id:
        db.touch_watch(conn, watch.id, now)

    verdict = indexing.evaluate(reading, basket, target_price=watch.target_price)

    result.quote = quote
    result.reading = reading
    result.verdict = verdict
    result.alert = emit_alert(
        conn, config, verdict, quote,
        watch=watch, kind=KIND_WATCH, notifier=notifier, now=now,
    )
    return result


# ------------------------------------------------------------- a rodada


def run_round(
    conn: sqlite3.Connection,
    config: Config,
    provider: Provider,
    *,
    notifier: Optional[Notifier] = None,
    now: Optional[datetime] = None,
    include_watches: bool = True,
    destinations: Sequence[str] = BASKET,
) -> RoundResult:
    """Mede a cesta, grava o índice e julga destinos e viagens acompanhadas."""
    now = now or datetime.now()
    round_id = uuid.uuid4().hex[:12]
    spec = ProbeSpec.from_config(config)
    overrides = db.load_base_overrides(conn)

    basket, probes, errors = measure_basket(provider, spec, overrides, now, destinations)

    result = RoundResult(
        round_id=round_id, collected_at=now, basket=basket, probes=probes, errors=errors
    )

    # Grava cada sondagem: o detalhe alimenta a recalibração depois.
    quotes: List[Quote] = []
    for probe in probes:
        for reading in probe.readings:
            quotes.append(
                Quote(
                    kind=KIND_BASKET,
                    round_id=round_id,
                    origin=spec.origin,
                    destination=reading.destination,
                    departure_date=reading.departure_date,
                    return_date=reading.return_date,
                    days_to_departure=reading.days_to_departure,
                    cabin=spec.cabin,
                    passengers=spec.passengers,
                    currency=reading.currency,
                    price=reading.price,
                    benchmark=reading.benchmark,
                    index_value=reading.index,
                    base_used=reading.breakdown.base if reading.breakdown else 0.0,
                    airline=reading.airline,
                    stops=reading.stops,
                    provider=provider.name,
                    collected_at=now,
                )
            )
    quote_ids = db.insert_quotes(conn, quotes)
    quote_by_destination: Dict[str, Quote] = {}
    for quote, quote_id in zip(quotes, quote_ids):
        quote.id = quote_id
        quote_by_destination.setdefault(quote.destination, quote)

    if basket.readings:
        snapshot = BasketSnapshot(
            round_id=round_id,
            collected_at=now,
            index_value=basket.index,
            dispersion=basket.dispersion,
            size=basket.size,
            currency=benchmarks.BENCHMARK_CURRENCY,
        )
        snapshot.id = db.insert_snapshot(conn, snapshot)
        result.snapshot = snapshot

    result.verdicts = indexing.evaluate_basket(basket)
    for verdict in result.verdicts:
        alert = emit_alert(
            conn, config, verdict,
            quote_by_destination.get(verdict.destination),
            kind=KIND_BASKET, notifier=notifier, now=now,
        )
        if alert:
            result.alerts.append(alert)

    if include_watches:
        for watch in db.list_watches(conn, only_active=True):
            result.watch_results.append(
                collect_watch(
                    conn, config, provider, watch, basket,
                    round_id=round_id, notifier=notifier, now=now,
                    base_overrides=overrides,
                )
            )

    return result


def current_basket(conn: sqlite3.Connection) -> Optional[Basket]:
    """Reconstrói a cesta da última rodada a partir do banco."""
    snapshot = db.latest_snapshot(conn)
    if snapshot is None:
        return None
    quotes = [q for q in db.quotes_for_round(conn, snapshot.round_id) if q.kind == KIND_BASKET]
    by_destination: Dict[str, List[Quote]] = {}
    for quote in quotes:
        by_destination.setdefault(quote.destination, []).append(quote)

    readings: List[Reading] = []
    for destination, group in by_destination.items():
        target = median([q.index_value for q in group])
        quote = min(group, key=lambda q: abs(q.index_value - target))
        readings.append(
            Reading(
                destination=destination,
                price=quote.price,
                benchmark=quote.benchmark,
                index=quote.index_value,
                departure_date=quote.departure_date,
                return_date=quote.return_date,
                days_to_departure=quote.days_to_departure,
                currency=quote.currency,
                airline=quote.airline,
                stops=quote.stops,
                collected_at=quote.collected_at,
            )
        )

    basket = indexing.build_basket(readings, collected_at=snapshot.collected_at)
    # O índice gravado é a verdade da rodada, mesmo que a reconstrução difira.
    basket.index = snapshot.index_value
    basket.dispersion = snapshot.dispersion
    return basket
