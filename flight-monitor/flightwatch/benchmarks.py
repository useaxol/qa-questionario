"""A tabela de benchmark: 10 destinos com preço de referência estabelecido.

Esta é a peça editorial do app — a única parte com números escritos à mão, e
de propósito. Sem ela o monitor precisaria de meses de histórico antes de
conseguir dizer se R$ 4.000 para Lisboa é caro ou barato. Com ela, funciona na
primeira execução.

O benchmark de um destino não é um número só; é uma função:

    benchmark = base × sazonalidade[mês] × antecedência[faixa]
                     × cabine × origem × passageiros

`base` é o preço de referência da ida e volta em econômica, 1 passageiro, saindo
de São Paulo, na média do ano. `sazonalidade` redistribui esse valor pelos meses
(férias brasileiras em janeiro e julho, festas em dezembro, alta local do
destino). `antecedência` aplica a curva de quem compra cedo ou em cima da hora.

Os valores partem de faixas de mercado observadas em 2025-2026 e são
deliberadamente conservadores: o benchmark existe para ser comparado, não para
prever. Ele envelhece — por isso o comando `recalibrate` reajusta a base a
partir das cotações que o próprio app coletou.

Para acrescentar um destino, basta mais uma entrada em DESTINATIONS.
"""
from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from . import airports
from .stats import median, robust_scale, weighted_median

#: Os benchmarks estão nesta moeda. Trocar de moeda exige converter a tabela.
BENCHMARK_CURRENCY = "BRL"

#: Origem para a qual a tabela foi escrita.
BASE_ORIGIN = "GRU"

MONTH_NAMES = (
    "jan", "fev", "mar", "abr", "mai", "jun",
    "jul", "ago", "set", "out", "nov", "dez",
)


@dataclass(frozen=True)
class Destination:
    """Um destino da cesta, com sua referência de preço."""

    iata: str
    city: str
    country: str
    region: str
    #: Ida e volta, econômica, 1 pax, saindo de GRU, na média anual, em BRL.
    base_price: float
    #: 12 fatores mensais (jan..dez). Normalizados para média 1,0 na carga.
    seasonal: Tuple[float, ...]
    #: Variação considerada normal, em % — define a largura da banda.
    band_pct: float
    #: Melhores meses para ir, do ponto de vista de preço (preenchido na carga).
    cheapest_months: Tuple[str, ...] = ()
    note: str = ""

    @property
    def label(self) -> str:
        return f"{self.city} ({self.iata})"

    def seasonal_factor(self, month: int) -> float:
        return self.seasonal[max(1, min(12, int(month))) - 1]

    def seasonal_table(self) -> List[Tuple[str, float]]:
        """Sazonalidade em % sobre a média anual, para exibição."""
        return [
            (MONTH_NAMES[i], 100.0 * (factor - 1.0))
            for i, factor in enumerate(self.seasonal)
        ]


def _normalize(factors: Sequence[float]) -> Tuple[float, ...]:
    """Reescala os fatores mensais para média exatamente 1,0.

    Deixa a tabela acima ser escrita em números intuitivos sem que a média
    anual saia do lugar.
    """
    mean = sum(factors) / len(factors)
    return tuple(round(f / mean, 4) for f in factors)


