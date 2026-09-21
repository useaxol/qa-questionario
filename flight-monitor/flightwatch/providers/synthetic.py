"""Provedor simulado: um mercado sintético ancorado na tabela de benchmark.

Serve a dois propósitos concretos:

* rodar e avaliar o app sem credencial de API;
* servir de banco de provas para a lógica de índice — como o simulador sabe
  qual destino ele colocou em promoção e quando moveu o mercado inteiro, os
  testes verificam se o app separa uma coisa da outra.

Para os destinos da cesta o preço nasce do próprio benchmark, movido por três
forças independentes e determinísticas:

    preço = benchmark × deriva_de_mercado × deriva_do_destino × promoção × ruído

`deriva_de_mercado` move os 10 juntos (câmbio, combustível) — é o que faz a
cesta subir e descer. `deriva_do_destino` e `promoção` movem um destino só —
é o que produz distorção. Para rotas fora da cesta, o preço cai num modelo
por distância geográfica, para que o provedor continue cotando o mundo todo.
"""
from __future__ import annotations

import math
import zlib
from datetime import date, timedelta
from typing import List, Optional

from .. import airports, benchmarks
from .base import Offer, Provider, SearchQuery

CABIN_MULTIPLIER = {
    "ECONOMY": 1.0,
    "PREMIUM_ECONOMY": 2.0,
    "BUSINESS": 3.5,
    "FIRST": 6.0,
}

AIRLINES = (
    "LA", "G3", "AD", "TP", "IB", "AF", "KL", "LH", "UA", "AA", "DL",
    "EK", "QR", "TK", "AZ", "BA", "CM", "AV", "AC", "JL", "NH",
)

#: Ida sozinha custa bem mais que metade da ida e volta.
ONEWAY_RATIO = 0.62


def _hash_unit(*parts: object) -> float:
    """Número determinístico em [0,1). crc32, não hash(): precisa ser estável entre execuções."""
    key = "|".join(str(p) for p in parts).encode("utf-8")
    return (zlib.crc32(key) % 1_000_000) / 1_000_000.0


def _hash_normal(*parts: object) -> float:
    u1 = min(0.999999, max(1e-6, _hash_unit("n1", *parts)))
    u2 = _hash_unit("n2", *parts)
    return math.sqrt(-2.0 * math.log(u1)) * math.cos(2 * math.pi * u2)


# --------------------------------------------------------- forças do mercado


def market_drift(as_of: date, amplitude: float = 0.06) -> float:
    """Movimento que atinge os 10 destinos juntos: câmbio, combustível, capacidade."""
    months = as_of.year * 12 + as_of.month + as_of.day / 31.0
    slow = math.sin(2 * math.pi * months / 17.0)
    fast = 0.4 * math.sin(2 * math.pi * months / 5.0)
    return 1.0 + amplitude * (slow + fast) / 1.4


def destination_drift(destination: str, as_of: date, amplitude: float = 0.08) -> float:
    """Movimento de um destino só: nova rota, mudança de capacidade, demanda local."""
    months = as_of.year * 12 + as_of.month + as_of.day / 31.0
    phase = 12.0 * _hash_unit("phase", destination)
    return 1.0 + amplitude * math.sin(2 * math.pi * (months + phase) / 11.0)


def sale_factor(destination: str, as_of: date, probability: float = 0.06) -> float:
    """Promoção relâmpago: rara, forte e com alguns dias de duração."""
    window = as_of.toordinal() // 4
    if _hash_unit("sale", destination, window) < probability:
        return 0.66 + 0.18 * _hash_unit("depth", destination, window)
    return 1.0


def weekday_factor(departure: date) -> float:
    return {0: 0.98, 1: 0.95, 2: 0.95, 3: 1.00, 4: 1.07, 5: 1.02, 6: 1.06}[departure.weekday()]


def trip_length_factor(departure: date, ret: Optional[date]) -> float:
    if ret is None:
        return 1.0
    nights = max(1, (ret - departure).days)
    if nights <= 2:
        return 1.12
    if nights <= 6:
        return 1.03
    if nights <= 21:
        return 1.0
    return 1.05


# ----------------------------------------------- rotas fora da cesta

#: Conversão aproximada a partir de USD, só para o modelo por distância.
FX_FROM_USD = {"USD": 1.0, "BRL": 5.40, "EUR": 0.92, "GBP": 0.79, "ARS": 1015.0}


