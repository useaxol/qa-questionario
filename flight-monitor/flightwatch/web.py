"""Dashboard web e API JSON do monitor."""
from __future__ import annotations

import random
import threading
import time
from collections import OrderedDict
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from flask import (
    Flask, abort, flash, jsonify, redirect, render_template, request, url_for,
)

from . import airports, analytics, charts, db, monitor
from .config import Config
from .models import CABINS, CABIN_LABELS, Observation, Watch, parse_date
from .notifier import build_notifier, format_money
from .providers import ProviderError, get_provider

SEVERITY_TONE = {
    -1: ("above", "Acima do normal"),
    0: ("normal", "Dentro do normal"),
    1: ("good", "Boa oportunidade"),
    2: ("great", "Ótima oportunidade"),
    3: ("exceptional", "Oportunidade excepcional"),
    4: ("suspect", "Suspeito · possível tarifa-erro"),
}

CONFIDENCE_LABEL = analytics.CONFIDENCE_LABEL


def daily_series(observations: List[Observation]) -> List[Tuple[datetime, float]]:
    """Menor preço por dia de coleta — uma linha limpa para o gráfico."""
    by_day: "OrderedDict[date, Tuple[datetime, float]]" = OrderedDict()
    for obs in sorted(observations, key=lambda o: o.observed_at or datetime.min):
        if not obs.observed_at or not obs.price_per_pax:
            continue
        day = obs.observed_at.date()
        current = by_day.get(day)
        if current is None or obs.price_per_pax < current[1]:
            by_day[day] = (obs.observed_at, float(obs.price_per_pax))
    return list(by_day.values())


def expected_series(
    watch: Watch, model: analytics.RouteModel, points: List[Tuple[datetime, float]]
) -> List[Tuple[datetime, float]]:
    """Preço esperado na mesma malha de datas do histórico observado."""
    if not model.fitted or watch.departure_date is None:
        return []
    out = []
    for moment, _ in points:
        dtd = (watch.departure_date - moment.date()).days
        out.append((moment, model.predict(watch.departure_date, dtd)))
    return out