# ---------------------------------------------------------------------------
# A CESTA
#
# Dez destinos saindo de São Paulo, escolhidos para cobrir os corredores de
# maior demanda do Brasil e regiões suficientemente distintas para que uma
# distorção em um não contamine a leitura dos outros.
#                       jan   fev   mar   abr   mai   jun   jul   ago   set   out   nov   dez
# ---------------------------------------------------------------------------
_RAW_DESTINATIONS: Tuple[dict, ...] = (
    dict(
        iata="LIS", city="Lisboa", country="Portugal", region="Europa",
        base_price=4200.0, band_pct=12.0,
        seasonal=(1.18, 1.02, 0.92, 0.95, 0.90, 1.05, 1.28, 1.20, 0.95, 0.88, 0.85, 1.32),
        note="Porta de entrada da Europa; alta no verão europeu e nas férias brasileiras.",
    ),
    dict(
        iata="MAD", city="Madri", country="Espanha", region="Europa",
        base_price=4400.0, band_pct=12.0,
        seasonal=(1.16, 1.00, 0.92, 0.98, 0.90, 1.06, 1.30, 1.22, 0.94, 0.87, 0.84, 1.30),
        note="Concorre com Lisboa; costuma acompanhar o mesmo ciclo.",
    ),
    dict(
        iata="FCO", city="Roma", country="Itália", region="Europa",
        base_price=5200.0, band_pct=13.0,
        seasonal=(1.10, 0.95, 0.90, 1.00, 0.95, 1.15, 1.32, 1.28, 1.00, 0.88, 0.82, 1.25),
        note="Sazonalidade de verão mais marcada que a península ibérica.",
    ),
    dict(
        iata="CDG", city="Paris", country="França", region="Europa",
        base_price=5000.0, band_pct=12.0,
        seasonal=(1.10, 0.96, 0.90, 0.98, 0.95, 1.12, 1.30, 1.22, 0.96, 0.88, 0.84, 1.28),
        note="Hub de conexão; promoções aparecem fora do verão.",
    ),
    dict(
        iata="JFK", city="Nova York", country="EUA", region="América do Norte",
        base_price=4800.0, band_pct=13.0,
        seasonal=(1.12, 0.94, 0.95, 0.96, 0.95, 1.15, 1.25, 1.12, 0.92, 0.90, 0.92, 1.30),
        note="Muita oferta e concorrência: a banda de variação normal é larga.",
    ),
    dict(
        iata="MIA", city="Miami", country="EUA", region="América do Norte",
        base_price=4300.0, band_pct=13.0,
        seasonal=(1.15, 0.98, 1.00, 0.94, 0.90, 1.10, 1.22, 1.05, 0.85, 0.86, 0.92, 1.32),
        note="Rota de compras e conexão; setembro e outubro são o vale do ano.",
    ),
    dict(
        iata="EZE", city="Buenos Aires", country="Argentina", region="América do Sul",
        base_price=2100.0, band_pct=16.0,
        seasonal=(1.20, 1.02, 0.94, 0.92, 0.88, 0.95, 1.25, 0.98, 0.90, 0.92, 0.95, 1.28),
        note="Curta distância e tarifa baixa: oscila mais em termos percentuais.",
    ),
    dict(
        iata="SCL", city="Santiago", country="Chile", region="América do Sul",
        base_price=2600.0, band_pct=15.0,
        seasonal=(1.18, 1.05, 0.92, 0.88, 0.90, 1.00, 1.28, 1.15, 0.92, 0.90, 0.92, 1.25),
        note="Julho e agosto puxados pela temporada de esqui.",
    ),
    dict(
        iata="CUN", city="Cancún", country="México", region="Caribe",
        base_price=3900.0, band_pct=14.0,
        seasonal=(1.22, 1.08, 1.10, 1.05, 0.88, 0.95, 1.20, 0.98, 0.78, 0.80, 0.88, 1.30),
        note="Alta de dezembro a abril; setembro é temporada de furacões e despenca.",
    ),
    dict(
        iata="HND", city="Tóquio", country="Japão", region="Ásia",
        base_price=8500.0, band_pct=10.0,
        seasonal=(1.10, 0.92, 1.12, 1.15, 0.92, 0.90, 1.20, 1.15, 0.92, 1.02, 0.98, 1.22),
        note="Picos nas cerejeiras (mar-abr) e no outono; banda estreita, pouca oferta.",
    ),
)


def _build_destinations() -> Dict[str, Destination]:
    built: Dict[str, Destination] = {}
    for raw in _RAW_DESTINATIONS:
        seasonal = _normalize(raw["seasonal"])
        ranked = sorted(range(12), key=lambda i: seasonal[i])[:3]
        built[raw["iata"]] = Destination(
            iata=raw["iata"],
            city=raw["city"],
            country=raw["country"],
            region=raw["region"],
            base_price=raw["base_price"],
            seasonal=seasonal,
            band_pct=raw["band_pct"],
            cheapest_months=tuple(MONTH_NAMES[i] for i in sorted(ranked)),
            note=raw["note"],
        )
    return built


DESTINATIONS: Dict[str, Destination] = _build_destinations()
BASKET: Tuple[str, ...] = tuple(DESTINATIONS.keys())


# ------------------------------------------------------------- antecedência

#: Curva de antecedência de referência, compartilhada pelos destinos:
#: (dias até a partida, fator sobre o benchmark).
ADVANCE_CURVE: Tuple[Tuple[int, float], ...] = (
    (0, 1.68), (3, 1.52), (7, 1.36), (14, 1.22), (21, 1.13), (30, 1.06),
    (45, 1.01), (60, 0.98), (90, 0.97), (120, 0.99), (180, 1.03), (300, 1.08),
)


