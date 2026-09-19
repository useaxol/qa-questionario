"""Provedor simulado: preços plausíveis e *determinísticos* para qualquer rota.

Serve a dois propósitos concretos:

* permitir rodar e avaliar o monitor sem credencial de API (inclusive gerando
  história passada, algo que nenhuma API pública de tarifa entrega);
* servir de banco de testes para o modelo estatístico — como o gerador conhece
  a sazonalidade e a curva de antecedência "verdadeiras", dá para verificar se
  o modelo as recupera.

O preço é reconstruído a partir da distância geográfica real entre os
aeroportos, da estação do ano no destino, dos feriados, da antecedência da
compra e de um ruído determinístico (mesma consulta => mesmo preço).
"""
from __future__ import annotations

import math
import zlib
from datetime import date, timedelta
from typing import List, Optional

from .. import airports
from .base import Offer, Provider, SearchQuery

#: Conversão aproximada a partir de USD. É uma tabela fixa, suficiente para a
#: simulação — o provedor real devolve o preço já na moeda pedida.
FX_FROM_USD = {
    "USD": 1.0,
    "BRL": 5.40,
    "EUR": 0.92,
    "GBP": 0.79,
    "ARS": 1015.0,
    "CLP": 940.0,
    "MXN": 17.2,
    "CAD": 1.36,
    "AUD": 1.52,
    "JPY": 152.0,
    "CHF": 0.88,
    "ZAR": 18.3,
}

CABIN_MULTIPLIER = {
    "ECONOMY": 1.0,
    "PREMIUM_ECONOMY": 2.05,
    "BUSINESS": 3.60,
    "FIRST": 6.40,
}

AIRLINES = (
    "LA", "G3", "AD", "TP", "IB", "AF", "KL", "LH", "UA", "AA", "DL", "EK",
    "QR", "TK", "AZ", "BA", "CM", "AV", "AC", "QF", "SQ", "JL",
)


def _hash_unit(*parts: object) -> float:
    """Número determinístico em [0,1) a partir de qualquer chave."""
    key = "|".join(str(p) for p in parts).encode("utf-8")
    return (zlib.crc32(key) % 1_000_000) / 1_000_000.0


def _hash_normal(*parts: object) -> float:
    """Normal padrão determinística (Box-Muller sobre dois hashes)."""
    u1 = min(0.999999, max(1e-6, _hash_unit("n1", *parts)))
    u2 = _hash_unit("n2", *parts)
    return math.sqrt(-2.0 * math.log(u1)) * math.cos(2 * math.pi * u2)


def base_price_usd(origin: str, destination: str) -> float:
    """Preço-base de ida, em USD, a partir da distância real da rota."""
    distance = airports.distance_km(origin, destination)
    base = 40.0 + 0.11 * (distance ** 0.92)
    # Prêmio/desconto estrutural da rota (concorrência, hub, sazonalidade de oferta).
    route_factor = 0.85 + 0.35 * _hash_unit("route", origin, destination)
    return base * route_factor


def season_factor(departure: date, origin: str, destination: str) -> float:
    """Quanto a época do ano encarece/barateia a viagem.

    A demanda tem duas pernas: as férias no mercado de *origem* (quem compra) e
    o verão no *destino* (o que se quer comprar). Uma passagem São Paulo-Lisboa
    em janeiro é cara por férias no Brasil, mesmo sendo inverno em Portugal.
    """
    doy = departure.timetuple().tm_yday

    def summer_phase(iata: str) -> float:
        airport = airports.get(iata)
        lat = airport.lat if airport else 0.0
        # Alta estação segue o verão local (jul no hemisfério N, jan no S).
        peak_doy = 196.0 if lat >= 0 else 14.0
        # Perto do equador a estação quase não pesa.
        amplitude = min(1.0, abs(lat) / 35.0)
        return amplitude * math.cos(2 * math.pi * (doy - peak_doy) / 365.25)

    phase = 0.55 * summer_phase(origin) + 0.45 * summer_phase(destination)
    factor = 1.0 + 0.18 * phase

    month, day = departure.month, departure.day
    if month == 12 and day >= 14:
        factor *= 1.38            # festas de fim de ano
    elif month == 1 and day <= 8:
        factor *= 1.30            # volta do réveillon
    elif month == 7:
        factor *= 1.12            # férias escolares (hemisfério norte e BR)
    elif month == 1 and day >= 9:
        factor *= 1.06            # janeiro ainda em alta no hemisfério sul
    elif month in (2,) and 8 <= day <= 20:
        factor *= 1.10            # carnaval (aproximado)
    elif month in (4,) and 1 <= day <= 12:
        factor *= 1.08            # semana santa (aproximada)
    elif month in (5, 9, 10, 11):
        factor *= 0.95            # baixa estação clássica
    return factor


def advance_factor(days_to_departure: int) -> float:
    """Curva de antecedência: última hora é caro, muito cedo é levemente caro."""
    dtd = max(0, days_to_departure)
    knots = (
        (0, 2.10), (3, 1.78), (7, 1.50), (14, 1.29), (21, 1.15), (30, 1.05),
        (45, 1.00), (60, 0.97), (90, 0.97), (120, 1.00), (180, 1.05), (330, 1.10),
    )
    if dtd >= knots[-1][0]:
        return knots[-1][1]
    for (x0, y0), (x1, y1) in zip(knots, knots[1:]):
        if x0 <= dtd <= x1:
            t = (dtd - x0) / (x1 - x0) if x1 > x0 else 0.0
            return y0 + t * (y1 - y0)
    return 1.0


