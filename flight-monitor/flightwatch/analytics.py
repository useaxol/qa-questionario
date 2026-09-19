"""Modelo estatístico de preço "normal" de uma passagem.

A ideia central: o preço de uma passagem não é comparável no vácuo. Ele depende de

  1. a rota (GRU-LIS custa mais que GRU-SDU);
  2. o período do ano da *viagem* (julho e final de dezembro são caros);
  3. a antecedência da compra (a curva sobe forte nas últimas semanas);

Então modelamos, em escala logarítmica e com estatística robusta (mediana/MAD,
resistentes a outliers e a tarifas-erro):

    log(preço) = base_da_rota + índice_sazonal[semana] + fator_antecedência[faixa] + resíduo

O ajuste é feito por *backfitting*: estima-se um efeito de cada vez, sempre
sobre o resíduo dos demais, repetindo algumas vezes até estabilizar. Cada efeito
sofre encolhimento (shrinkage) proporcional ao volume de dados que o sustenta —
com pouca história, o efeito tende a zero em vez de inventar sazonalidade.

O resíduo padronizado (z-score robusto) é o sinal de oportunidade: quanto mais
negativo, mais barata a passagem está *em relação ao próprio padrão dela*.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .models import Observation

# ------------------------------------------------------------------ parâmetros

WEEKS_IN_YEAR = 52

#: Faixas de antecedência (dias até a partida). A curva de preço muda de regime
#: em cada uma delas.
ADVANCE_BUCKETS: Tuple[Tuple[int, int, str], ...] = (
    (0, 3, "0-3"),
    (4, 7, "4-7"),
    (8, 14, "8-14"),
    (15, 21, "15-21"),
    (22, 30, "22-30"),
    (31, 45, "31-45"),
    (46, 60, "46-60"),
    (61, 90, "61-90"),
    (91, 120, "91-120"),
    (121, 180, "121-180"),
    (181, 10_000, "181+"),
)
_BUCKET_ORDER = [label for _, _, label in ADVANCE_BUCKETS]
_BUCKET_INDEX = {label: i for i, label in enumerate(_BUCKET_ORDER)}

#: Encolhimento dos efeitos: um efeito estimado com n amostras é multiplicado
#: por n / (n + K). Quanto maior o K, mais conservador.
SEASONAL_SHRINK_K = 6.0
ADVANCE_SHRINK_K = 8.0

#: Largura (em semanas) do kernel que empresta informação de semanas vizinhas.
SEASONAL_KERNEL_SIGMA = 1.6
SEASONAL_KERNEL_RADIUS = 3

#: Limites do desvio robusto dos resíduos, para não gerar z-scores absurdos
#: quando a história é homogênea demais ou ruidosa demais.
MIN_RESIDUAL_SCALE = 0.035
MAX_RESIDUAL_SCALE = 0.60
DEFAULT_RESIDUAL_SCALE = 0.16

#: Volume mínimo de história para confiar no modelo completo.
MIN_SAMPLES_MODEL = 8
MIN_SAMPLES_LOW = 8
MIN_SAMPLES_MEDIUM = 25
MIN_SAMPLES_HIGH = 80

#: Limiares de z-score por nível de oportunidade (multiplicados pelo fator de
#: confiança: com pouca história exigimos um sinal mais forte).
Z_GOOD = -0.90
Z_GREAT = -1.60
Z_EXCEPTIONAL = -2.40
Z_SUSPICIOUS = -4.00
Z_ABOVE = 0.75

CONFIDENCE_FACTOR = {"none": 2.0, "low": 1.5, "medium": 1.18, "high": 1.0}

#: Desconto mínimo (%) para cada nível, para evitar alerta em rota barata onde
#: 2% de queda já vira z-score alto.
MIN_DISCOUNT = {1: 4.0, 2: 8.0, 3: 15.0}

CONFIDENCE_LABEL = {
    "none": "sem histórico",
    "low": "baixa",
    "medium": "média",
    "high": "alta",
}


def fmt_num(value: float) -> str:
    """Milhar no padrão brasileiro (1.234), para os textos de justificativa."""
    return f"{value:,.0f}".replace(",", ".")


SEVERITY_LABEL = {
    -1: "acima do normal",
    0: "dentro do normal",
    1: "boa oportunidade",
    2: "ótima oportunidade",
    3: "oportunidade excepcional",
    4: "suspeito (possível tarifa-erro)",
}

VERDICT_BY_SEVERITY = {
    -1: "above_normal",
    0: "normal",
    1: "good_deal",
    2: "great_deal",
    3: "exceptional_deal",
    4: "suspicious_low",
}


# ------------------------------------------------------------ estatística base


def weighted_median(pairs: Sequence[Tuple[float, float]]) -> float:
    """Mediana ponderada de uma lista de (valor, peso)."""
    items = [(v, w) for v, w in pairs if w > 0]
    if not items:
        raise ValueError("weighted_median de sequência vazia")
    items.sort(key=lambda p: p[0])
    total = sum(w for _, w in items)
    half = total / 2.0
    acc = 0.0
    for i, (value, weight) in enumerate(items):
        acc += weight
        if acc >= half:
            # Interpolação no caso exatamente central (peso par).
            if abs(acc - half) < 1e-12 and i + 1 < len(items):
                return (value + items[i + 1][0]) / 2.0
            return value
    return items[-1][0]


def median(values: Sequence[float]) -> float:
    return weighted_median([(v, 1.0) for v in values])


def mad(values: Sequence[float], center: Optional[float] = None) -> float:
    """Desvio absoluto mediano."""
    if not values:
        return 0.0
    c = median(values) if center is None else center
    return median([abs(v - c) for v in values])


def robust_scale(values: Sequence[float], center: Optional[float] = None) -> float:
    """MAD reescalado para ser comparável a um desvio-padrão."""
    return 1.4826 * mad(values, center)


def percentile_of(values: Sequence[float], target: float) -> float:
    """% de observações estritamente maiores que `target` (0-100)."""
    if not values:
        return 0.0
    greater = sum(1 for v in values if v > target)
    return 100.0 * greater / len(values)


def weighted_percentile_of(pairs: Sequence[Tuple[float, float]], target: float) -> float:
    total = sum(w for _, w in pairs if w > 0)
    if total <= 0:
        return 0.0
    greater = sum(w for v, w in pairs if w > 0 and v > target)
    return 100.0 * greater / total


# ------------------------------------------------------------------ calendário


def week_of_year(day: date) -> int:
    """Semana ISO normalizada em 1..52 (a semana 53 é dobrada na 52)."""
    week = day.isocalendar()[1]
    return 52 if week >= 53 else int(week)


def week_distance(a: int, b: int) -> int:
    """Distância circular entre semanas do ano."""
    diff = abs(a - b) % WEEKS_IN_YEAR
    return min(diff, WEEKS_IN_YEAR - diff)


def advance_bucket(days_to_departure: Optional[int]) -> str:
    dtd = 0 if days_to_departure is None else max(0, int(days_to_departure))
    for low, high, label in ADVANCE_BUCKETS:
        if low <= dtd <= high:
            return label
    return _BUCKET_ORDER[-1]


# -------------------------------------------------------------------- amostras


@dataclass
class Sample:
    """Uma cotação histórica pronta para o ajuste."""

    price: float
    log_price: float
    week: int
    bucket: str
    weight: float = 1.0
    departure_date: Optional[date] = None
    observed_at: Optional[datetime] = None
    observation_id: Optional[int] = None


def sample_from_observation(obs: Observation) -> Optional[Sample]:
    price = obs.price_per_pax or obs.price
    if not price or price <= 0 or obs.departure_date is None:
        return None
    return Sample(
        price=float(price),
        log_price=math.log(float(price)),
        week=week_of_year(obs.departure_date),
        bucket=advance_bucket(obs.days_to_departure),
        weight=float(obs.weight or 1.0),
        departure_date=obs.departure_date,
        observed_at=obs.observed_at,
        observation_id=obs.id,
    )


def samples_from_observations(observations: Iterable[Observation]) -> List[Sample]:
    out = []
    for obs in observations:
        sample = sample_from_observation(obs)
        if sample is not None:
            out.append(sample)
    return out


# ---------------------------------------------------------------- modelo rota


@dataclass
class RouteModel:
    """Preço de referência de uma rota, decomposto em base + sazonal + antecedência."""

    n: int = 0
    total_weight: float = 0.0
    log_base: float = 0.0
    seasonal: Dict[int, float] = field(default_factory=dict)
    advance: Dict[str, float] = field(default_factory=dict)
    residual_scale: float = DEFAULT_RESIDUAL_SCALE
    residuals: List[float] = field(default_factory=list)
    weeks_covered: int = 0
    fitted: bool = False

    # -- consulta

    @property
    def base_price(self) -> float:
        return math.exp(self.log_base)

    def seasonal_offset(self, week: int) -> float:
        return self.seasonal.get(int(week), 0.0)

    def advance_offset(self, bucket: str) -> float:
        return self.advance.get(bucket, 0.0)

    def predict_log(self, departure_date: date, days_to_departure: Optional[int]) -> float:
        return (
            self.log_base
            + self.seasonal_offset(week_of_year(departure_date))
            + self.advance_offset(advance_bucket(days_to_departure))
        )

    def predict(self, departure_date: date, days_to_departure: Optional[int]) -> float:
        """Preço esperado (por passageiro) para uma data de viagem e antecedência."""
        return math.exp(self.predict_log(departure_date, days_to_departure))

    def residual_of(self, sample: "Sample") -> float:
        """Resíduo em log de uma amostra já ajustada (base + sazonal + antecedência)."""
        return (
            sample.log_price
            - self.log_base
            - self.seasonal_offset(sample.week)
            - self.advance_offset(sample.bucket)
        )

    def seasonal_curve(self) -> List[Tuple[int, float]]:
        """Índice sazonal por semana, em % sobre a média da rota."""
        return [
            (week, 100.0 * (math.exp(self.seasonal_offset(week)) - 1.0))
            for week in range(1, WEEKS_IN_YEAR + 1)
        ]

    def monthly_curve(self, year: int) -> List[Tuple[int, float]]:
        """Índice sazonal agregado por mês, em % sobre a média da rota."""
        buckets: Dict[int, List[float]] = {m: [] for m in range(1, 13)}
        for week in range(1, WEEKS_IN_YEAR + 1):
            try:
                day = date.fromisocalendar(year, week, 4)
            except ValueError:
                continue
            buckets[day.month].append(self.seasonal_offset(week))
        out = []
        for month in range(1, 13):
            offsets = buckets[month]
            avg = sum(offsets) / len(offsets) if offsets else 0.0
            out.append((month, 100.0 * (math.exp(avg) - 1.0)))
        return out

    def advance_curve(self) -> List[Tuple[str, float]]:
        return [
            (label, 100.0 * (math.exp(self.advance_offset(label)) - 1.0))
            for label in _BUCKET_ORDER
        ]

    def confidence(self, week: Optional[int] = None) -> str:
        """Quanta história sustenta uma previsão (opcionalmente naquele período)."""
        if self.n < MIN_SAMPLES_LOW or not self.fitted:
            return "none"
        if self.n >= MIN_SAMPLES_HIGH:
            level = "high"
        elif self.n >= MIN_SAMPLES_MEDIUM:
            level = "medium"
        else:
            level = "low"
        if week is not None and self.weeks_covered < 4:
            # História concentrada em poucas semanas do ano: não dá para
            # afirmar muito sobre sazonalidade.
            level = {"high": "medium", "medium": "low", "low": "low"}[level]
        return level


def _smoothed_group_effect(
    residual_by_week: Dict[int, List[Tuple[float, float]]],
    target_week: int,
) -> Tuple[float, float]:
    """Efeito sazonal da semana alvo, tomando emprestado das semanas vizinhas.

    Retorna (efeito_bruto, peso_efetivo).
    """
    pairs: List[Tuple[float, float]] = []
    total_weight = 0.0
    for week, residuals in residual_by_week.items():
        dist = week_distance(week, target_week)
        if dist > SEASONAL_KERNEL_RADIUS:
            continue
        kernel = math.exp(-(dist ** 2) / (2 * SEASONAL_KERNEL_SIGMA ** 2))
        for value, weight in residuals:
            pairs.append((value, weight * kernel))
            total_weight += weight * kernel
    if not pairs or total_weight <= 0:
        return 0.0, 0.0
    return weighted_median(pairs), total_weight


def _bucket_effect(
    residual_by_bucket: Dict[str, List[Tuple[float, float]]],
    target: str,
) -> Tuple[float, float]:
    """Efeito de antecedência, suavizado com as faixas adjacentes."""
    target_idx = _BUCKET_INDEX[target]
    pairs: List[Tuple[float, float]] = []
    total_weight = 0.0
    for bucket, residuals in residual_by_bucket.items():
        dist = abs(_BUCKET_INDEX[bucket] - target_idx)
        if dist > 1:
            continue
        kernel = 1.0 if dist == 0 else 0.35
        for value, weight in residuals:
            pairs.append((value, weight * kernel))
            total_weight += weight * kernel
    if not pairs or total_weight <= 0:
        return 0.0, 0.0
    return weighted_median(pairs), total_weight


def fit_route_model(samples: Sequence[Sample], iterations: int = 3) -> RouteModel:
    """Ajusta o modelo base + sazonalidade + antecedência por backfitting robusto."""
    usable = [s for s in samples if s.weight > 0 and s.price > 0]
    model = RouteModel(n=len(usable), total_weight=sum(s.weight for s in usable))
    if not usable:
        return model

    logs = [(s.log_price, s.weight) for s in usable]
    model.log_base = weighted_median(logs)
    model.weeks_covered = len({s.week for s in usable})

    if len(usable) < MIN_SAMPLES_MODEL:
        # Pouca história: mantém só a base, sem inventar efeitos.
        residuals = [s.log_price - model.log_base for s in usable]
        model.residuals = residuals
        model.residual_scale = DEFAULT_RESIDUAL_SCALE
        return model

    seasonal: Dict[int, float] = {}
    advance: Dict[str, float] = {}

    for _ in range(max(1, iterations)):
        # 1. Sazonalidade, dado o efeito de antecedência corrente.
        by_week: Dict[int, List[Tuple[float, float]]] = {}
        for s in usable:
            resid = s.log_price - model.log_base - advance.get(s.bucket, 0.0)
            by_week.setdefault(s.week, []).append((resid, s.weight))

        new_seasonal: Dict[int, float] = {}
        for week in range(1, WEEKS_IN_YEAR + 1):
            raw, eff_weight = _smoothed_group_effect(by_week, week)
            if eff_weight <= 0:
                continue
            shrink = eff_weight / (eff_weight + SEASONAL_SHRINK_K)
            new_seasonal[week] = raw * shrink
        seasonal = new_seasonal

        # 2. Antecedência, dado o efeito sazonal corrente.
        by_bucket: Dict[str, List[Tuple[float, float]]] = {}
        for s in usable:
            resid = s.log_price - model.log_base - seasonal.get(s.week, 0.0)
            by_bucket.setdefault(s.bucket, []).append((resid, s.weight))

        new_advance: Dict[str, float] = {}
        for label in _BUCKET_ORDER:
            raw, eff_weight = _bucket_effect(by_bucket, label)
            if eff_weight <= 0:
                continue
            shrink = eff_weight / (eff_weight + ADVANCE_SHRINK_K)
            new_advance[label] = raw * shrink
        advance = new_advance

        # 3. Recentraliza a base no resíduo remanescente.
        leftovers = [
            (
                s.log_price
                - model.log_base
                - seasonal.get(s.week, 0.0)
                - advance.get(s.bucket, 0.0),
                s.weight,
            )
            for s in usable
        ]
        model.log_base += weighted_median(leftovers)

    model.seasonal = seasonal
    model.advance = advance
    model.fitted = True

    residuals = [
        s.log_price - model.log_base - seasonal.get(s.week, 0.0) - advance.get(s.bucket, 0.0)
        for s in usable
    ]
    model.residuals = residuals
    scale = robust_scale(residuals, center=0.0)
    if scale <= 0:
        scale = DEFAULT_RESIDUAL_SCALE
    model.residual_scale = min(MAX_RESIDUAL_SCALE, max(MIN_RESIDUAL_SCALE, scale))
    return model


# ---------------------------------------------------------------- diagnóstico


@dataclass
class Assessment:
    """Veredito sobre uma cotação, comparada ao padrão histórico da rota."""

    price: float
    expected_price: float
    currency: str = "BRL"
    z_score: float = 0.0
    discount_pct: float = 0.0
    percentile: float = 0.0  # % de cotações históricas mais caras que esta
    confidence: str = "none"
    method: str = "model"  # model | relative | insufficient
    verdict: str = "normal"
    severity: int = 0
    deal_score: float = 0.0
    n_samples: int = 0
    n_season: int = 0
    weeks_covered: int = 0
    seasonal_pct: float = 0.0
    advance_pct: float = 0.0
    advance_label: str = ""
    is_lowest_for_date: bool = False
    is_lowest_for_route: bool = False
    lowest_seen: Optional[float] = None
    median_recent: Optional[float] = None
    reasons: List[str] = field(default_factory=list)

    @property
    def delta_pct(self) -> float:
        """Distância até o preço padrão, com sinal intuitivo: + é mais caro."""
        if self.expected_price <= 0:
            return 0.0
        return 100.0 * (self.price / self.expected_price - 1.0)

    @property
    def delta_label(self) -> str:
        delta = self.delta_pct
        if abs(delta) < 0.5:
            return "no preço padrão"
        return f"{abs(delta):.0f}% {'acima' if delta > 0 else 'abaixo'} do padrão"

    @property
    def is_deal(self) -> bool:
        return self.severity >= 1

    @property
    def severity_label(self) -> str:
        return SEVERITY_LABEL.get(self.severity, "dentro do normal")

    def to_dict(self) -> Dict[str, object]:
        return {
            "price": round(self.price, 2),
            "expected_price": round(self.expected_price, 2),
            "currency": self.currency,
            "z_score": round(self.z_score, 3),
            "discount_pct": round(self.discount_pct, 2),
            "delta_pct": round(self.delta_pct, 2),
            "delta_label": self.delta_label,
            "percentile": round(self.percentile, 1),
            "confidence": self.confidence,
            "method": self.method,
            "verdict": self.verdict,
            "severity": self.severity,
            "severity_label": self.severity_label,
            "deal_score": round(self.deal_score, 1),
            "n_samples": self.n_samples,
            "n_season": self.n_season,
            "seasonal_pct": round(self.seasonal_pct, 1),
            "advance_pct": round(self.advance_pct, 1),
            "advance_label": self.advance_label,
            "is_lowest_for_date": self.is_lowest_for_date,
            "is_lowest_for_route": self.is_lowest_for_route,
            "lowest_seen": round(self.lowest_seen, 2) if self.lowest_seen else None,
            "reasons": list(self.reasons),
        }


def _deal_score(z: float) -> float:
    """Converte o z-score em uma nota 0-100 (maior = melhor oportunidade)."""
    try:
        return 100.0 / (1.0 + math.exp(1.25 * (z + 1.0)))
    except OverflowError:
        return 0.0 if z > 0 else 100.0


def _classify(z: float, discount_pct: float, confidence: str) -> int:
    factor = CONFIDENCE_FACTOR.get(confidence, 1.5)
    if z <= Z_SUSPICIOUS * factor and discount_pct >= 35.0:
        return 4
    for severity, threshold in ((3, Z_EXCEPTIONAL), (2, Z_GREAT), (1, Z_GOOD)):
        if z <= threshold * factor and discount_pct >= MIN_DISCOUNT[severity]:
            return severity
    if z >= Z_ABOVE * factor:
        return -1
    return 0


def _season_window_samples(
    samples: Sequence[Sample], week: int, radius: int = SEASONAL_KERNEL_RADIUS
) -> List[Sample]:
    return [s for s in samples if week_distance(s.week, week) <= radius]


def assess(
    price: float,
    departure_date: date,
    days_to_departure: Optional[int],
    history: Sequence[Sample],
    model: Optional[RouteModel] = None,
    currency: str = "BRL",
) -> Assessment:
    """Compara uma cotação ao padrão histórico da rota naquele período do ano."""
    price = float(price)
    history = list(history)
    model = model if model is not None else fit_route_model(history)

    week = week_of_year(departure_date)
    bucket = advance_bucket(days_to_departure)
    season_samples = _season_window_samples(history, week)
    confidence = model.confidence(week)
    if confidence != "none" and len(season_samples) < 3:
        confidence = {"high": "medium", "medium": "low", "low": "low"}[confidence]

    lowest_seen = min((s.price for s in history), default=None)
    same_date = [s for s in history if s.departure_date == departure_date]
    lowest_same_date = min((s.price for s in same_date), default=None)

    assessment = Assessment(
        price=price,
        expected_price=price,
        currency=currency,
        n_samples=len(history),
        n_season=len(season_samples),
        weeks_covered=model.weeks_covered,
        advance_label=bucket,
        lowest_seen=lowest_seen,
        is_lowest_for_route=bool(lowest_seen is not None and price < lowest_seen),
        is_lowest_for_date=bool(lowest_same_date is not None and price < lowest_same_date),
    )

    if len(history) < MIN_SAMPLES_MODEL or not model.fitted:
        return _assess_relative(assessment, price, same_date or history)

    expected = model.predict(departure_date, days_to_departure)
    assessment.expected_price = expected
    assessment.seasonal_pct = 100.0 * (math.exp(model.seasonal_offset(week)) - 1.0)
    assessment.advance_pct = 100.0 * (math.exp(model.advance_offset(bucket)) - 1.0)

    residual = math.log(price) - math.log(expected)
    assessment.z_score = residual / model.residual_scale
    assessment.discount_pct = 100.0 * (1.0 - price / expected) if expected > 0 else 0.0
    assessment.confidence = confidence
    assessment.method = "model"

    # Percentil calculado sobre os resíduos das cotações do mesmo período do ano,
    # ponderados pela proximidade da semana.
    resid_pairs: List[Tuple[float, float]] = []
    for s in season_samples:
        kernel = math.exp(-(week_distance(s.week, week) ** 2) / (2 * SEASONAL_KERNEL_SIGMA ** 2))
        resid_pairs.append((model.residual_of(s), s.weight * kernel))
    assessment.percentile = weighted_percentile_of(resid_pairs, residual)

    recent = sorted(
        [s for s in same_date if s.observed_at is not None],
        key=lambda s: s.observed_at,
        reverse=True,
    )[:10]
    if recent:
        assessment.median_recent = median([s.price for s in recent])

    severity = _classify(assessment.z_score, assessment.discount_pct, confidence)

    # Menor preço já visto para a mesma data reforça o sinal.
    if assessment.is_lowest_for_date and severity >= 1 and severity < 3:
        severity += 1

    assessment.severity = severity
    assessment.verdict = VERDICT_BY_SEVERITY[severity]
    assessment.deal_score = _deal_score(assessment.z_score)
    assessment.reasons = _build_reasons(assessment, model, week, bucket)
    return assessment


def _assess_relative(
    assessment: Assessment, price: float, history: Sequence[Sample]
) -> Assessment:
    """Fallback quando ainda não há história suficiente para o modelo sazonal."""
    assessment.method = "relative"
    prices = [s.price for s in history]
    if len(prices) < 4:
        assessment.method = "insufficient"
        assessment.verdict = "insufficient_data"
        assessment.confidence = "none"
        assessment.expected_price = median(prices) if prices else price
        assessment.reasons = [
            f"Histórico ainda insuficiente ({len(prices)} cotações). "
            "O monitor precisa de mais coletas para definir o preço padrão."
        ]
        return assessment

    reference = median(prices)
    assessment.expected_price = reference
    assessment.discount_pct = 100.0 * (1.0 - price / reference) if reference > 0 else 0.0
    assessment.confidence = "low"
    scale = robust_scale([math.log(p) for p in prices]) or DEFAULT_RESIDUAL_SCALE
    scale = min(MAX_RESIDUAL_SCALE, max(MIN_RESIDUAL_SCALE, scale))
    assessment.z_score = (math.log(price) - math.log(reference)) / scale
    assessment.percentile = percentile_of(prices, price)

    if assessment.discount_pct >= 25.0:
        severity = 2
    elif assessment.discount_pct >= 15.0:
        severity = 1
    elif assessment.discount_pct <= -15.0:
        severity = -1
    else:
        severity = 0

    assessment.severity = severity
    assessment.verdict = VERDICT_BY_SEVERITY[severity]
    assessment.deal_score = _deal_score(assessment.z_score)
    assessment.reasons = [
        f"Comparação simples com a mediana das {len(prices)} cotações já vistas "
        f"({fmt_num(reference)}); ainda sem ajuste de sazonalidade."
    ]
    if assessment.is_lowest_for_date:
        assessment.reasons.append("É o menor preço já registrado para esta data de ida.")
    return assessment


def _build_reasons(
    assessment: Assessment, model: RouteModel, week: int, bucket: str
) -> List[str]:
    reasons: List[str] = []
    if assessment.discount_pct >= 0.5:
        reasons.append(
            f"{assessment.discount_pct:.0f}% abaixo do preço esperado "
            f"({fmt_num(assessment.expected_price)}) para esta rota nesta época do ano."
        )
    elif assessment.discount_pct <= -0.5:
        reasons.append(
            f"{abs(assessment.discount_pct):.0f}% acima do preço esperado "
            f"({fmt_num(assessment.expected_price)}) para esta rota nesta época do ano."
        )
    else:
        reasons.append(
            f"Praticamente no preço esperado ({fmt_num(assessment.expected_price)})."
        )

    if assessment.percentile >= 50:
        reasons.append(
            f"Mais barata que {assessment.percentile:.0f}% das cotações históricas "
            f"do mesmo período do ano (semana {week})."
        )

    if abs(assessment.seasonal_pct) >= 4:
        direction = "cara" if assessment.seasonal_pct > 0 else "barata"
        reasons.append(
            f"Esta época do ano costuma ser {abs(assessment.seasonal_pct):.0f}% mais "
            f"{direction} que a média anual da rota."
        )

    if abs(assessment.advance_pct) >= 4:
        direction = "acima" if assessment.advance_pct > 0 else "abaixo"
        reasons.append(
            f"Comprando com {bucket} dias de antecedência, o padrão fica "
            f"{abs(assessment.advance_pct):.0f}% {direction} da média."
        )

    if assessment.is_lowest_for_date:
        reasons.append("É o menor preço já registrado para esta data de ida.")
    if assessment.is_lowest_for_route:
        reasons.append("É o menor preço já registrado para a rota inteira.")

    if assessment.severity == 4:
        reasons.append(
            "Queda grande demais para ser típica: pode ser tarifa-erro "
            "(costuma durar pouco e pode ser cancelada pela companhia)."
        )

    reasons.append(
        f"Baseado em {assessment.n_samples} cotações da rota "
        f"({assessment.n_season} no mesmo período do ano); confiança "
        f"{CONFIDENCE_LABEL.get(assessment.confidence, assessment.confidence)}."
    )
    return reasons


def build_model_for(observations: Iterable[Observation]) -> RouteModel:
    """Atalho: constrói o modelo diretamente de observações do banco."""
    return fit_route_model(samples_from_observations(observations))
