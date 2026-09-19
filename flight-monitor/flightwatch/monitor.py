"""Orquestração da coleta: cotar, gravar, avaliar e alertar."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Iterable, List, Optional, Sequence

from . import analytics, db
from .analytics import Assessment, RouteModel
from .config import Config
from .models import Alert, Observation, Watch
from .notifier import Notifier, alert_payload, headline
from .providers import Offer, Provider, ProviderError, SearchQuery


@dataclass
class WatchResult:
    """Resultado da coleta de uma rota monitorada."""

    watch: Watch
    observations: List[Observation] = field(default_factory=list)
    best: Optional[Observation] = None
    assessment: Optional[Assessment] = None
    alert: Optional[Alert] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None


def candidate_dates(watch: Watch, today: date) -> List[date]:
    """Datas a cotar: a data alvo e, se houver flexibilidade, os dias vizinhos."""
    if watch.departure_date is None:
        return []
    flex = max(0, min(7, watch.flex_days or 0))
    days = [watch.departure_date]
    for delta in range(1, flex + 1):
        days.append(watch.departure_date - timedelta(days=delta))
        days.append(watch.departure_date + timedelta(days=delta))
    return [d for d in sorted(set(days)) if d >= today]


def _return_for(watch: Watch, departure: date) -> Optional[date]:
    """Mantém a duração da viagem ao deslocar a data de ida."""
    if watch.trip_type != "round" or watch.return_date is None or watch.departure_date is None:
        return watch.return_date
    nights = (watch.return_date - watch.departure_date).days
    return departure + timedelta(days=nights)


def build_query(watch: Watch, departure: date, as_of: date, max_offers: int = 20) -> SearchQuery:
    return SearchQuery(
        origin=watch.origin,
        destination=watch.destination,
        departure_date=departure,
        return_date=_return_for(watch, departure),
        trip_type=watch.trip_type,
        cabin=watch.cabin,
        passengers=watch.passengers,
        currency=watch.currency,
        max_stops=watch.max_stops,
        max_offers=max_offers,
        as_of=as_of,
    )


def offer_to_observation(
    watch: Watch, offer: Offer, query: SearchQuery, provider_name: str, observed_at: datetime
) -> Observation:
    return Observation(
        watch_id=watch.id,
        origin=watch.origin,
        destination=watch.destination,
        departure_date=offer.departure_date or query.departure_date,
        return_date=offer.return_date or query.return_date,
        trip_type=watch.trip_type,
        cabin=watch.cabin,
        passengers=watch.passengers,
        currency=offer.currency or watch.currency,
        price=offer.price,
        price_per_pax=offer.price_per_pax(watch.passengers),
        airline=offer.airline,
        stops=offer.stops,
        duration_minutes=offer.duration_minutes,
        provider=provider_name,
        source="quote",
        weight=1.0,
        observed_at=observed_at,
        days_to_departure=(query.departure_date - observed_at.date()).days,
    )


def route_model_for(
    conn: sqlite3.Connection, watch: Watch, before: Optional[datetime] = None
) -> tuple:
    """Modelo da rota e as amostras que o sustentam."""
    history = db.route_history(
        conn,
        origin=watch.origin,
        destination=watch.destination,
        trip_type=watch.trip_type,
        cabin=watch.cabin,
        currency=watch.currency,
        before=before,
    )
    samples = analytics.samples_from_observations(history)
    return analytics.fit_route_model(samples), samples


def assess_observation(
    conn: sqlite3.Connection,
    watch: Watch,
    observation: Observation,
    before: Optional[datetime] = None,
) -> Assessment:
    """Avalia uma cotação contra a história da rota anterior a ela."""
    model, samples = route_model_for(conn, watch, before=before or observation.observed_at)
    return analytics.assess(
        price=observation.price_per_pax,
        departure_date=observation.departure_date,
        days_to_departure=observation.days_to_departure,
        history=samples,
        model=model,
        currency=observation.currency,
    )


def _should_alert(
    conn: sqlite3.Connection, config: Config, watch: Watch, assessment: Assessment, now: datetime
) -> bool:
    """Evita repetir o mesmo alerta: só repete se melhorar ou se o prazo passar."""
    if assessment.severity < 1:
        return False
    previous = db.last_alert_for_watch(conn, watch.id) if watch.id else None
    if previous is None or previous.created_at is None:
        return True
    if now - previous.created_at >= timedelta(hours=config.alert_cooldown_hours):
        return True
    if assessment.severity > previous.severity:
        return True
    improve = 1.0 - (config.alert_improve_pct / 100.0)
    return assessment.price <= previous.price * improve


def _apply_target_price(watch: Watch, assessment: Assessment, observation: Observation) -> None:
    """O preço-alvo do usuário vale como alerta mesmo sem sinal estatístico."""
    if watch.target_price is None or observation.price > watch.target_price:
        return
    if assessment.severity < 1:
        assessment.severity = 1
        assessment.verdict = "target_hit"
    assessment.reasons.insert(
        0, f"Atingiu o preço-alvo definido ({analytics.fmt_num(watch.target_price)})."
    )


def emit_alert(
    conn: sqlite3.Connection,
    config: Config,
    watch: Watch,
    observation: Observation,
    assessment: Assessment,
    notifier: Optional[Notifier] = None,
    now: Optional[datetime] = None,
) -> Optional[Alert]:
    """Grava e notifica o alerta, se a avaliação justificar."""
    now = now or datetime.now()
    _apply_target_price(watch, assessment, observation)
    if not _should_alert(conn, config, watch, assessment, now):
        return None

    alert = Alert(
        watch_id=watch.id,
        observation_id=observation.id,
        created_at=now,
        verdict=assessment.verdict,
        severity=assessment.severity,
        price=observation.price,
        expected_price=assessment.expected_price * max(1, watch.passengers),
        discount_pct=assessment.discount_pct,
        z_score=assessment.z_score,
        percentile=assessment.percentile,
        confidence=assessment.confidence,
        deal_score=assessment.deal_score,
        message=headline(watch, assessment),
        payload=alert_payload(watch, assessment, observation),
    )
    alert.id = db.insert_alert(conn, alert)

    if notifier is not None:
        notifier.send(watch, assessment, observation, alert)
        db.mark_alert_notified(conn, alert.id)
        alert.notified = True
    return alert


def evaluate_and_alert(
    conn: sqlite3.Connection,
    config: Config,
    watch: Watch,
    observation: Observation,
    notifier: Optional[Notifier] = None,
    now: Optional[datetime] = None,
) -> tuple:
    """Avalia uma cotação já gravada e dispara o alerta, se for o caso."""
    now = now or datetime.now()
    assessment = assess_observation(conn, watch, observation, before=observation.observed_at)
    alert = emit_alert(conn, config, watch, observation, assessment, notifier, now)
    return assessment, alert


def collect_watch(
    conn: sqlite3.Connection,
    config: Config,
    provider: Provider,
    watch: Watch,
    notifier: Optional[Notifier] = None,
    now: Optional[datetime] = None,
) -> WatchResult:
    """Cota uma rota monitorada e avalia o melhor preço encontrado."""
    now = now or datetime.now()
    result = WatchResult(watch=watch)

    dates = candidate_dates(watch, now.date())
    if not dates:
        result.error = "Sem data de ida futura para cotar (defina ou atualize a data)."
        return result

    collected: List[Observation] = []
    errors: List[str] = []
    for departure in dates:
        query = build_query(watch, departure, now.date(), config.max_offers)
        try:
            offer = provider.cheapest(query)
        except ProviderError as exc:
            errors.append(str(exc))
            continue
        except Exception as exc:  # falha inesperada do provedor
            errors.append(f"{type(exc).__name__}: {exc}")
            continue
        if offer is None:
            continue
        collected.append(offer_to_observation(watch, offer, query, provider.name, now))

    if not collected:
        result.error = errors[0] if errors else "Nenhuma oferta retornada pelo provedor."
        return result

    best = min(collected, key=lambda o: o.price_per_pax)

    # A avaliação precisa acontecer contra a história *anterior*; por isso o
    # modelo é ajustado antes de gravar as novas cotações.
    assessment = assess_observation(conn, watch, best, before=now)

    for obs in collected:
        obs.id = db.insert_observation(conn, obs, commit=False)
    conn.commit()
    if watch.id:
        db.touch_watch(conn, watch.id, now)

    alert = emit_alert(conn, config, watch, best, assessment, notifier, now)

    result.observations = collected
    result.best = best
    result.assessment = assessment
    result.alert = alert
    return result


def run_collection(
    conn: sqlite3.Connection,
    config: Config,
    provider: Provider,
    watch_ids: Optional[Sequence[int]] = None,
    notifier: Optional[Notifier] = None,
    now: Optional[datetime] = None,
) -> List[WatchResult]:
    """Roda uma rodada completa de coleta sobre as rotas ativas."""
    watches = db.list_watches(conn, only_active=True)
    if watch_ids:
        wanted = set(watch_ids)
        watches = [w for w in watches if w.id in wanted]
    return [
        collect_watch(conn, config, provider, watch, notifier=notifier, now=now)
        for watch in watches
    ]


def watch_snapshot(conn: sqlite3.Connection, watch: Watch) -> dict:
    """Estado atual de uma rota monitorada, para dashboard e API."""
    latest = db.latest_observation(conn, watch.id) if watch.id else None
    model, samples = route_model_for(conn, watch)
    assessment = None
    if latest is not None:
        history = [s for s in samples if s.observation_id != latest.id]
        assessment = analytics.assess(
            price=latest.price_per_pax,
            departure_date=latest.departure_date,
            days_to_departure=latest.days_to_departure,
            history=history,
            model=analytics.fit_route_model(history),
            currency=latest.currency,
        )
    return {
        "watch": watch,
        "latest": latest,
        "assessment": assessment,
        "model": model,
        "n_samples": len(samples),
    }