def advance_factor(days_to_departure: Optional[int]) -> float:
    """Quanto a antecedência da compra move o benchmark (interpolação linear)."""
    dtd = max(0, int(days_to_departure or 0))
    if dtd >= ADVANCE_CURVE[-1][0]:
        return ADVANCE_CURVE[-1][1]
    for (x0, y0), (x1, y1) in zip(ADVANCE_CURVE, ADVANCE_CURVE[1:]):
        if x0 <= dtd <= x1:
            span = x1 - x0
            return y0 if span == 0 else y0 + (dtd - x0) / span * (y1 - y0)
    return 1.0


ADVANCE_BANDS: Tuple[Tuple[int, int, str], ...] = (
    (0, 6, "até 6 dias"),
    (7, 20, "1 a 3 semanas"),
    (21, 44, "3 a 6 semanas"),
    (45, 89, "6 a 12 semanas"),
    (90, 179, "3 a 6 meses"),
    (180, 10_000, "mais de 6 meses"),
)


def advance_band(days_to_departure: Optional[int]) -> str:
    dtd = max(0, int(days_to_departure or 0))
    for low, high, label in ADVANCE_BANDS:
        if low <= dtd <= high:
            return label
    return ADVANCE_BANDS[-1][2]


# -------------------------------------------------------- cabine e origem

CABIN_FACTOR: Dict[str, float] = {
    "ECONOMY": 1.0,
    "PREMIUM_ECONOMY": 2.0,
    "BUSINESS": 3.5,
    "FIRST": 6.0,
}

#: Ajuste aproximado para sair de outra cidade brasileira. A tabela foi escrita
#: para GRU; estes fatores refletem a menor oferta direta dos demais aeroportos.
ORIGIN_FACTOR: Dict[str, float] = {
    "GRU": 1.00, "CGH": 1.00, "VCP": 0.97,
    "GIG": 1.03, "SDU": 1.05, "CNF": 1.07, "BSB": 1.05,
    "POA": 1.08, "CWB": 1.08, "FLN": 1.09,
    "SSA": 1.10, "REC": 1.11, "FOR": 1.11, "NAT": 1.13,
    "BEL": 1.14, "MAO": 1.14, "VIX": 1.10, "GYN": 1.08, "CGB": 1.12,
}
DEFAULT_ORIGIN_FACTOR = 1.12


def origin_factor(origin: str) -> float:
    return ORIGIN_FACTOR.get((origin or "").upper(), DEFAULT_ORIGIN_FACTOR)


# ------------------------------------------------------------- o benchmark


@dataclass
class BenchmarkBreakdown:
    """O benchmark aberto em suas partes — o app mostra a conta, não só o total."""

    destination: str
    price: float
    base: float
    seasonal: float
    advance: float
    cabin: float
    origin: float
    passengers: int
    month: int
    band_pct: float
    calibrated: bool = False

    def as_dict(self) -> dict:
        return {
            "destination": self.destination,
            "benchmark": round(self.price, 2),
            "base": round(self.base, 2),
            "seasonal_factor": round(self.seasonal, 4),
            "advance_factor": round(self.advance, 4),
            "cabin_factor": self.cabin,
            "origin_factor": self.origin,
            "passengers": self.passengers,
            "band_pct": self.band_pct,
            "calibrated": self.calibrated,
        }


def get(destination: str) -> Optional[Destination]:
    return DESTINATIONS.get((destination or "").upper())


def is_covered(destination: str) -> bool:
    return (destination or "").upper() in DESTINATIONS


def benchmark(
    destination: str,
    departure_date: date,
    days_to_departure: Optional[int] = None,
    *,
    origin: str = BASE_ORIGIN,
    cabin: str = "ECONOMY",
    passengers: int = 1,
    base_override: Optional[float] = None,
) -> BenchmarkBreakdown:
    """Preço de referência para um destino, data e antecedência."""
    dest = get(destination)
    if dest is None:
        raise KeyError(
            f"{destination} não está na cesta. Destinos: {', '.join(sorted(DESTINATIONS))}."
        )

    base = float(base_override) if base_override else dest.base_price
    seasonal = dest.seasonal_factor(departure_date.month)
    advance = advance_factor(days_to_departure)
    cabin_f = CABIN_FACTOR.get((cabin or "ECONOMY").upper(), 1.0)
    origin_f = origin_factor(origin)
    pax = max(1, int(passengers))

    return BenchmarkBreakdown(
        destination=dest.iata,
        price=base * seasonal * advance * cabin_f * origin_f * pax,
        base=base,
        seasonal=seasonal,
        advance=advance,
        cabin=cabin_f,
        origin=origin_f,
        passengers=pax,
        month=departure_date.month,
        band_pct=dest.band_pct,
        calibrated=base_override is not None,
    )