def weekday_factor(departure: date) -> float:
    return {0: 0.98, 1: 0.94, 2: 0.94, 3: 1.00, 4: 1.08, 5: 1.02, 6: 1.07}[departure.weekday()]


def trip_length_factor(departure: date, ret: Optional[date]) -> float:
    if ret is None:
        return 1.0
    nights = max(1, (ret - departure).days)
    if nights <= 2:
        return 1.12      # bate-volta costuma ser tarifa de executivo
    if nights <= 6:
        return 1.03
    if nights <= 21:
        return 1.0
    return 1.05          # estadias muito longas saem das tarifas promocionais


def sale_factor(origin: str, destination: str, as_of: date) -> float:
    """Promoções relâmpago: raras, fortes e com alguns dias de duração."""
    window = as_of.toordinal() // 4          # janelas de ~4 dias
    if _hash_unit("sale", origin, destination, window) < 0.055:
        return 0.62 + 0.20 * _hash_unit("saledepth", origin, destination, window)
    return 1.0


def market_drift(origin: str, destination: str, as_of: date) -> float:
    """Oscilação lenta de mercado (combustível, câmbio, capacidade)."""
    months = as_of.year * 12 + as_of.month
    phase = 2 * math.pi * ((months + 7 * _hash_unit("drift", origin, destination)) % 18) / 18.0
    return 1.0 + 0.07 * math.sin(phase)


class SyntheticProvider(Provider):
    """Gerador determinístico de cotações."""

    name = "synthetic"
    supports_backfill = True

    def __init__(self, seed: str = "flightwatch", noise_sigma: float = 0.10):
        self.seed = seed
        self.noise_sigma = noise_sigma

    # -- preço de referência (sem ruído), útil para testes do modelo
    def fair_price(self, query: SearchQuery) -> float:
        as_of = query.as_of or date.today()
        usd = base_price_usd(query.origin, query.destination)
        usd *= season_factor(query.departure_date, query.origin, query.destination)
        usd *= advance_factor((query.departure_date - as_of).days)
        usd *= weekday_factor(query.departure_date)
        usd *= CABIN_MULTIPLIER.get(query.cabin, 1.0)
        if query.trip_type == "round" and query.return_date is not None:
            usd *= 1.85 * trip_length_factor(query.departure_date, query.return_date)
        elif query.trip_type == "round":
            usd *= 1.85
        usd *= market_drift(query.origin, query.destination, as_of)
        return usd * FX_FROM_USD.get(query.currency.upper(), 1.0)

    def search(self, query: SearchQuery) -> List[Offer]:
        as_of = query.as_of or date.today()
        if (query.departure_date - as_of).days < 0:
            return []

        fair = self.fair_price(query)
        fair *= sale_factor(query.origin, query.destination, as_of)
        noise = math.exp(
            self.noise_sigma
            * _hash_normal(self.seed, query.origin, query.destination,
                           query.departure_date, query.return_date, as_of)
        )
        cheapest = fair * noise

        n_offers = 3 + int(5 * _hash_unit("count", query.origin, query.destination, as_of))
        n_offers = min(n_offers, max(1, query.max_offers))

        distance = airports.distance_km(query.origin, query.destination)
        base_minutes = int(55 + distance / 12.5)

        offers: List[Offer] = []
        for i in range(n_offers):
            spread = 1.0 + 0.085 * i + 0.05 * _hash_unit("spread", i, query.origin, as_of)
            # A oferta mais barata quase nunca é a direta.
            direct_bias = _hash_unit("direct", i, query.origin, query.destination, as_of)
            if distance < 1200:
                stops = 0 if direct_bias < 0.75 else 1
            else:
                stops = 0 if (i >= 1 and direct_bias < 0.45) else (1 if direct_bias < 0.85 else 2)
            price = cheapest * spread * (1.16 if stops == 0 and distance >= 1200 else 1.0)
            duration = base_minutes + stops * int(90 + 140 * _hash_unit("layover", i, as_of))
            airline = AIRLINES[
                int(_hash_unit("airline", i, query.origin, query.destination) * len(AIRLINES))
            ]
            offers.append(
                Offer(
                    price=round(price * max(1, query.passengers), 2),
                    currency=query.currency.upper(),
                    airline=airline,
                    stops=stops,
                    duration_minutes=duration,
                    departure_date=query.departure_date,
                    return_date=query.return_date,
                    raw={"simulated": True, "as_of": as_of.isoformat()},
                )
            )
        offers.sort(key=lambda o: o.price)
        return offers

    def price_metrics(self, query: SearchQuery) -> Optional[dict]:
        """Quartis simulados a partir de cotações em várias antecedências."""
        as_of = query.as_of or date.today()
        prices = []
        for back in range(0, 180, 7):
            probe_day = as_of - timedelta(days=back)
            if (query.departure_date - probe_day).days < 0:
                continue
            probe = SearchQuery(
                origin=query.origin,
                destination=query.destination,
                departure_date=query.departure_date,
                return_date=query.return_date,
                trip_type=query.trip_type,
                cabin=query.cabin,
                passengers=1,
                currency=query.currency,
                as_of=probe_day,
            )
            prices.append(self.fair_price(probe))
        if not prices:
            return None
        prices.sort()
        def q(p: float) -> float:
            return prices[min(len(prices) - 1, int(p * len(prices)))]
        return {
            "min": prices[0],
            "q1": q(0.25),
            "median": q(0.5),
            "q3": q(0.75),
            "max": prices[-1],
        }
