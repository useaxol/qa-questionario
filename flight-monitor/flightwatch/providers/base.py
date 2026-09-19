"""Contrato comum dos provedores de cotação."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional


class ProviderError(RuntimeError):
    """Falha ao consultar um provedor (rede, credencial, resposta inválida)."""


@dataclass
class SearchQuery:
    origin: str
    destination: str
    departure_date: date
    return_date: Optional[date] = None
    trip_type: str = "round"
    cabin: str = "ECONOMY"
    passengers: int = 1
    currency: str = "BRL"
    max_stops: Optional[int] = None
    max_offers: int = 20
    #: Data em que a cotação está sendo feita. Permite reconstruir histórico
    #: com provedores que suportam simulação/backfill.
    as_of: Optional[date] = None

    @property
    def days_to_departure(self) -> int:
        ref = self.as_of or date.today()
        return (self.departure_date - ref).days


@dataclass
class Offer:
    price: float
    currency: str
    airline: Optional[str] = None
    stops: Optional[int] = None
    duration_minutes: Optional[int] = None
    departure_date: Optional[date] = None
    return_date: Optional[date] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    def price_per_pax(self, passengers: int) -> float:
        return self.price / max(1, passengers)


class Provider(ABC):
    """Fonte de cotações de passagem."""

    name: str = "base"
    #: Provedores que conseguem cotar uma data passada (simuladores) permitem
    #: reconstruir histórico com o comando `backfill`.
    supports_backfill: bool = False

    @abstractmethod
    def search(self, query: SearchQuery) -> List[Offer]:
        """Retorna as ofertas disponíveis para a consulta."""

    def price_metrics(self, query: SearchQuery) -> Optional[Dict[str, float]]:
        """Quartis históricos de preço da rota, quando o provedor oferecer.

        Usado para dar um ponto de partida ao modelo antes de acumular história
        própria. Retorna algo como {"min":.., "q1":.., "median":.., "q3":.., "max":..}.
        """
        return None

    def cheapest(self, query: SearchQuery) -> Optional[Offer]:
        offers = self.search(query)
        if query.max_stops is not None:
            filtered = [o for o in offers if o.stops is None or o.stops <= query.max_stops]
            offers = filtered or offers
        if not offers:
            return None
        return min(offers, key=lambda o: o.price)