# ------------------------------------------------------------ recalibração

#: Volume mínimo de cotações para propor um novo preço-base.
MIN_QUOTES_TO_CALIBRATE = 25
#: Meses distintos de partida exigidos — sem espalhamento, a mediana só
#: descreveria a época que por acaso foi coletada.
MIN_MONTHS_TO_CALIBRATE = 3
#: Mudança máxima aceita de uma vez, para a base não saltar atrás de um
#: período atípico.
MAX_CALIBRATION_STEP = 0.20


@dataclass
class Calibration:
    """Proposta de novo preço-base para um destino."""

    destination: str
    current_base: float
    observed_base: float
    proposed_base: float
    change_pct: float
    n_quotes: int
    n_months: int
    dispersion_pct: float
    applied: bool = False
    blocked_reason: str = ""

    @property
    def is_actionable(self) -> bool:
        return not self.blocked_reason


def implied_base(price: float, breakdown: BenchmarkBreakdown) -> float:
    """Inverte a fórmula: que preço-base explicaria esta cotação?

    Tirar sazonalidade, antecedência, cabine e origem de cada cotação deixa
    todas na mesma régua — só então faz sentido tirar a mediana delas.
    """
    divisor = (
        breakdown.seasonal * breakdown.advance
        * breakdown.cabin * breakdown.origin * breakdown.passengers
    )
    return float(price) / divisor if divisor > 0 else float(price)


def propose_calibration(
    destination: str,
    implied_bases: Sequence[float],
    months: Iterable[int],
    current_base: Optional[float] = None,
) -> Calibration:
    """Compara a mediana das bases implícitas com a base vigente."""
    dest = get(destination)
    current = float(current_base) if current_base else (dest.base_price if dest else 0.0)
    values = [float(v) for v in implied_bases if v and v > 0]
    month_set = {int(m) for m in months}

    calibration = Calibration(
        destination=(destination or "").upper(),
        current_base=current,
        observed_base=median(values) if values else current,
        proposed_base=current,
        change_pct=0.0,
        n_quotes=len(values),
        n_months=len(month_set),
        dispersion_pct=(
            100.0 * robust_scale(values) / median(values) if len(values) > 2 else 0.0
        ),
    )

    if len(values) < MIN_QUOTES_TO_CALIBRATE:
        calibration.blocked_reason = (
            f"apenas {len(values)} cotações (mínimo {MIN_QUOTES_TO_CALIBRATE})"
        )
        return calibration
    if len(month_set) < MIN_MONTHS_TO_CALIBRATE:
        calibration.blocked_reason = (
            f"cotações concentradas em {len(month_set)} mês(es) "
            f"(mínimo {MIN_MONTHS_TO_CALIBRATE})"
        )
        return calibration

    # O passo é limitado: a base acompanha o mercado, não persegue o mês.
    ratio = calibration.observed_base / current if current > 0 else 1.0
    clamped = max(1 - MAX_CALIBRATION_STEP, min(1 + MAX_CALIBRATION_STEP, ratio))
    calibration.proposed_base = current * clamped
    calibration.change_pct = 100.0 * (clamped - 1.0)
    return calibration


def describe_table() -> List[dict]:
    """A tabela inteira, para exibição e auditoria."""
    return [
        {
            "iata": dest.iata,
            "city": dest.city,
            "country": dest.country,
            "region": dest.region,
            "base_price": dest.base_price,
            "band_pct": dest.band_pct,
            "cheapest_months": list(dest.cheapest_months),
            "distance_km": round(airports.distance_km(BASE_ORIGIN, dest.iata)),
            "seasonal": dict(zip(MONTH_NAMES, dest.seasonal)),
            "note": dest.note,
        }
        for dest in DESTINATIONS.values()
    ]
