"""Índice, cesta e distorção — a lógica de decisão do app.

Cada cotação vira um **índice** contra o benchmark do seu destino:

    índice = 100 × preço / benchmark

100 é o preço de referência. 78 significa 22% abaixo dele.

Os 10 destinos são cotados no mesmo instante, com a mesma metodologia, e a
mediana dos índices forma a **cesta** — um índice de mercado. Comparar um
destino com a cesta é o que separa duas situações que um número sozinho
confunde:

* **cesta em 82, destino em 80** — o mercado inteiro caiu (câmbio, combustível,
  capacidade). Bom momento para comprar qualquer coisa, mas este destino não
  tem nada de especial.
* **cesta em 101, destino em 78** — só este destino descolou. É uma distorção:
  promoção, guerra de tarifa ou erro. É o sinal que interessa.

Os dois sinais são medidos na mesma unidade — quantas **bandas** de variação
normal do destino o preço está abaixo — e o mais forte manda, com leve
vantagem para a distorção.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, Iterable, List, Optional, Sequence

from . import benchmarks
from .benchmarks import BenchmarkBreakdown, Destination
from .stats import clamp, median, robust_scale

INDEX_BASE = 100.0

#: Cotações válidas mínimas para a cesta ser lida como mercado. Abaixo disso o
#: app usa só o desvio contra o benchmark e diz que a cesta está incompleta.
MIN_BASKET_READINGS = 5

#: A distorção pesa um pouco mais que o desvio puro: é o sinal específico do
#: destino, enquanto o desvio contra o benchmark pode ser movimento de mercado.
DISTORTION_WEIGHT = 1.15

#: Limiares em "bandas de variação normal" do destino.
SIGNAL_WATCH = 1.0
SIGNAL_STRONG = 1.6
SIGNAL_EXTREME = 2.4

#: Abaixo deste índice a cotação é improvável demais para ser tratada como
#: oportunidade comum — costuma ser tarifa-erro ou dado quebrado.
SUSPICIOUS_INDEX = 45.0

#: Acima desta distância da banda, o destino é sinalizado como caro.
EXPENSIVE_BANDS = 1.5

#: O rótulo depende de qual sinal mandou. Chamar de "distorção" um preço que
#: apenas acompanha um mercado inteiro barato seria impreciso.
LEVEL_LABEL_DISTORTION = {
    -1: "acima do normal",
    0: "dentro do normal",
    1: "descolando da cesta",
    2: "distorção clara",
    3: "distorção forte",
    4: "suspeito (possível tarifa-erro)",
}

LEVEL_LABEL_BENCHMARK = {
    -1: "acima do normal",
    0: "dentro do normal",
    1: "abaixo do benchmark",
    2: "bem abaixo do benchmark",
    3: "muito abaixo do benchmark",
    4: "suspeito (possível tarifa-erro)",
}

LEVEL_LABEL = LEVEL_LABEL_BENCHMARK

DRIVER_LABEL = {
    "distortion": "descolou da cesta",
    "benchmark": "abaixo do próprio benchmark",
    "both": "abaixo do benchmark e descolado da cesta",
    "none": "sem sinal",
}


def price_index(price: float, benchmark_price: float) -> float:
    """Índice base 100 de uma cotação contra seu benchmark."""
    if not benchmark_price or benchmark_price <= 0:
        return INDEX_BASE
    return INDEX_BASE * float(price) / float(benchmark_price)


# ------------------------------------------------------------------ leitura


@dataclass
class Reading:
    """Uma medição: um destino, um preço, o índice que ele produz."""

    destination: str
    price: float
    benchmark: float
    index: float
    departure_date: date
    return_date: Optional[date] = None
    days_to_departure: int = 0
    currency: str = benchmarks.BENCHMARK_CURRENCY
    airline: Optional[str] = None
    stops: Optional[int] = None
    collected_at: Optional[datetime] = None
    breakdown: Optional[BenchmarkBreakdown] = None

    @property
    def dest(self) -> Optional[Destination]:
        return benchmarks.get(self.destination)

    @property
    def band_pct(self) -> float:
        dest = self.dest
        return dest.band_pct if dest else 12.0

    @property
    def gap_pct(self) -> float:
        """Distância até o benchmark, em %. Negativo = mais barato."""
        return self.index - INDEX_BASE

    def as_dict(self) -> dict:
        return {
            "destination": self.destination,
            "price": round(self.price, 2),
            "benchmark": round(self.benchmark, 2),
            "index": round(self.index, 1),
            "gap_pct": round(self.gap_pct, 1),
            "departure_date": self.departure_date.isoformat() if self.departure_date else None,
            "days_to_departure": self.days_to_departure,
            "currency": self.currency,
            "airline": self.airline,
            "stops": self.stops,
        }


def build_reading(
    destination: str,
    price: float,
    departure_date: date,
    days_to_departure: int,
    *,
    origin: str = benchmarks.BASE_ORIGIN,
    cabin: str = "ECONOMY",
    passengers: int = 1,
    base_override: Optional[float] = None,
    **extra,
) -> Reading:
    breakdown = benchmarks.benchmark(
        destination,
        departure_date,
        days_to_departure,
        origin=origin,
        cabin=cabin,
        passengers=passengers,
        base_override=base_override,
    )
    return Reading(
        destination=breakdown.destination,
        price=float(price),
        benchmark=breakdown.price,
        index=price_index(price, breakdown.price),
        departure_date=departure_date,
        days_to_departure=days_to_departure,
        breakdown=breakdown,
        **extra,
    )


# -------------------------------------------------------------------- cesta


@dataclass
class Basket:
    """A leitura de mercado de uma rodada de coleta."""

    collected_at: Optional[datetime] = None
    readings: List[Reading] = field(default_factory=list)
    index: float = INDEX_BASE
    dispersion: float = 0.0

    @property
    def size(self) -> int:
        return len(self.readings)

    @property
    def is_valid(self) -> bool:
        return self.size >= MIN_BASKET_READINGS

    def index_of(self, destination: str) -> Optional[float]:
        for reading in self.readings:
            if reading.destination == (destination or "").upper():
                return reading.index
        return None

    def distortion_of(self, destination: str) -> Optional[float]:
        """Quantos pontos de índice o destino está abaixo da cesta."""
        value = self.index_of(destination)
        if value is None or not self.is_valid:
            return None
        return value - self.index

    def ranked(self) -> List[Reading]:
        return sorted(self.readings, key=lambda r: r.index)

    def as_dict(self) -> dict:
        return {
            "collected_at": self.collected_at.isoformat() if self.collected_at else None,
            "index": round(self.index, 1),
            "dispersion": round(self.dispersion, 1),
            "size": self.size,
            "valid": self.is_valid,
            "readings": [r.as_dict() for r in self.readings],
        }


def build_basket(readings: Sequence[Reading], collected_at: Optional[datetime] = None) -> Basket:
    """Mediana dos índices — uma cotação quebrada não move o mercado."""
    valid = [r for r in readings if r.index > 0 and math.isfinite(r.index)]
    basket = Basket(
        collected_at=collected_at or datetime.now(),
        readings=list(valid),
    )
    if valid:
        indices = [r.index for r in valid]
        basket.index = median(indices)
        basket.dispersion = robust_scale(indices)
    return basket


# ----------------------------------------------------------------- veredito


@dataclass
class Verdict:
    """O julgamento de uma cotação: quanto, contra o quê e por quê."""

    destination: str
    price: float
    benchmark: float
    index: float
    band_pct: float
    currency: str = benchmarks.BENCHMARK_CURRENCY
    basket_index: Optional[float] = None
    distortion: Optional[float] = None
    signal_benchmark: float = 0.0
    signal_distortion: float = 0.0
    signal: float = 0.0
    driver: str = "none"
    level: int = 0
    score: float = 0.0
    passengers: int = 1
    reasons: List[str] = field(default_factory=list)

    @property
    def is_alert(self) -> bool:
        return self.level >= 1

    @property
    def label(self) -> str:
        table = (
            LEVEL_LABEL_DISTORTION
            if self.driver in ("distortion", "both")
            else LEVEL_LABEL_BENCHMARK
        )
        return table.get(self.level, "dentro do normal")

    @property
    def driver_label(self) -> str:
        return DRIVER_LABEL.get(self.driver, "sem sinal")

    @property
    def gap_pct(self) -> float:
        return self.index - INDEX_BASE

    @property
    def gap_label(self) -> str:
        gap = self.gap_pct
        if abs(gap) < 0.5:
            return "no benchmark"
        return f"{abs(gap):.0f}% {'acima' if gap > 0 else 'abaixo'} do benchmark"

    def as_dict(self) -> dict:
        return {
            "destination": self.destination,
            "price": round(self.price, 2),
            "benchmark": round(self.benchmark, 2),
            "index": round(self.index, 1),
            "gap_pct": round(self.gap_pct, 1),
            "gap_label": self.gap_label,
            "band_pct": self.band_pct,
            "basket_index": round(self.basket_index, 1) if self.basket_index else None,
            "distortion": round(self.distortion, 1) if self.distortion is not None else None,
            "signal": round(self.signal, 2),
            "signal_benchmark": round(self.signal_benchmark, 2),
            "signal_distortion": round(self.signal_distortion, 2),
            "driver": self.driver,
            "driver_label": self.driver_label,
            "level": self.level,
            "label": self.label,
            "score": round(self.score, 1),
            "currency": self.currency,
            "reasons": list(self.reasons),
        }


def _classify(index: float, signal: float, band_pct: float) -> int:
    if index <= SUSPICIOUS_INDEX:
        return 4
    if signal >= SIGNAL_EXTREME:
        return 3
    if signal >= SIGNAL_STRONG:
        return 2
    if signal >= SIGNAL_WATCH:
        return 1
    if index >= INDEX_BASE + EXPENSIVE_BANDS * band_pct:
        return -1
    return 0


def _driver(signal_benchmark: float, weighted_distortion: float) -> str:
    bench_on = signal_benchmark >= SIGNAL_WATCH
    dist_on = weighted_distortion >= SIGNAL_WATCH
    if bench_on and dist_on:
        return "both"
    if dist_on:
        return "distortion"
    if bench_on:
        return "benchmark"
    return "none"


def evaluate(
    reading: Reading,
    basket: Optional[Basket] = None,
    *,
    target_price: Optional[float] = None,
) -> Verdict:
    """Julga uma cotação contra seu benchmark e contra a cesta."""
    band = reading.band_pct
    verdict = Verdict(
        destination=reading.destination,
        price=reading.price,
        benchmark=reading.benchmark,
        index=reading.index,
        band_pct=band,
        currency=reading.currency,
        passengers=reading.breakdown.passengers if reading.breakdown else 1,
    )

    # Sinal 1: distância até o próprio benchmark, medida em bandas.
    verdict.signal_benchmark = (INDEX_BASE - reading.index) / band if band > 0 else 0.0

    # Sinal 2: distância até a cesta — só existe com mercado suficiente medido.
    weighted_distortion = 0.0
    if basket is not None and basket.is_valid:
        verdict.basket_index = basket.index
        verdict.distortion = reading.index - basket.index
        verdict.signal_distortion = (-verdict.distortion) / band if band > 0 else 0.0
        weighted_distortion = verdict.signal_distortion * DISTORTION_WEIGHT

    verdict.signal = max(verdict.signal_benchmark, weighted_distortion)
    verdict.driver = _driver(verdict.signal_benchmark, weighted_distortion)
    verdict.level = _classify(reading.index, verdict.signal, band)
    verdict.score = clamp(100.0 * verdict.signal / SIGNAL_EXTREME, 0.0, 100.0)

    if target_price is not None and reading.price <= target_price:
        verdict.level = max(verdict.level, 1)
        verdict.reasons.append(
            f"Atingiu o preço-alvo definido ({_money(target_price)})."
        )

    verdict.reasons.extend(
        _build_reasons(reading, verdict, basket.size if basket else 0)
    )
    return verdict


def _money(value: float) -> str:
    return f"R$ {value:,.0f}".replace(",", ".")


def _dec(value: float, digits: int = 1) -> str:
    """Decimal com vírgula, como se escreve em português."""
    return f"{value:.{digits}f}".replace(".", ",")


def _build_reasons(reading: Reading, verdict: Verdict, basket_size: int = 0) -> List[str]:
    reasons: List[str] = []
    dest = reading.dest
    month = benchmarks.MONTH_NAMES[reading.departure_date.month - 1]

    reasons.append(
        f"Índice {verdict.index:.0f} — {verdict.gap_label} de "
        f"{_money(verdict.benchmark)} para {month} comprando com "
        f"{reading.days_to_departure} dias de antecedência."
    )

    if verdict.distortion is not None:
        if verdict.distortion <= -3:
            reasons.append(
                f"A cesta de {basket_size} destinos está em "
                f"{verdict.basket_index:.0f}; este destino está "
                f"{abs(verdict.distortion):.0f} pontos abaixo do mercado."
            )
        elif verdict.distortion >= 3:
            reasons.append(
                f"A cesta está em {verdict.basket_index:.0f}; este destino está "
                f"{verdict.distortion:.0f} pontos acima do mercado."
            )
        else:
            reasons.append(
                f"Acompanha a cesta, que está em {verdict.basket_index:.0f} — "
                "o movimento é de mercado, não deste destino."
            )
    else:
        reasons.append(
            "Cesta ainda incompleta: a leitura usa apenas o desvio contra o benchmark."
        )

    if verdict.signal >= SIGNAL_WATCH:
        reasons.append(
            f"O desvio equivale a {_dec(verdict.signal)} banda(s) de variação "
            f"normal do destino (±{verdict.band_pct:.0f}%) — {verdict.driver_label}."
        )

    if dest and dest.cheapest_months:
        if month in dest.cheapest_months:
            reasons.append(f"{month.capitalize()} é um dos meses mais baratos do destino.")
        elif dest.seasonal_factor(reading.departure_date.month) >= 1.12:
            reasons.append(
                f"{month.capitalize()} é alta estação aqui "
                f"(+{100 * (dest.seasonal_factor(reading.departure_date.month) - 1):.0f}% "
                f"sobre a média anual); os meses baratos são "
                f"{', '.join(dest.cheapest_months)}."
            )

    if verdict.level == 4:
        reasons.append(
            "Queda grande demais para ser tarifa comum — pode ser tarifa-erro ou "
            "cotação quebrada. Confira antes de comprar: esse tipo de tarifa dura "
            "pouco e pode ser cancelada pela companhia."
        )

    return reasons


def evaluate_basket(basket: Basket) -> List[Verdict]:
    """Julga todos os destinos de uma rodada, do mais distorcido ao menos."""
    verdicts = [evaluate(reading, basket) for reading in basket.readings]
    return sorted(verdicts, key=lambda v: -v.signal)


def market_summary(basket: Basket) -> dict:
    """Leitura de uma linha sobre o momento de mercado."""
    if not basket.readings:
        return {"index": INDEX_BASE, "state": "sem dados", "detail": "Nenhuma cotação na rodada."}

    index = basket.index
    if index <= 88:
        state = "mercado barato"
        detail = "Os 10 destinos estão abaixo do benchmark — movimento amplo, não pontual."
    elif index <= 96:
        state = "levemente abaixo"
        detail = "A cesta está um pouco abaixo da referência."
    elif index < 105:
        state = "em linha"
        detail = "A cesta está próxima do benchmark; sem movimento de mercado relevante."
    elif index < 115:
        state = "levemente acima"
        detail = "A cesta está acima da referência."
    else:
        state = "mercado caro"
        detail = "Os 10 destinos estão acima do benchmark — momento ruim para comprar."

    cheapest = basket.ranked()[0]
    return {
        "index": round(index, 1),
        "state": state,
        "detail": detail,
        "dispersion": round(basket.dispersion, 1),
        "size": basket.size,
        "cheapest": cheapest.destination,
        "cheapest_index": round(cheapest.index, 1),
    }