def distance_price(query: SearchQuery, as_of: date) -> float:
    """Modelo de reserva: preço por distância, para destinos sem benchmark."""
    distance = airports.distance_km(query.origin, query.destination)
    usd = 40.0 + 0.11 * (distance ** 0.92)
    usd *= 0.85 + 0.35 * _hash_unit("route", query.origin, query.destination)
    usd *= benchmarks.advance_factor((query.departure_date - as_of).days)
    usd *= CABIN_MULTIPLIER.get(query.cabin, 1.0)
    if query.trip_type == "round":
        usd *= 1.85
    return usd * FX_FROM_USD.get(query.currency.upper(), 1.0)


class SyntheticProvider(Provider):
    """Gerador determinístico de cotações."""

    name = "synthetic"
    supports_backfill = True

    def __init__(
        self,
        seed: str = "flightwatch",
        noise_sigma: float = 0.07,
        sale_probability: float = 0.06,
        market_amplitude: float = 0.06,
        destination_amplitude: float = 0.08,
        bias: float = 1.0,
    ):
        self.seed = seed
        self.noise_sigma = noise_sigma
        self.sale_probability = sale_probability
        self.market_amplitude = market_amplitude
        self.destination_amplitude = destination_amplitude
        #: Desvio proposital do mercado em relação ao benchmark. Serve para
        #: testar a recalibração: com bias=1.2 a tabela está 20% defasada.
        self.bias = bias

    def fair_price(self, query: SearchQuery) -> float:
        """Preço "justo" da rota, sem ruído nem promoção."""
        as_of = query.as_of or date.today()
        days_to_departure = (query.departure_date - as_of).days

        if benchmarks.is_covered(query.destination):
            price = benchmarks.benchmark(
                query.destination,
                query.departure_date,
                days_to_departure,
                origin=query.origin,
                cabin=query.cabin,
                passengers=query.passengers,
            ).price
            if query.trip_type != "round":
                price *= ONEWAY_RATIO
            price *= trip_length_factor(query.departure_date, query.return_date)
        else:
            price = distance_price(query, as_of) * max(1, query.passengers)

        price *= weekday_factor(query.departure_date)
        price *= market_drift(as_of, self.market_amplitude)
        price *= destination_drift(query.destination, as_of, self.destination_amplitude)
        return price * self.bias

    def search(self, query: SearchQuery) -> List[Offer]:
        as_of = query.as_of or date.today()
        if (query.departure_date - as_of).days < 0:
            return []

        fair = self.fair_price(query)
        fair *= sale_factor(query.destination, as_of, self.sale_probability)
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
            spread = 1.0 + 0.08 * i + 0.04 * _hash_unit("spread", i, query.origin, as_of)
            direct_bias = _hash_unit("direct", i, query.origin, query.destination, as_of)
            if distance < 1200:
                stops = 0 if direct_bias < 0.75 else 1
            else:
                stops = 0 if (i >= 1 and direct_bias < 0.45) else (1 if direct_bias < 0.85 else 2)
            # A mais barata quase nunca é a direta.
            price = cheapest * spread * (1.14 if stops == 0 and distance >= 1200 else 1.0)
            offers.append(
                Offer(
                    price=round(price, 2),
                    currency=query.currency.upper(),
                    airline=AIRLINES[
                        int(_hash_unit("airline", i, query.origin, query.destination) * len(AIRLINES))
                    ],
                    stops=stops,
                    duration_minutes=base_minutes + stops * int(90 + 140 * _hash_unit("layover", i, as_of)),
                    departure_date=query.departure_date,
                    return_date=query.return_date,
                    raw={"simulated": True, "as_of": as_of.isoformat()},
                )
            )
        offers.sort(key=lambda o: o.price)
        return offers

    def price_metrics(self, query: SearchQuery) -> Optional[dict]:
        """Quartis simulados, sondando várias antecedências."""
        as_of = query.as_of or date.today()
        prices = []
        for back in range(0, 180, 7):
            probe_day = as_of - timedelta(days=back)
            if (query.departure_date - probe_day).days < 0:
                continue
            probe = SearchQuery(
                origin=query.origin, destination=query.destination,
                departure_date=query.departure_date, return_date=query.return_date,
                trip_type=query.trip_type, cabin=query.cabin, passengers=1,
                currency=query.currency, as_of=probe_day,
            )
            prices.append(self.fair_price(probe))
        if not prices:
            return None
        prices.sort()

        def q(p: float) -> float:
            return prices[min(len(prices) - 1, int(p * len(prices)))]

        return {"min": prices[0], "q1": q(0.25), "median": q(0.5), "q3": q(0.75), "max": prices[-1]}