def create_app(config: Optional[Config] = None) -> Flask:
    config = config or Config.from_env()
    app = Flask(__name__)
    app.config["SECRET_KEY"] = config.secret_key
    app.config["FLIGHTWATCH"] = config

    with db.session(config.db_path):
        pass  # garante o schema

    def conn():
        connection = db.connect(config.db_path)
        db.init_db(connection)
        return connection

    # ------------------------------------------------------------ filtros

    @app.template_filter("money")
    def _money(value, currency="BRL"):
        if value is None:
            return "—"
        return format_money(float(value), currency)

    @app.template_filter("pct")
    def _pct(value, digits=1):
        if value is None:
            return "—"
        return f"{float(value):+.{digits}f}%"

    @app.template_filter("airport")
    def _airport(code):
        found = airports.get(code)
        return f"{found.city} ({found.iata})" if found else (code or "—")

    @app.template_filter("dt")
    def _dt(value, fmt="%d/%m/%Y"):
        if not value:
            return "—"
        if isinstance(value, str):
            value = datetime.fromisoformat(value)
        return value.strftime(fmt)

    @app.context_processor
    def _globals():
        return {
            "cabin_labels": CABIN_LABELS,
            "confidence_label": CONFIDENCE_LABEL,
            "severity_tone": SEVERITY_TONE,
            "airports_list": airports.all_airports(),
            "provider_name": config.provider,
            "now": datetime.now(),
        }

    # ---------------------------------------------------------- dashboard

    @app.route("/")
    def index():
        connection = conn()
        try:
            watches = db.list_watches(connection)
            cards = []
            for watch in watches:
                snapshot = monitor.watch_snapshot(connection, watch)
                history = db.watch_history(connection, watch.id) if watch.id else []
                points = daily_series(history)
                snapshot["spark"] = charts.sparkline([p for _, p in points[-40:]])
                snapshot["n_points"] = len(points)
                cards.append(snapshot)

            deals = [c for c in cards if c["assessment"] and c["assessment"].is_deal]
            best = max(
                (c for c in cards if c["assessment"]),
                key=lambda c: c["assessment"].deal_score,
                default=None,
            )
            stats = db.observation_stats(connection)
            stats["alerts_30d"] = db.count_alerts_since(connection, datetime.now() - timedelta(days=30))
            stats["active"] = sum(1 for w in watches if w.active)
            potential = sum(
                max(0.0, (c["assessment"].expected_price - c["assessment"].price))
                * max(1, c["watch"].passengers)
                for c in deals
            )
            return render_template(
                "index.html",
                cards=cards,
                deals=deals,
                best=best,
                stats=stats,
                potential=potential,
                alerts=db.list_alerts(connection, limit=8),
            )
        finally:
            connection.close()

    # ------------------------------------------------------------ detalhe

    @app.route("/watch/<int:watch_id>")
    def watch_detail(watch_id: int):
        connection = conn()
        try:
            watch = db.get_watch(connection, watch_id)
            if watch is None:
                abort(404)

            snapshot = monitor.watch_snapshot(connection, watch)
            model: analytics.RouteModel = snapshot["model"]
            history = db.watch_history(connection, watch_id)
            points = daily_series(history)
            expected = expected_series(watch, model, points)

            alert_rows = db.list_alerts(connection, limit=50, watch_id=watch_id)
            alert_points = [
                (a.created_at, a.price / max(1, watch.passengers), a.severity)
                for a in alert_rows
                if a.created_at
            ]

            history_chart = charts.price_history_chart(
                points,
                expected,
                alerts=alert_points,
                currency=watch.currency,
                band_pct=model.residual_scale if model.fitted else 0.0,
            )
            year = (watch.departure_date or date.today()).year
            seasonal_chart = (
                charts.seasonal_chart(model.monthly_curve(year))
                if model.fitted
                else charts.empty_chart("Histórico insuficiente para estimar a sazonalidade.")
            )
            advance_chart = (
                charts.advance_chart(
                    [(label, pct) for label, pct in model.advance_curve() if label in model.advance]
                )
                if model.fitted
                else charts.empty_chart("Histórico insuficiente para a curva de antecedência.")
            )

            insights = build_insights(model, watch)
            return render_template(
                "watch.html",
                watch=watch,
                snapshot=snapshot,
                model=model,
                history_chart=history_chart,
                seasonal_chart=seasonal_chart,
                advance_chart=advance_chart,
                insights=insights,
                alerts=alert_rows,
                observations=list(reversed(history))[:25],
                n_points=len(points),
            )
        finally:
            connection.close()

    # ------------------------------------------------------- criar/editar

    @app.route("/watches/new", methods=["GET", "POST"])
    def new_watch():
        if request.method == "POST":
            try:
                watch = watch_from_form(request.form, config)
            except ValueError as exc:
                flash(str(exc), "error")
                return render_template("new_watch.html", form=request.form, cabins=CABINS)

            connection = conn()
            try:
                watch.id = db.insert_watch(connection, watch)
                flash(f"Monitorando {watch.display_name}.", "ok")
                if request.form.get("collect_now"):
                    try:
                        provider = get_provider(config)
                        monitor.collect_watch(
                            connection, config, provider, watch, notifier=build_notifier(config)
                        )
                    except ProviderError as exc:
                        flash(f"Primeira coleta falhou: {exc}", "error")
                return redirect(url_for("watch_detail", watch_id=watch.id))
            finally:
                connection.close()
        return render_template("new_watch.html", form={}, cabins=CABINS)

    @app.route("/watch/<int:watch_id>/toggle", methods=["POST"])
    def toggle_watch(watch_id: int):
        connection = conn()
        try:
            watch = db.get_watch(connection, watch_id)
            if watch is None:
                abort(404)
            db.set_watch_active(connection, watch_id, not watch.active)
            flash("Monitoramento " + ("pausado." if watch.active else "retomado."), "ok")
        finally:
            connection.close()
        return redirect(request.referrer or url_for("index"))

    @app.route("/watch/<int:watch_id>/delete", methods=["POST"])
    def remove_watch(watch_id: int):
        connection = conn()
        try:
            db.delete_watch(connection, watch_id)
            flash("Monitoramento removido.", "ok")
        finally:
            connection.close()
        return redirect(url_for("index"))

    # ------------------------------------------------------------- coleta

    @app.route("/collect", methods=["POST"])
    def collect():
        watch_id = request.form.get("watch_id", type=int)
        connection = conn()
        try:
            provider = get_provider(config)
            notifier = build_notifier(config)
            results = monitor.run_collection(
                connection, config, provider,
                watch_ids=[watch_id] if watch_id else None,
                notifier=notifier,
            )
            ok = [r for r in results if r.ok]
            failed = [r for r in results if not r.ok]
            found = sum(1 for r in ok if r.alert is not None)
            flash(
                f"Coleta concluída: {len(ok)} rota(s) cotada(s), {found} alerta(s)."
                + (f" {len(failed)} falha(s)." if failed else ""),
                "ok" if not failed else "warn",
            )
            for result in failed:
                flash(f"{result.watch.display_name}: {result.error}", "error")
        except ProviderError as exc:
            flash(f"Provedor indisponível: {exc}", "error")
        finally:
            connection.close()
        if watch_id:
            return redirect(url_for("watch_detail", watch_id=watch_id))
        return redirect(url_for("index"))

    @app.route("/alerts")
    def alerts_page():
        connection = conn()
        try:
            rows = db.list_alerts(connection, limit=200)
            watches = {w.id: w for w in db.list_watches(connection)}
            return render_template("alerts.html", alerts=rows, watches=watches)
        finally:
            connection.close()

    # ---------------------------------------------------------------- API

    @app.route("/api/watches")
    def api_watches():
        connection = conn()
        try:
            payload = []
            for watch in db.list_watches(connection):
                snapshot = monitor.watch_snapshot(connection, watch)
                assessment = snapshot["assessment"]
                payload.append(
                    {
                        "id": watch.id,
                        "label": watch.display_name,
                        "origin": watch.origin,
                        "destination": watch.destination,
                        "departure_date": watch.departure_date.isoformat() if watch.departure_date else None,
                        "return_date": watch.return_date.isoformat() if watch.return_date else None,
                        "cabin": watch.cabin,
                        "passengers": watch.passengers,
                        "currency": watch.currency,
                        "active": watch.active,
                        "last_checked_at": watch.last_checked_at.isoformat() if watch.last_checked_at else None,
                        "latest_price": snapshot["latest"].price if snapshot["latest"] else None,
                        "assessment": assessment.to_dict() if assessment else None,
                        "history_size": snapshot["n_samples"],
                    }
                )
            return jsonify({"watches": payload})
        finally:
            connection.close()

    @app.route("/api/watches", methods=["POST"])
    def api_create_watch():
        data = request.get_json(silent=True) or {}
        try:
            watch = watch_from_form(data, config)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        connection = conn()
        try:
            watch.id = db.insert_watch(connection, watch)
            return jsonify({"id": watch.id, "label": watch.display_name}), 201
        finally:
            connection.close()

    @app.route("/api/watches/<int:watch_id>/history")
    def api_history(watch_id: int):
        connection = conn()
        try:
            watch = db.get_watch(connection, watch_id)
            if watch is None:
                return jsonify({"error": "not found"}), 404
            history = db.watch_history(connection, watch_id)
            return jsonify(
                {
                    "watch_id": watch_id,
                    "currency": watch.currency,
                    "points": [
                        {
                            "observed_at": o.observed_at.isoformat() if o.observed_at else None,
                            "departure_date": o.departure_date.isoformat() if o.departure_date else None,
                            "price": o.price,
                            "price_per_pax": o.price_per_pax,
                            "airline": o.airline,
                            "stops": o.stops,
                            "days_to_departure": o.days_to_departure,
                        }
                        for o in history
                    ],
                }
            )
        finally:
            connection.close()

    @app.route("/api/alerts")
    def api_alerts():
        limit = request.args.get("limit", default=50, type=int)
        connection = conn()
        try:
            return jsonify(
                {
                    "alerts": [
                        {
                            "id": a.id,
                            "watch_id": a.watch_id,
                            "created_at": a.created_at.isoformat() if a.created_at else None,
                            "verdict": a.verdict,
                            "severity": a.severity,
                            "price": a.price,
                            "expected_price": a.expected_price,
                            "discount_pct": a.discount_pct,
                            "z_score": a.z_score,
                            "deal_score": a.deal_score,
                            "confidence": a.confidence,
                            "message": a.message,
                        }
                        for a in db.list_alerts(connection, limit=limit)
                    ]
                }
            )
        finally:
            connection.close()

    @app.route("/api/collect", methods=["POST"])
    def api_collect():
        data = request.get_json(silent=True) or {}
        watch_ids = data.get("watch_ids")
        connection = conn()
        try:
            provider = get_provider(config)
            results = monitor.run_collection(
                connection, config, provider, watch_ids=watch_ids,
                notifier=build_notifier(config),
            )
            return jsonify(
                {
                    "results": [
                        {
                            "watch_id": r.watch.id,
                            "ok": r.ok,
                            "error": r.error,
                            "price": r.best.price if r.best else None,
                            "assessment": r.assessment.to_dict() if r.assessment else None,
                            "alert": bool(r.alert),
                        }
                        for r in results
                    ]
                }
            )
        except ProviderError as exc:
            return jsonify({"error": str(exc)}), 502
        finally:
            connection.close()

    @app.route("/api/airports")
    def api_airports():
        query = request.args.get("q", "")
        return jsonify(
            {
                "airports": [
                    {"iata": a.iata, "city": a.city, "country": a.country, "name": a.name}
                    for a in airports.search(query, limit=25)
                ]
            }
        )

    @app.route("/health")
    def health():
        return jsonify({"status": "ok", "provider": config.provider})

    return app


