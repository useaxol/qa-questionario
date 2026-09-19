"""Estruturas de dados compartilhadas pelo monitor."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, Optional

CABINS = ("ECONOMY", "PREMIUM_ECONOMY", "BUSINESS", "FIRST")
TRIP_TYPES = ("round", "oneway")

CABIN_LABELS = {
    "ECONOMY": "Econômica",
    "PREMIUM_ECONOMY": "Econômica premium",
    "BUSINESS": "Executiva",
    "FIRST": "Primeira classe",
}


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
    """Uma rota/data monitorada continuamente."""

    id: Optional[int] = None
    label: str = ""
    origin: str = ""
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
    def route_key(self) -> str:
        """Chave usada para agrupar o histórico comparável."""
        return f"{self.origin}-{self.destination}|{self.trip_type}|{self.cabin}|{self.currency}"

    @property
    def display_name(self) -> str:
        if self.label:
            return self.label
        return self.route

    def days_to_departure(self, ref: Optional[date] = None) -> Optional[int]:
        if self.departure_date is None:
            return None
        return (self.departure_date - (ref or date.today())).days

    def trip_length_days(self) -> Optional[int]:
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
class Observation:
    """Uma cotação registrada em um instante do tempo."""

    id: Optional[int] = None
    watch_id: Optional[int] = None
    origin: str = ""
    destination: str = ""
    departure_date: Optional[date] = None
    return_date: Optional[date] = None
    trip_type: str = "round"
    cabin: str = "ECONOMY"
    passengers: int = 1
    currency: str = "BRL"
    price: float = 0.0
    price_per_pax: float = 0.0
    airline: Optional[str] = None
    stops: Optional[int] = None
    duration_minutes: Optional[int] = None
    provider: str = ""
    source: str = "quote"  # quote | metric (estatística externa) | seed
    weight: float = 1.0
    observed_at: Optional[datetime] = None
    days_to_departure: Optional[int] = None

    @property
    def route_key(self) -> str:
        return f"{self.origin}-{self.destination}|{self.trip_type}|{self.cabin}|{self.currency}"

    @classmethod
    def from_row(cls, row: Any) -> "Observation":
        return cls(
            id=row["id"],
            watch_id=row["watch_id"],
            origin=row["origin"],
            destination=row["destination"],
            departure_date=parse_date(row["departure_date"]),
            return_date=parse_date(row["return_date"]),
            trip_type=row["trip_type"],
            cabin=row["cabin"],
            passengers=row["passengers"] or 1,
            currency=row["currency"],
            price=row["price"],
            price_per_pax=row["price_per_pax"],
            airline=row["airline"],
            stops=row["stops"],
            duration_minutes=row["duration_minutes"],
            provider=row["provider"],
            source=row["source"],
            weight=row["weight"] if row["weight"] is not None else 1.0,
            observed_at=parse_datetime(row["observed_at"]),
            days_to_departure=row["days_to_departure"],
        )


@dataclass
class Alert:
    id: Optional[int] = None
    watch_id: Optional[int] = None
    observation_id: Optional[int] = None
    created_at: Optional[datetime] = None
    verdict: str = ""
    severity: int = 0
    price: float = 0.0
    expected_price: float = 0.0
    discount_pct: float = 0.0
    z_score: float = 0.0
    percentile: float = 0.0
    confidence: str = ""
    deal_score: float = 0.0
    message: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    notified: bool = False

    @property
    def delta_pct(self) -> float:
        if not self.expected_price:
            return 0.0
        return 100.0 * (self.price / self.expected_price - 1.0)

    @property
    def delta_label(self) -> str:
        delta = self.delta_pct
        if abs(delta) < 0.5:
            return "no padrão"
        return f"{abs(delta):.0f}% {'acima' if delta > 0 else 'abaixo'}"

    @classmethod
    def from_row(cls, row: Any) -> "Alert":
        import json

        return cls(
            id=row["id"],
            watch_id=row["watch_id"],
            observation_id=row["observation_id"],
            created_at=parse_datetime(row["created_at"]),
            verdict=row["verdict"],
            severity=row["severity"],
            price=row["price"],
            expected_price=row["expected_price"],
            discount_pct=row["discount_pct"],
            z_score=row["z_score"],
            percentile=row["percentile"],
            confidence=row["confidence"],
            deal_score=row["deal_score"],
            message=row["message"],
            payload=json.loads(row["payload"]) if row["payload"] else {},
            notified=bool(row["notified"]),
        )
