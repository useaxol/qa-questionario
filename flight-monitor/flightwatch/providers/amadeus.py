"""Provedor real, sobre a API Amadeus for Developers (Self-Service).

Endpoints usados:

* ``POST /v1/security/oauth2/token``          - autenticação (client credentials)
* ``GET  /v2/shopping/flight-offers``         - cotações do momento
* ``GET  /v1/analytics/itinerary-price-metrics`` - quartis históricos da rota

O último é o que permite ao monitor ter uma referência de preço já na primeira
coleta, antes de acumular história própria. Credenciais gratuitas de teste em
https://developers.amadeus.com — ambiente de teste tem dados limitados; para
produção, aponte AMADEUS_HOST para https://api.amadeus.com.
"""
from __future__ import annotations

import re
import time
from datetime import date, datetime
from typing import Any, Dict, List, Optional

try:  # requests é opcional: o provedor simulado não precisa dele
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore

from .base import Offer, Provider, ProviderError, SearchQuery

_DURATION_RE = re.compile(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?")


def parse_iso_duration(value: Optional[str]) -> Optional[int]:
    """Converte uma duração ISO-8601 (PT11H35M) em minutos."""
    if not value:
        return None
    match = _DURATION_RE.fullmatch(value)
    if not match:
        return None
    days, hours, minutes = (int(g) if g else 0 for g in match.groups())
    total = days * 1440 + hours * 60 + minutes
    return total or None


class AmadeusProvider(Provider):
    name = "amadeus"
    supports_backfill = False

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        host: str = "https://test.api.amadeus.com",
        timeout: int = 25,
    ):
        if requests is None:  # pragma: no cover
            raise ProviderError("O pacote 'requests' é necessário para o provedor Amadeus.")
        if not client_id or not client_secret:
            raise ProviderError(
                "Credenciais Amadeus ausentes. Defina AMADEUS_CLIENT_ID e AMADEUS_CLIENT_SECRET."
            )
        self.client_id = client_id
        self.client_secret = client_secret
        self.host = host.rstrip("/")
        self.timeout = timeout
        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0

    # ------------------------------------------------------------ auth

    def _access_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 30:
            return self._token
        try:
            response = requests.post(
                f"{self.host}/v1/security/oauth2/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=self.timeout,
            )
        except Exception as exc:  # rede
            raise ProviderError(f"Falha de rede ao autenticar na Amadeus: {exc}") from exc

        if response.status_code != 200:
            raise ProviderError(
                f"Amadeus recusou a autenticação ({response.status_code}): {response.text[:300]}"
            )
        payload = response.json()
        self._token = payload["access_token"]
        self._token_expires_at = time.time() + float(payload.get("expires_in", 1799))
        return self._token

    def _get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        token = self._access_token()
        try:
            response = requests.get(
                f"{self.host}{path}",
                params=params,
                headers={"Authorization": f"Bearer {token}"},
                timeout=self.timeout,
            )
        except Exception as exc:
            raise ProviderError(f"Falha de rede na Amadeus ({path}): {exc}") from exc

        if response.status_code == 429:
            raise ProviderError("Amadeus: limite de requisições atingido (429).")
        if response.status_code >= 400:
            raise ProviderError(
                f"Amadeus respondeu {response.status_code} em {path}: {response.text[:300]}"
            )
        return response.json()

    # ---------------------------------------------------------- busca

    def search(self, query: SearchQuery) -> List[Offer]:
        if query.as_of is not None and query.as_of != date.today():
            raise ProviderError(
                "A Amadeus só cota o preço de hoje; use o provedor 'synthetic' para backfill."
            )

        params: Dict[str, Any] = {
            "originLocationCode": query.origin.upper(),
            "destinationLocationCode": query.destination.upper(),
            "departureDate": query.departure_date.isoformat(),
            "adults": max(1, query.passengers),
            "currencyCode": query.currency.upper(),
            "max": min(50, max(1, query.max_offers)),
        }
        if query.trip_type == "round" and query.return_date:
            params["returnDate"] = query.return_date.isoformat()
        if query.cabin and query.cabin != "ECONOMY":
            params["travelClass"] = query.cabin
        if query.max_stops == 0:
            params["nonStop"] = "true"

        payload = self._get("/v2/shopping/flight-offers", params)
        return [
            offer
            for offer in (self._parse_offer(item, query) for item in payload.get("data", []))
            if offer is not None
        ]

    def _parse_offer(self, item: Dict[str, Any], query: SearchQuery) -> Optional[Offer]:
        try:
            price = float(item["price"]["grandTotal"])
        except (KeyError, TypeError, ValueError):
            try:
                price = float(item["price"]["total"])
            except (KeyError, TypeError, ValueError):
                return None

        itineraries = item.get("itineraries") or []
        segments = itineraries[0].get("segments", []) if itineraries else []
        stops = max(0, len(segments) - 1) if segments else None
        duration = parse_iso_duration(itineraries[0].get("duration")) if itineraries else None

        airline = None
        validating = item.get("validatingAirlineCodes") or []
        if validating:
            airline = validating[0]
        elif segments:
            airline = segments[0].get("carrierCode")

        departure_date = query.departure_date
        if segments:
            raw_at = (segments[0].get("departure") or {}).get("at")
            if raw_at:
                try:
                    departure_date = datetime.fromisoformat(raw_at).date()
                except ValueError:
                    pass

        return Offer(
            price=price,
            currency=(item.get("price") or {}).get("currency", query.currency).upper(),
            airline=airline,
            stops=stops,
            duration_minutes=duration,
            departure_date=departure_date,
            return_date=query.return_date,
            raw={"id": item.get("id"), "oneWay": item.get("oneWay")},
        )

    # ------------------------------------------- estatísticas históricas

    def price_metrics(self, query: SearchQuery) -> Optional[Dict[str, float]]:
        """Quartis de preço da rota, calculados pela Amadeus sobre dados históricos."""
        params = {
            "originIataCode": query.origin.upper(),
            "destinationIataCode": query.destination.upper(),
            "departureDate": query.departure_date.isoformat(),
            "currencyCode": query.currency.upper(),
            "oneWay": "false" if query.trip_type == "round" else "true",
        }
        try:
            payload = self._get("/v1/analytics/itinerary-price-metrics", params)
        except ProviderError:
            return None

        data = payload.get("data") or []
        if not data:
            return None
        metrics = {}
        for entry in data[0].get("priceMetrics", []):
            ranking = (entry.get("quartileRanking") or "").upper()
            try:
                amount = float(entry.get("amount"))
            except (TypeError, ValueError):
                continue
            metrics[
                {
                    "MINIMUM": "min",
                    "FIRST": "q1",
                    "MEDIUM": "median",
                    "THIRD": "q3",
                    "MAXIMUM": "max",
                }.get(ranking, ranking.lower())
            ] = amount
        return metrics or None