def build_insights(model: analytics.RouteModel, watch: Watch) -> Dict[str, Any]:
    """Leituras práticas do modelo: quando viajar e quando comprar."""
    if not model.fitted:
        return {}
    year = (watch.departure_date or date.today()).year
    monthly = model.monthly_curve(year)
    cheapest_month = min(monthly, key=lambda t: t[1])
    priciest_month = max(monthly, key=lambda t: t[1])
    advance = [(label, pct) for label, pct in model.advance_curve() if label in model.advance]
    best_window = min(advance, key=lambda t: t[1]) if advance else None
    worst_window = max(advance, key=lambda t: t[1]) if advance else None
    return {
        "cheapest_month": (charts.MONTH_ABBR[cheapest_month[0] - 1], cheapest_month[1]),
        "priciest_month": (charts.MONTH_ABBR[priciest_month[0] - 1], priciest_month[1]),
        "best_window": best_window,
        "worst_window": worst_window,
        "base_price": model.base_price,
        "volatility_pct": 100.0 * model.residual_scale,
    }


def watch_from_form(form: Any, config: Config) -> Watch:
    """Valida e constrói um Watch a partir do formulário web ou do JSON da API."""

    def value(key: str, default: str = "") -> str:
        raw = form.get(key, default)
        return str(raw).strip() if raw is not None else ""

    origin = value("origin").upper()[:3]
    destination = value("destination").upper()[:3]
    if len(origin) != 3 or len(destination) != 3:
        raise ValueError("Informe os códigos IATA de origem e destino (3 letras).")
    if origin == destination:
        raise ValueError("Origem e destino precisam ser diferentes.")

    try:
        departure = parse_date(value("departure_date"))
    except ValueError:
        raise ValueError("Data de ida inválida.")
    if departure is None:
        raise ValueError("Informe a data de ida.")
    if departure < date.today():
        raise ValueError("A data de ida precisa ser futura.")

    try:
        return_date = parse_date(value("return_date")) or None
    except ValueError:
        raise ValueError("Data de volta inválida.")

    trip_type = value("trip_type", "round") or "round"
    if trip_type == "round" and return_date is None:
        raise ValueError("Viagem de ida e volta exige a data de volta.")
    if return_date is not None and return_date < departure:
        raise ValueError("A volta não pode ser antes da ida.")
    if trip_type == "oneway":
        return_date = None

    cabin = value("cabin", "ECONOMY").upper() or "ECONOMY"
    if cabin not in CABINS:
        raise ValueError(f"Cabine inválida: {cabin}.")

    def as_int(key: str, default: int) -> int:
        raw = value(key)
        try:
            return int(raw) if raw else default
        except ValueError:
            raise ValueError(f"Valor numérico inválido em '{key}'.")

    def as_float(key: str) -> Optional[float]:
        raw = value(key).replace(".", "").replace(",", ".") if value(key) else ""
        try:
            return float(raw) if raw else None
        except ValueError:
            raise ValueError(f"Valor numérico inválido em '{key}'.")

    max_stops_raw = value("max_stops")
    max_stops = int(max_stops_raw) if max_stops_raw not in ("", "any") else None

    return Watch(
        label=value("label"),
        origin=origin,
        destination=destination,
        departure_date=departure,
        return_date=return_date,
        flex_days=max(0, min(7, as_int("flex_days", 0))),
        trip_type=trip_type,
        cabin=cabin,
        passengers=max(1, min(9, as_int("passengers", 1))),
        currency=(value("currency") or config.currency).upper(),
        max_stops=max_stops,
        target_price=as_float("target_price"),
        active=True,
        created_at=datetime.now(),
    )


class CollectorThread(threading.Thread):
    """Agendador simples embutido no servidor web."""

    def __init__(self, config: Config):
        super().__init__(daemon=True, name="flightwatch-collector")
        self.config = config
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:  # pragma: no cover - laço de fundo
        interval = max(60, self.config.collect_interval_minutes * 60)
        jitter = max(0, self.config.collect_jitter_seconds)
        # Primeira coleta logo após subir, para o dashboard não nascer vazio.
        self._stop.wait(10)
        while not self._stop.is_set():
            connection = None
            try:
                connection = db.connect(self.config.db_path)
                db.init_db(connection)
                provider = get_provider(self.config)
                results = monitor.run_collection(
                    connection, self.config, provider, notifier=build_notifier(self.config)
                )
                alerts = sum(1 for r in results if r.alert)
                print(
                    f"[flightwatch] coleta automática: {len(results)} rota(s), "
                    f"{alerts} alerta(s) — {datetime.now():%d/%m %H:%M}",
                    flush=True,
                )
            except Exception as exc:
                print(f"[flightwatch] coleta automática falhou: {exc}", flush=True)
            finally:
                if connection is not None:
                    connection.close()
            self._stop.wait(interval + random.uniform(0, jitter))
