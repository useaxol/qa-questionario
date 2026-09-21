"""Gráficos em SVG gerados no servidor — sem JavaScript e sem CDN.

As cores não são escritas aqui: cada elemento recebe uma classe CSS e o tema
(claro/escuro) é resolvido por `static/style.css`. Assim o mesmo SVG serve aos
dois modos e a paleta fica em um lugar só.
"""
from __future__ import annotations

import html
import math
from datetime import date, datetime
from typing import Iterable, List, Optional, Sequence, Tuple

Point = Tuple[datetime, float]

MONTH_ABBR = ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")


# ------------------------------------------------------------------ utilitários


def _esc(text: object) -> str:
    return html.escape(str(text), quote=True)


def _fmt_number(value: float) -> str:
    """Milhar com separador fino, no padrão brasileiro."""
    return f"{value:,.0f}".replace(",", ".")


def _fmt_compact(value: float) -> str:
    if abs(value) >= 1000:
        return f"{value / 1000:.1f}".rstrip("0").rstrip(".") + "k"
    return f"{value:.0f}"


def nice_ticks(low: float, high: float, count: int = 4) -> List[float]:
    """Marcações de eixo em números redondos."""
    if not math.isfinite(low) or not math.isfinite(high):
        return [0.0]
    if high <= low:
        high = low + 1.0
    raw_step = (high - low) / max(1, count)
    magnitude = 10 ** math.floor(math.log10(raw_step)) if raw_step > 0 else 1
    for multiple in (1, 2, 2.5, 5, 10):
        step = magnitude * multiple
        if step >= raw_step:
            break
    start = math.floor(low / step) * step
    ticks = []
    value = start
    while value <= high + step * 0.5:
        if value >= low - step * 0.5:
            ticks.append(round(value, 6))
        value += step
    return ticks or [low, high]


def _scale(value: float, lo: float, hi: float, out_lo: float, out_hi: float) -> float:
    if hi == lo:
        return (out_lo + out_hi) / 2.0
    return out_lo + (value - lo) * (out_hi - out_lo) / (hi - lo)


def _rounded_bar(x: float, width: float, y_base: float, y_value: float, radius: float = 4.0) -> str:
    """Barra com a ponta de dados arredondada e a base quadrada."""
    height = abs(y_value - y_base)
    r = min(radius, width / 2.0, height)
    if height < 0.6:
        return f"M {x:.1f} {y_base:.1f} h {width:.1f} v 0.6 h {-width:.1f} Z"
    if y_value < y_base:  # barra para cima
        return (
            f"M {x:.1f} {y_base:.1f} V {y_value + r:.1f} A {r:.1f} {r:.1f} 0 0 1 {x + r:.1f} {y_value:.1f} "
            f"H {x + width - r:.1f} A {r:.1f} {r:.1f} 0 0 1 {x + width:.1f} {y_value + r:.1f} "
            f"V {y_base:.1f} Z"
        )
    return (  # barra para baixo
        f"M {x:.1f} {y_base:.1f} V {y_value - r:.1f} A {r:.1f} {r:.1f} 0 0 0 {x + r:.1f} {y_value:.1f} "
        f"H {x + width - r:.1f} A {r:.1f} {r:.1f} 0 0 0 {x + width:.1f} {y_value - r:.1f} "
        f"V {y_base:.1f} Z"
    )


def empty_chart(message: str, width: int = 880, height: int = 260) -> str:
    return (
        f'<svg class="fw-chart" viewBox="0 0 {width} {height}" width="100%" height="{height}" '
        f'role="img" aria-label="{_esc(message)}">'
        f'<text class="fw-empty" x="{width / 2:.0f}" y="{height / 2:.0f}" text-anchor="middle">'
        f"{_esc(message)}</text></svg>"
    )


# ------------------------------------------------------ índice no tempo


