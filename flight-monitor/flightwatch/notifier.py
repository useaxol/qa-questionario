"""Saída dos alertas: console, arquivo JSONL e webhook (Slack/Discord/genérico)."""
from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore

from . import airports
from .analytics import Assessment
from .models import Alert, CABIN_LABELS, Observation, Watch

SEVERITY_EMOJI = {1: "🟢", 2: "🔵", 3: "🟣", 4: "⚠️"}


def format_money(value: float, currency: str) -> str:
    symbol = {"BRL": "R$", "USD": "US$", "EUR": "€", "GBP": "£"}.get(currency.upper(), currency.upper() + " ")
    formatted = f"{value:,.0f}".replace(",", " ")
    return f"{symbol}{formatted}"


def headline(watch: Watch, assessment: Assessment) -> str:
    emoji = SEVERITY_EMOJI.get(assessment.severity, "🔔")
    route = f"{airports.city_of(watch.origin)} → {airports.city_of(watch.destination)}"
    price = format_money(assessment.price, assessment.currency)
    if assessment.discount_pct >= 1:
        return (
            f"{emoji} {route} por {price} "
            f"({assessment.discount_pct:.0f}% abaixo do padrão) — {assessment.severity_label}"
        )
    return f"{emoji} {route} por {price} — {assessment.severity_label}"


def format_alert_text(watch: Watch, assessment: Assessment, observation: Optional[Observation]) -> str:
    lines: List[str] = [headline(watch, assessment)]
    dep = watch.departure_date.strftime("%d/%m/%Y") if watch.departure_date else "?"
    if observation and observation.departure_date:
        dep = observation.departure_date.strftime("%d/%m/%Y")
    trip = f"ida {dep}"
    ret_date = (observation.return_date if observation else None) or watch.return_date
    if ret_date:
        trip += f" · volta {ret_date.strftime('%d/%m/%Y')}"
    lines.append(
        f"   {airports.label(watch.origin)} → {airports.label(watch.destination)} · {trip}"
    )
    lines.append(
        f"   {CABIN_LABELS.get(watch.cabin, watch.cabin)} · {watch.passengers} pax · "
        f"preço esperado {format_money(assessment.expected_price, assessment.currency)} · "
        f"z={assessment.z_score:+.2f} · nota {assessment.deal_score:.0f}/100"
    )
    if observation and observation.airline:
        stops = "direto" if observation.stops == 0 else f"{observation.stops} parada(s)"
        lines.append(f"   Cia {observation.airline} · {stops}")
    for reason in assessment.reasons:
        lines.append(f"   • {reason}")
    return "\n".join(lines)


def alert_payload(watch: Watch, assessment: Assessment, observation: Optional[Observation]) -> Dict[str, Any]:
    return {
        "watch": {
            "id": watch.id,
            "label": watch.display_name,
            "origin": watch.origin,
            "destination": watch.destination,
            "origin_label": airports.label(watch.origin),
            "destination_label": airports.label(watch.destination),
            "departure_date": watch.departure_date.isoformat() if watch.departure_date else None,
            "return_date": watch.return_date.isoformat() if watch.return_date else None,
            "cabin": watch.cabin,
            "passengers": watch.passengers,
            "trip_type": watch.trip_type,
        },
        "offer": {
            "price": observation.price if observation else assessment.price,
            "price_per_pax": observation.price_per_pax if observation else assessment.price,
            "currency": assessment.currency,
            "airline": observation.airline if observation else None,
            "stops": observation.stops if observation else None,
            "departure_date": (
                observation.departure_date.isoformat()
                if observation and observation.departure_date
                else None
            ),
            "provider": observation.provider if observation else None,
            "observed_at": (
                observation.observed_at.isoformat()
                if observation and observation.observed_at
                else datetime.now().isoformat()
            ),
        },
        "assessment": assessment.to_dict(),
        "text": format_alert_text(watch, assessment, observation),
    }


class Notifier(ABC):
    @abstractmethod
    def send(self, watch: Watch, assessment: Assessment, observation: Optional[Observation],
             alert: Optional[Alert] = None) -> None:
        ...


class ConsoleNotifier(Notifier):
    def send(self, watch, assessment, observation, alert=None) -> None:
        print(format_alert_text(watch, assessment, observation), flush=True)


class JsonlFileNotifier(Notifier):
    """Append de um JSON por linha — fácil de consumir por outro processo."""

    def __init__(self, path: str):
        self.path = path

    def send(self, watch, assessment, observation, alert=None) -> None:
        directory = os.path.dirname(os.path.abspath(self.path))
        if directory:
            os.makedirs(directory, exist_ok=True)
        payload = alert_payload(watch, assessment, observation)
        payload["alert_id"] = alert.id if alert else None
        payload["created_at"] = datetime.now().isoformat()
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


class WebhookNotifier(Notifier):
    """POST JSON. O campo `text` torna o payload compatível com Slack e Discord."""

    def __init__(self, url: str, timeout: int = 15):
        self.url = url
        self.timeout = timeout

    def send(self, watch, assessment, observation, alert=None) -> None:
        if requests is None:  # pragma: no cover
            print("[flightwatch] webhook ignorado: pacote 'requests' ausente.")
            return
        payload = alert_payload(watch, assessment, observation)
        payload["content"] = payload["text"]  # Discord usa 'content'
        try:
            requests.post(self.url, json=payload, timeout=self.timeout)
        except Exception as exc:  # não derruba a coleta por causa de um webhook
            print(f"[flightwatch] falha ao enviar webhook: {exc}")


class CompositeNotifier(Notifier):
    def __init__(self, notifiers: List[Notifier]):
        self.notifiers = notifiers

    def send(self, watch, assessment, observation, alert=None) -> None:
        for notifier in self.notifiers:
            try:
                notifier.send(watch, assessment, observation, alert)
            except Exception as exc:  # pragma: no cover
                print(f"[flightwatch] notificador {type(notifier).__name__} falhou: {exc}")


def build_notifier(config) -> Notifier:
    notifiers: List[Notifier] = []
    if config.notify_console:
        notifiers.append(ConsoleNotifier())
    if config.notify_file:
        notifiers.append(JsonlFileNotifier(config.notify_file))
    if config.webhook_url:
        notifiers.append(WebhookNotifier(config.webhook_url, timeout=config.request_timeout))
    return CompositeNotifier(notifiers)
