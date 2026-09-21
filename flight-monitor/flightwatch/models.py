"""Estruturas de dados persistidas pelo monitor."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional

CABINS = ("ECONOMY", "PREMIUM_ECONOMY", "BUSINESS", "FIRST")
CABIN_LABELS = {
    "ECONOMY": "Econômica",
    "PREMIUM_ECONOMY": "Econômica premium",
    "BUSINESS": "Executiva",
    "FIRST": "Primeira classe",
}

#: Uma cotação nasce da cesta padrão (medição de mercado) ou de uma viagem que
#: o usuário pediu para acompanhar.
KIND_BASKET = "basket"
KIND_WATCH = "watch"


def parse_date(value: Any) -> Optional[date]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def parse_datetime(value: Any) -> Optional[datetime]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


@dataclass
class Watch:
    """Uma viagem concreta que o usuário quer acompanhar."""

    id: Optional[int] = None
    label: str = ""
    origin: str = "GRU"
    destination: str = ""
    departure_date: Optional[date] = None
    return_date: Optional[date] = None
    flex_days: int = 0
    trip_type: str = "round"
    cabin: str = "ECONOMY"
    passengers: int = 1
    currency: str = "BRL"
    max_stops: Optional[int] = None
    target_price: Optional[float] = None
    active: bool = True
    created_at: Optional[datetime] = None
    last_checked_at: Optional[datetime] = None

    @property
    def route(self) -> str:
        return f"{self.origin}-{self.destination}"

    @property
    def display_name(self) -> str:
        return self.label or self.route

    def days_to_departure(self, ref: Optional[date] = None) -> Optional[int]:
        if self.departure_date is None:
            return None
        return (self.departure_date - (ref or date.today())).days

    def nights(self) -> Optional[int]:
        if self.departure_date is None or self.return_date is None:
            return None
        return (self.return_date - self.departure_date).days

    @classmethod
    def from_row(cls, row: Any) -> "Watch":
        return cls(
            id=row["id"],
            label=row["label"] or "",
            origin=row["origin"],
            destination=row["destination"],
            departure_date=parse_date(row["departure_date"]),
            return_date=parse_date(row["return_date"]),
            flex_days=row["flex_days"] or 0,
            trip_type=row["trip_type"],
            cabin=row["cabin"],
            passengers=row["passengers"] or 1,
            currency=row["currency"],
            max_stops=row["max_stops"],
            target_price=row["target_price"],
            active=bool(row["active"]),
            created_at=parse_datetime(row["created_at"]),
            last_checked_at=parse_datetime(row["last_checked_at"]),
        )


@dataclass
class Quote:
    """Uma cotação gravada, já com seu índice contra o benchmark."""

    id: Optional[int] = None
    watch_id: Optional[int] = None
    kind: str = KIND_BASKET
    round_id: str = ""
    origin: str = "GRU"
    destination: str = ""
    departure_date: Optional[date] = None
    return_date: Optional[date] = None
    days_to_departure: int = 0
    cabin: str = "ECONOMY"
    passengers: int = 1
    currency: str = "BRL"
    price: float = 0.0
    benchmark: float = 0.0
    index_value: float = 100.0
    base_used: float = 0.0
    airline: Optional[str] = None
    stops: Optional[int] = None
    duration_minutes: Optional[int] = None
    provider: str = ""
    collected_at: Optional[datetime] = None

    @property
    def gap_pct(self) -> float:
        return self.index_value - 100.0

    @classmethod
    def from_row(cls, row: Any) -> "Quote":
        return cls(
            id=row["id"],
            watch_id=row["watch_id"],
            kind=row["kind"],
            round_id=row["round_id"] or "",
            origin=row["origin"],
            destination=row["destination"],
            departure_date=parse_date(row["departure_date"]),
            return_date=parse_date(row["return_date"]),
            days_to_departure=row["days_to_departure"] or 0,
            cabin=row["cabin"],
            passengers=row["passengers"] or 1,
            currency=row["currency"],
            price=row["price"],
            benchmark=row["benchmark"],
            index_value=row["index_value"],
            base_used=row["base_used"] or 0.0,
            airline=row["airline"],
            stops=row["stops"],
            duration_minutes=row["duration_minutes"],
            provider=row["provider"],
            collected_at=parse_datetime(row["collected_at"]),
        )


@dataclass
class BasketSnapshot:
    """O índice de mercado em um instante."""

    id: Optional[int] = None
    round_id: str = ""
    collected_at: Optional[datetime] = None
    index_value: float = 100.0
    dispersion: float = 0.0
    size: int = 0
    currency: str = "BRL"

    @classmethod
    def from_row(cls, row: Any) -> "BasketSnapshot":
        return cls(
            id=row["id"],
            round_id=row["round_id"] or "",
            collected_at=parse_datetime(row["collected_at"]),
            index_value=row["index_value"],
            dispersion=row["dispersion"] or 0.0,
            size=row["size"] or 0,
            currency=row["currency"],
        )


@dataclass
class Alert:
    id: Optional[int] = None
    watch_id: Optional[int] = None
    quote_id: Optional[int] = None
    created_at: Optional[datetime] = None
    destination: str = ""
    kind: str = KIND_BASKET
    level: int = 0
    driver: str = "none"
    price: float = 0.0
    benchmark: float = 0.0
    index_value: float = 100.0
    basket_index: Optional[float] = None
    distortion: Optional[float] = None
    signal: float = 0.0
    score: float = 0.0
    currency: str = "BRL"
    message: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    notified: bool = False

    @property
    def gap_pct(self) -> float:
        return self.index_value - 100.0

    @property
    def gap_label(self) -> str:
        gap = self.gap_pct
        if abs(gap) < 0.5:
            return "no benchmark"
        return f"{abs(gap):.0f}% {'acima' if gap > 0 else 'abaixo'}"

    @classmethod
    def from_row(cls, row: Any) -> "Alert":
        return cls(
            id=row["id"],
            watch_id=row["watch_id"],
            quote_id=row["quote_id"],
            created_at=parse_datetime(row["created_at"]),
            destination=row["destination"],
            kind=row["kind"],
            level=row["level"],
            driver=row["driver"],
            price=row["price"],
            benchmark=row["benchmark"],
            index_value=row["index_value"],
            basket_index=row["basket_index"],
            distortion=row["distortion"],
            signal=row["signal"],
            score=row["score"],
            currency=row["currency"],
            message=row["message"],
            payload=json.loads(row["payload"]) if row["payload"] else {},
            notified=bool(row["notified"]),
        )


@dataclass
class BaseOverride:
    """Preço-base recalibrado de um destino, substituindo o da tabela."""

    destination: str
    base_price: float
    updated_at: Optional[datetime] = None
    n_quotes: int = 0
    change_pct: float = 0.0
    note: str = ""

    @classmethod
    def from_row(cls, row: Any) -> "BaseOverride":
        return cls(
            destination=row["destination"],
            base_price=row["base_price"],
            updated_at=parse_datetime(row["updated_at"]),
            n_quotes=row["n_quotes"] or 0,
            change_pct=row["change_pct"] or 0.0,
            note=row["note"] or "",
        )