def index_history_chart(
    points: Sequence[Tuple[datetime, float]],
    comparison: Optional[Sequence[Tuple[datetime, float]]] = None,
    *,
    band_pct: float = 0.0,
    width: int = 880,
    height: int = 300,
    label: str = "índice",
    comparison_label: str = "cesta",
    alerts: Optional[Sequence[Tuple[datetime, float, int]]] = None,
) -> str:
    """Índice ao longo do tempo, contra a linha de referência 100.

    Com `comparison` desenha uma segunda série (tipicamente a cesta), que é o
    que revela se um destino está descolando ou apenas acompanhando o mercado.
    """
    points = [(t, float(v)) for t, v in points if v and math.isfinite(v)]
    if len(points) < 2:
        return empty_chart("Ainda sem rodadas suficientes para a série do índice.", width, height)

    comparison = [(t, float(v)) for t, v in (comparison or []) if v and math.isfinite(v)]
    alerts = list(alerts or [])

    pad_left, pad_right, pad_top, pad_bottom = 56, 78, 18, 34
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom

    xs = [t.timestamp() for t, _ in points] + [t.timestamp() for t, _ in comparison]
    x_lo, x_hi = min(xs), max(xs)

    values = [v for _, v in points] + [v for _, v in comparison] + [100.0]
    if band_pct > 0:
        values += [100.0 - band_pct, 100.0 + band_pct]
    y_lo, y_hi = min(values), max(values)
    span = max(6.0, y_hi - y_lo)
    y_lo -= span * 0.12
    y_hi += span * 0.12

    def px(moment: datetime) -> float:
        return _scale(moment.timestamp(), x_lo, x_hi, pad_left, pad_left + plot_w)

    def py(value: float) -> float:
        return _scale(value, y_lo, y_hi, pad_top + plot_h, pad_top)

    parts: List[str] = [
        f'<svg class="fw-chart" viewBox="0 0 {width} {height}" width="100%" height="{height}" '
        f'role="img" aria-label="Índice ao longo do tempo contra a referência 100">'
    ]

    for tick in nice_ticks(y_lo, y_hi, 5):
        y = py(tick)
        if not (pad_top - 1 <= y <= pad_top + plot_h + 1):
            continue
        parts.append(
            f'<line class="fw-grid" x1="{pad_left}" y1="{y:.1f}" x2="{pad_left + plot_w}" y2="{y:.1f}"/>'
        )
        parts.append(
            f'<text class="fw-tick" x="{pad_left - 10}" y="{y + 4:.1f}" text-anchor="end">'
            f"{tick:.0f}</text>"
        )

    # Faixa de variação normal em torno de 100.
    if band_pct > 0:
        top, bottom = py(100.0 + band_pct), py(100.0 - band_pct)
        parts.append(
            f'<rect class="fw-band" x="{pad_left}" y="{top:.1f}" '
            f'width="{plot_w}" height="{max(1.0, bottom - top):.1f}"/>'
        )

    # A linha do 100: a referência, não um dado.
    y100 = py(100.0)
    parts.append(
        f'<line class="fw-reference" x1="{pad_left}" y1="{y100:.1f}" '
        f'x2="{pad_left + plot_w}" y2="{y100:.1f}"/>'
    )
    parts.append(
        f'<text class="fw-end-label fw-muted-label" x="{pad_left + plot_w + 8:.1f}" '
        f'y="{y100 + 4:.1f}">100</text>'
    )

    if comparison:
        path = " ".join(
            ("M" if i == 0 else "L") + f" {px(t):.1f} {py(v):.1f}"
            for i, (t, v) in enumerate(comparison)
        )
        parts.append(f'<path class="fw-line-compare" d="{path}"/>')

    path = " ".join(
        ("M" if i == 0 else "L") + f" {px(t):.1f} {py(v):.1f}" for i, (t, v) in enumerate(points)
    )
    parts.append(f'<path class="fw-line-index" d="{path}"/>')

    severity_class = {1: "good", 2: "good", 3: "serious", 4: "critical"}
    for moment, value, level in alerts:
        parts.append(
            f'<circle class="fw-alert-dot fw-alert-{severity_class.get(level, "good")}" '
            f'cx="{px(moment):.1f}" cy="{py(value):.1f}" r="5"><title>Alerta em '
            f"{_esc(moment.strftime('%d/%m/%Y %H:%M'))} · índice {value:.0f}</title></circle>"
        )

    for moment, value in points:
        parts.append(
            f'<circle class="fw-hit" cx="{px(moment):.1f}" cy="{py(value):.1f}" r="9">'
            f"<title>{_esc(moment.strftime('%d/%m/%Y %H:%M'))} · {_esc(label)} "
            f"{value:.0f}</title></circle>"
        )

    last_t, last_v = points[-1]
    parts.append(f'<circle class="fw-end-dot" cx="{px(last_t):.1f}" cy="{py(last_v):.1f}" r="4.5"/>')
    parts.append(
        f'<text class="fw-end-label" x="{px(last_t) + 10:.1f}" y="{py(last_v) + 4:.1f}">'
        f"{last_v:.0f}</text>"
    )
    if comparison:
        ct, cv = comparison[-1]
        parts.append(
            f'<circle class="fw-end-dot-compare" cx="{px(ct):.1f}" cy="{py(cv):.1f}" r="4"/>'
        )
        parts.append(
            f'<text class="fw-end-label fw-muted-label" x="{px(ct) + 10:.1f}" '
            f'y="{py(cv) + 4:.1f}">{_esc(comparison_label)}</text>'
        )

    baseline_y = pad_top + plot_h
    parts.append(
        f'<line class="fw-axis" x1="{pad_left}" y1="{baseline_y:.1f}" '
        f'x2="{pad_left + plot_w}" y2="{baseline_y:.1f}"/>'
    )
    for index, anchor in ((0, "start"), (len(points) // 2, "middle"), (len(points) - 1, "end")):
        moment = points[index][0]
        parts.append(
            f'<text class="fw-tick" x="{px(moment):.1f}" y="{baseline_y + 20:.0f}" '
            f'text-anchor="{anchor}">{_esc(moment.strftime("%d/%m %H:%M"))}</text>'
        )

    parts.append("</svg>")
    return "".join(parts)


# ------------------------------------------------- a cesta agora (barras)


def basket_bars(
    items: Sequence[Tuple[str, float, str]],
    basket_index: Optional[float] = None,
    width: int = 880,
    row_height: int = 34,
) -> str:
    """Barras horizontais: o índice de cada destino em torno da referência 100.

    É o gráfico principal do app. Cada barra cresce a partir do 100, então o
    olho lê imediatamente quem está abaixo e quanto.
    """
    items = list(items)
    if not items:
        return empty_chart("Nenhuma cotação na última rodada.", width, 200)

    pad_left, pad_right, pad_top, pad_bottom = 118, 58, 26, 30
    plot_w = width - pad_left - pad_right
    height = pad_top + pad_bottom + row_height * len(items)

    magnitude = max(
        14.0,
        max(abs(value - 100.0) for _, value, _ in items) * 1.18,
        abs((basket_index or 100.0) - 100.0) * 1.3,
    )
    x_zero = pad_left + plot_w / 2.0

    def px(value: float) -> float:
        return x_zero + ((value - 100.0) / magnitude) * (plot_w / 2.0)

    bar_h = min(24.0, row_height * 0.58)

    parts: List[str] = [
        f'<svg class="fw-chart" viewBox="0 0 {width} {height}" width="100%" height="{height}" '
        f'role="img" aria-label="Índice de cada destino da cesta em torno de 100">'
    ]

    for tick in (100 - magnitude, 100 - magnitude / 2, 100, 100 + magnitude / 2, 100 + magnitude):
        x = px(tick)
        css = "fw-reference" if abs(tick - 100) < 1e-9 else "fw-grid"
        parts.append(
            f'<line class="{css}" x1="{x:.1f}" y1="{pad_top - 8}" '
            f'x2="{x:.1f}" y2="{pad_top + row_height * len(items):.1f}"/>'
        )
        parts.append(
            f'<text class="fw-tick" x="{x:.1f}" y="{pad_top - 14}" text-anchor="middle">'
            f"{tick:.0f}</text>"
        )

    # A cesta entra como uma marca vertical: cada destino é lido contra ela.
    if basket_index is not None:
        x = px(basket_index)
        parts.append(
            f'<line class="fw-basket-mark" x1="{x:.1f}" y1="{pad_top - 6}" '
            f'x2="{x:.1f}" y2="{pad_top + row_height * len(items) + 4:.1f}"/>'
        )
        parts.append(
            f'<text class="fw-tick fw-basket-label" x="{x:.1f}" '
            f'y="{pad_top + row_height * len(items) + 20:.0f}" text-anchor="middle">'
            f"cesta {basket_index:.0f}</text>"
        )

    for row, (label, value, note) in enumerate(items):
        y_center = pad_top + row * row_height + row_height / 2.0
        y = y_center - bar_h / 2.0
        x_value = px(value)
        css = "fw-bar-low" if value <= 100 else "fw-bar-high"
        left, right = (x_value, x_zero) if value <= 100 else (x_zero, x_value)
        parts.append(
            f'<path class="{css}" d="{_rounded_bar_h(left, right, y, bar_h, value <= 100)}">'
            f"<title>{_esc(label)}: índice {value:.0f} — {_esc(note)}</title></path>"
        )
        parts.append(
            f'<text class="fw-row-label" x="{pad_left - 14}" y="{y_center + 4:.1f}" '
            f'text-anchor="end">{_esc(label)}</text>'
        )
        anchor_x = x_value + (-9 if value <= 100 else 9)
        anchor = "end" if value <= 100 else "start"
        parts.append(
            f'<text class="fw-row-value" x="{anchor_x:.1f}" y="{y_center + 4:.1f}" '
            f'text-anchor="{anchor}">{value:.0f}</text>'
        )

    parts.append("</svg>")
    return "".join(parts)


def _rounded_bar_h(left: float, right: float, y: float, height: float, round_left: bool) -> str:
    """Barra horizontal com a ponta de dados arredondada e a base quadrada."""
    span = max(0.0, right - left)
    r = min(4.0, height / 2.0, span)
    if span < 0.8:
        return f"M {left:.1f} {y:.1f} h 0.8 v {height:.1f} h -0.8 Z"
    if round_left:
        return (
            f"M {right:.1f} {y:.1f} H {left + r:.1f} A {r:.1f} {r:.1f} 0 0 0 {left:.1f} {y + r:.1f} "
            f"V {y + height - r:.1f} A {r:.1f} {r:.1f} 0 0 0 {left + r:.1f} {y + height:.1f} "
            f"H {right:.1f} Z"
        )
    return (
        f"M {left:.1f} {y:.1f} H {right - r:.1f} A {r:.1f} {r:.1f} 0 0 1 {right:.1f} {y + r:.1f} "
        f"V {y + height - r:.1f} A {r:.1f} {r:.1f} 0 0 1 {right - r:.1f} {y + height:.1f} "
        f"H {left:.1f} Z"
    )


# ---------------------------------------------------- sazonalidade (divergente)


def diverging_bars(
    items: Sequence[Tuple[str, float]],
    width: int = 880,
    height: int = 220,
    label_every: int = 1,
    unit: str = "%",
    caption_high: str = "mais caro",
    caption_low: str = "mais barato",
) -> str:
    """Barras divergentes: acima de zero = mais caro, abaixo = mais barato."""
    items = list(items)
    if not items:
        return empty_chart("Sem dados suficientes.", width, height)

    pad_left, pad_right, pad_top, pad_bottom = 52, 20, 24, 30
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom

    magnitude = max((abs(v) for _, v in items), default=1.0)
    magnitude = max(magnitude * 1.15, 2.0)
    y_zero = pad_top + plot_h / 2.0

    slot = plot_w / len(items)
    bar_w = min(24.0, slot * 0.62)

    parts: List[str] = [
        f'<svg class="fw-chart" viewBox="0 0 {width} {height}" width="100%" height="{height}" '
        f'role="img" aria-label="Variação percentual por faixa">'
    ]

    for tick in (-magnitude, -magnitude / 2, 0.0, magnitude / 2, magnitude):
        y = y_zero - (tick / magnitude) * (plot_h / 2.0)
        css = "fw-axis" if abs(tick) < 1e-9 else "fw-grid"
        parts.append(f'<line class="{css}" x1="{pad_left}" y1="{y:.1f}" x2="{pad_left + plot_w}" y2="{y:.1f}"/>')
        parts.append(
            f'<text class="fw-tick" x="{pad_left - 10}" y="{y + 4:.1f}" text-anchor="end">'
            f"{tick:+.0f}{_esc(unit)}</text>"
        )

    for index, (label, value) in enumerate(items):
        # 2px de respiro entre barras vizinhas é dado pelo próprio slot.
        x = pad_left + slot * index + (slot - bar_w) / 2.0
        y_value = y_zero - (value / magnitude) * (plot_h / 2.0)
        css = "fw-bar-high" if value >= 0 else "fw-bar-low"
        direction = caption_high if value >= 0 else caption_low
        parts.append(
            f'<path class="{css}" d="{_rounded_bar(x, bar_w, y_zero, y_value)}">'
            f"<title>{_esc(label)}: {value:+.1f}{_esc(unit)} ({_esc(direction)})</title></path>"
        )
        if index % max(1, label_every) == 0:
            parts.append(
                f'<text class="fw-tick" x="{x + bar_w / 2:.1f}" y="{pad_top + plot_h + 20:.0f}" '
                f'text-anchor="middle">{_esc(label)}</text>'
            )

    parts.append("</svg>")
    return "".join(parts)


def seasonal_chart(monthly: Sequence[Tuple[int, float]], width: int = 880, height: int = 220) -> str:
    return diverging_bars(
        [(MONTH_ABBR[month - 1], pct) for month, pct in monthly], width=width, height=height
    )


def advance_chart(curve: Sequence[Tuple[str, float]], width: int = 880, height: int = 220) -> str:
    return diverging_bars(
        [(f"{label}d", pct) for label, pct in curve],
        width=width,
        height=height,
        caption_high="acima da média",
        caption_low="abaixo da média",
    )


# --------------------------------------------------------------- sparkline


def sparkline(values: Sequence[float], width: int = 150, height: int = 38) -> str:
    """Miniatura da série de preços, para as linhas da lista."""
    series = [float(v) for v in values if v and v > 0]
    if len(series) < 2:
        return f'<svg class="fw-spark" viewBox="0 0 {width} {height}" width="{width}" height="{height}"></svg>'

    lo, hi = min(series), max(series)
    pad = 5
    step = (width - 2 * pad) / (len(series) - 1)

    def py(value: float) -> float:
        return _scale(value, lo, hi, height - pad, pad) if hi > lo else height / 2.0

    path = " ".join(
        ("M" if i == 0 else "L") + f" {pad + i * step:.1f} {py(v):.1f}" for i, v in enumerate(series)
    )
    last_x, last_y = pad + (len(series) - 1) * step, py(series[-1])
    return (
        f'<svg class="fw-spark" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'role="img" aria-label="Evolução recente do preço">'
        f'<path class="fw-spark-line" d="{path}"/>'
        f'<circle class="fw-end-dot" cx="{last_x:.1f}" cy="{last_y:.1f}" r="3.5"/>'
        f"</svg>"
    )
