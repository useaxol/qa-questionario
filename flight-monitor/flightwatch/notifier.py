"""Saída dos alertas: console, arquivo JSONL e webhook."""
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

from . import airports, benchmarks
from .indexing import Verdict
from .models import CABIN_LABELS, Quote, Watch

LEVEL_MARK = {1: "🟢", 2: "🔵", 3: "🟣", 4: "⚠️"}


def format_money(value: float, currency: str = "BRL") -> str:
    symbol = {"BRL": "R$", "USD": "US$", "EUR": "€", "GBP": "£"}.get(
        (currency or "BRL").upper(), (currency or "").upper() + " "
    )
    return f"{symbol}{value:,.0f}".replace(",", ".")


def headline(verdict: Verdict, watch: Optional[Watch] = None) -> str:
    mark = LEVEL_MARK.get(verdict.level, "🔔")
    city = airports.city_of(verdict.destination)
    name = watch.display_name if watch and watch.label else city
    price = format_money(verdict.price, verdict.currency)
    if verdict.distortion is not None and verdict.driver in ("distortion", "both"):
        return (
            f"{mark} {name} por {price} — índice {verdict.index:.0f} contra "
            f"cesta em {verdict.basket_index:.0f} ({verdict.distortion:+.0f} pontos) — {verdict.label}"
        )
    return f"{mark} {name} por {price} — índice {verdict.index:.0f} ({verdict.gap_label}) — {verdict.label}"


def format_alert_text(
    verdict: Verdict, quote: Optional[Quote] = None, watch: Optional[Watch] = None
) -> str:
    lines: List[str] = [headline(verdict, watch)]

    origin = (quote.origin if quote else None) or (watch.origin if watch else benchmarks.BASE_ORIGIN)
    trip = f"{airports.label(origin)} → {airports.label(verdict.destination)}"
    lines.append(f"   {trip}")

    if quote and quote.departure_date:
        detail = f"ida {quote.departure_date.strftime('%d/%m/%Y')}"
        if quote.return_date:
            detail += f" · volta {quote.return_date.strftime('%d/%m/%Y')}"
        detail += f" · {quote.days_to_departure} dias de antecedência"
        lines.append(f"   {detail}")
        lines.append(
            f"   {CABIN_LABELS.get(quote.cabin, quote.cabin)} · {quote.passengers} pax"
            + (f" · {quote.airline}" if quote.airline else "")
            + (
                f" · {'direto' if quote.stops == 0 else str(quote.stops) + ' parada(s)'}"
                if quote.stops is not None
                else ""
            )
        )

    lines.append(
        f"   benchmark {format_money(verdict.benchmark, verdict.currency)} · "
        f"índice {verdict.index:.0f} · sinal {verdict.signal:.1f} banda(s) · "
        f"nota {verdict.score:.0f}/100"
    )
    for reason in verdict.reasons:
        lines.append(f"   • {reason}")
    return "\n".join(lines)


def alert_payload(
    verdict: Verdict, quote: Optional[Quote] = None, watch: Optional[Watch] = None
) -> Dict[str, Any]:
    return {
        "destination": verdict.destination,
        "destination_label": airports.label(verdict.destination),
        "watch": (
            {
                "id": watch.id,
                "label": watch.display_name,
                "origin": watch.origin,
                "departure_date": watch.departure_date.isoformat() if watch.departure_date else None,
                "return_date": watch.return_date.isoformat() if watch.return_date else None,
                "cabin": watch.cabin,
                "passengers": watch.passengers,
            }
            if watch
            else None
        ),
        "quote": (
            {
                "price": quote.price,
                "currency": quote.currency,
                "departure_date": quote.departure_date.isoformat() if quote.departure_date else None,
                "return_date": quote.return_date.isoformat() if quote.return_date else None,
                "days_to_departure": quote.days_to_departure,
                "airline": quote.airline,
                "stops": quote.stops,
                "provider": quote.provider,
                "collected_at": quote.collected_at.isoformat() if quote.collected_at else None,
            }
            if quote
            else None
        ),
        "verdict": verdict.as_dict(),
        "text": format_alert_text(verdict, quote, watch),
    }


class Notifier(ABC):
    @abstractmethod
    def send(self, verdict: Verdict, quote: Optional[Quote], watch: Optional[Watch],
             alert: Optional[Any] = None) -> None:
        ...


class ConsoleNotifier(Notifier):
    def send(self, verdict, quote, watch, alert=None) -> None:
        print(format_alert_text(verdict, quote, watch), flush=True)


class JsonlFileNotifier(Notifier):
    """Append de um JSON por linha — fácil de consumir por outro processo."""

    def __init__(self, path: str):
        self.path = path

    def send(self, verdict, quote, watch, alert=None) -> None:
        directory = os.path.dirname(os.path.abspath(self.path))
        if directory:
            os.makedirs(directory, exist_ok=True)
        payload = alert_payload(verdict, quote, watch)
        payload["alert_id"] = alert.id if alert else None
        payload["created_at"] = datetime.now().isoformat()
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


class WebhookNotifier(Notifier):
    """POST JSON. `text` e `content` deixam o payload pronto para Slack e Discord."""

    def __init__(self, url: str, timeout: int = 15):
        self.url = url
        self.timeout = timeout

    def send(self, verdict, quote, watch, alert=None) -> None:
        if requests is None:  # pragma: no cover
            print("[flightwatch] webhook ignorado: pacote 'requests' ausente.")
            return
        payload = alert_payload(verdict, quote, watch)
        payload["content"] = payload["text"]
        try:
            requests.post(self.url, json=payload, timeout=self.timeout)
        except Exception as exc:
            print(f"[flightwatch] falha ao enviar webhook: {exc}")


class CompositeNotifier(Notifier):
    def __init__(self, notifiers: List[Notifier]):
        self.notifiers = notifiers

    def send(self, verdict, quote, watch, alert=None) -> None:
        for notifier in self.notifiers:
            try:
                notifier.send(verdict, quote, watch, alert)
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
