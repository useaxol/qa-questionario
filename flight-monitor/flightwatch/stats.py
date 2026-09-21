"""Estatística robusta usada pelo índice e pela recalibração.

Mediana e MAD, não média e desvio-padrão: uma tarifa-erro ou uma cotação
quebrada não pode mover a referência de mercado.
"""
from __future__ import annotations

from typing import Optional, Sequence, Tuple


def median(values: Sequence[float]) -> float:
    ordered = sorted(float(v) for v in values)
    if not ordered:
        raise ValueError("mediana de sequência vazia")
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def weighted_median(pairs: Sequence[Tuple[float, float]]) -> float:
    items = sorted(((float(v), float(w)) for v, w in pairs if w > 0), key=lambda p: p[0])
    if not items:
        raise ValueError("mediana ponderada de sequência vazia")
    total = sum(w for _, w in items)
    acc = 0.0
    for index, (value, weight) in enumerate(items):
        acc += weight
        if acc >= total / 2.0:
            if abs(acc - total / 2.0) < 1e-12 and index + 1 < len(items):
                return (value + items[index + 1][0]) / 2.0
            return value
    return items[-1][0]


def mad(values: Sequence[float], center: Optional[float] = None) -> float:
    """Desvio absoluto mediano."""
    if not values:
        return 0.0
    middle = median(values) if center is None else center
    return median([abs(float(v) - middle) for v in values])


def robust_scale(values: Sequence[float], center: Optional[float] = None) -> float:
    """MAD reescalado para ser comparável a um desvio-padrão."""
    return 1.4826 * mad(values, center)


def percentile_below(values: Sequence[float], target: float) -> float:
    """% de observações maiores que `target` — "mais barato que X% delas"."""
    if not values:
        return 0.0
    return 100.0 * sum(1 for v in values if float(v) > target) / len(values)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
