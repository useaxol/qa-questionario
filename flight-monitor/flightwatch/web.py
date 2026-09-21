"""Painel web e API JSON do monitor."""
from __future__ import annotations

import random
import threading
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from flask import (
    Flask, abort, flash, jsonify, redirect, render_template, request, url_for,
)

from . import airports, benchmarks, calibration, charts, db, indexing, monitor
from .config import Config
from .indexing import Verdict
from .models import CABINS, CABIN_LABELS, KIND_BASKET, Quote, Watch, parse_date
from .notifier import build_notifier, format_money
from .providers import ProviderError, get_provider

LEVEL_TONE = {
    -1: ("above", "Acima do normal"),
    0: ("normal", "Dentro do normal"),
    1: ("good", "Abaixo do normal"),
    2: ("great", "Distorção clara"),
    3: ("exceptional", "Distorção forte"),
    4: ("suspect", "Suspeito · possível tarifa-erro"),
}

DRIVER_TONE = {
    "distortion": "descolou da cesta",
    "benchmark": "abaixo do próprio benchmark",
    "both": "abaixo do benchmark e da cesta",
    "none": "sem sinal",
}


def create_app(config: Optional[Config] = None) -> Flask:
    config = config or Config.from_env()
    app = Flask(__name__)
    app.config["SECRET_KEY"] = config.secret_key
    app.config["FLIGHTWATCH"] = config

    with db.session(config.db_path):
        pass

    def conn():
        connection = db.connect(config.db_path)
        db.init_db(connection)
        return connection

    # ------------------------------------------------------------ filtros

    @app.template_filter("money")
    def _money(value, currency="BRL"):
        return "—" if value is None else format_money(float(value), currency)

    @app.template_filter("idx")
    def _idx(value, digits=0):
        return "—" if value is None else f"{float(value):.{digits}f}"

    @app.template_filter("points")
    def _points(value):
        if value is None:
            return "—"
        rounded = round(float(value))
        return "0" if rounded == 0 else f"{rounded:+.0f}"

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
            "level_tone": LEVEL_TONE,
            "driver_tone": DRIVER_TONE,
            "destinations": benchmarks.DESTINATIONS,
            "basket_codes": benchmarks.BASKET,
            "provider_name": config.provider,
            "probe": monitor.ProbeSpec.from_config(config),
            "now": datetime.now(),
        }

    # ---------------------------------------------------------- dashboard

    @app.route("/")
    def index():
        connection = conn()
        try:
            basket = monitor.current_basket(connection)
            snapshot = db.latest_snapshot(connection)
            verdicts = indexing.evaluate_basket(basket) if basket else []
            by_destination = {v.destination: v for v in verdicts}

            rows = []
            for code in benchmarks.BASKET:
                dest = benchmarks.DESTINATIONS[code]
                verdict = by_destination.get(code)
                series = db.destination_index_series(connection, code, limit=40)
                rows.append(
                    {
                        "dest": dest,
                        "verdict": verdict,
                        "spark": charts.sparkline([v for _, v in series]),
                        "points": len(series),
                    }
                )
            rows.sort(key=lambda r: (r["verdict"].index if r["verdict"] else 999))

            history = db.snapshot_history(connection, limit=120)
            index_chart = charts.index_history_chart(
                [(s.collected_at, s.index_value) for s in history],
                label="índice de mercado",
                band_pct=0.0,
            )
            bars = charts.basket_bars(
                [
                    (
                        benchmarks.DESTINATIONS[v.destination].label,
                        v.index,
                        f"{v.label} · {v.driver_label}",
                    )
                    for v in sorted(verdicts, key=lambda v: v.index)
                ],
                basket_index=basket.index if basket else None,
            )

            stats = db.quote_stats(connection)
            stats["alerts_30d"] = db.count_alerts_since(
                connection, datetime.now() - timedelta(days=30)
            )
            summary = indexing.market_summary(basket) if basket else None
            distorted = [v for v in verdicts if v.is_alert]

            watch_cards = []
            for watch in db.list_watches(connection):
                quote = db.latest_quote(connection, watch.id) if watch.id else None
                watch_cards.append(
                    {"watch": watch, "quote": quote, "verdict": _watch_verdict(quote, basket)}
                )

            return render_template(
                "index.html",
                basket=basket,
                snapshot=snapshot,
                summary=summary,
                rows=rows,
                distorted=distorted,
                bars=bars,
                index_chart=index_chart,
                stats=stats,
                watch_cards=watch_cards,
                alerts=db.list_alerts(connection, limit=8),
                rounds=len(history),
            )
        finally:
            connection.close()

    # ------------------------------------------------------------ destino

    @app.route("/destino/<code>")
    def destination_detail(code: str):
        code = code.upper()
        dest = benchmarks.get(code)
        if dest is None:
            abort(404)

        connection = conn()
        try:
            basket = monitor.current_basket(connection)
            verdict = None
            if basket:
                for candidate in indexing.evaluate_basket(basket):
                    if candidate.destination == code:
                        verdict = candidate
                        break

            series = db.destination_index_series(connection, code, limit=180)
            snapshots = {s.collected_at: s.index_value for s in db.snapshot_history(connection, 180)}
            comparison = [(t, v) for t, v in snapshots.items()]
            comparison.sort(key=lambda item: item[0])

            alerts = db.list_alerts(connection, limit=30, destination=code)
            alert_points = [
                (a.created_at, a.index_value, a.level) for a in alerts if a.created_at
            ]
            chart = charts.index_history_chart(
                series,
                comparison,
                band_pct=dest.band_pct,
                label=f"índice {code}",
                comparison_label="cesta",
                alerts=alert_points,
            )
            seasonal = charts.seasonal_chart(
                [(i + 1, pct) for i, (_, pct) in enumerate(dest.seasonal_table())]
            )
            bases = calibration.effective_bases(connection)[code]
            quotes = db.destination_history(connection, code, limit=40)

            return render_template(
                "destination.html",
                dest=dest,
                verdict=verdict,
                basket=basket,
                chart=chart,
                seasonal=seasonal,
                bases=bases,
                alerts=alerts,
                quotes=list(reversed(quotes))[:20],
                points=len(series),
                distance=round(airports.distance_km(config.basket_origin, code)),
            )
        finally:
            connection.close()

    # ------------------------------------------------------------- viagem

    @app.route("/watch/<int:watch_id>")
    def watch_detail(watch_id: int):
        connection = conn()
        try:
            watch = db.get_watch(connection, watch_id)
            if watch is None:
                abort(404)
            basket = monitor.current_basket(connection)
            history = db.watch_history(connection, watch_id)
            quote = history[-1] if history else None
            verdict = _watch_verdict(quote, basket)

            comparison = [(s.collected_at, s.index_value) for s in db.snapshot_history(connection, 180)]
            chart = charts.index_history_chart(
                [(q.collected_at, q.index_value) for q in history if q.collected_at],
                comparison,
                band_pct=benchmarks.DESTINATIONS[watch.destination].band_pct
                if benchmarks.is_covered(watch.destination)
                else 12.0,
                label="índice da viagem",
                comparison_label="cesta",
            )
            return render_template(
                "watch.html",
                watch=watch,
                quote=quote,
                verdict=verdict,
                basket=basket,
                chart=chart,
                history=list(reversed(history))[:25],
                alerts=db.list_alerts(connection, limit=25, watch_id=watch_id),
                dest=benchmarks.get(watch.destination),
            )
        finally:
            connection.close()

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
                flash(f"Acompanhando {watch.display_name}.", "ok")
                if request.form.get("collect_now"):
                    try:
                        monitor.collect_watch(
                            connection, config, get_provider(config), watch,
                            monitor.current_basket(connection),
                            notifier=build_notifier(config),
                        )
                    except ProviderError as exc:
                        flash(f"Primeira cotação falhou: {exc}", "error")
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
            flash("Acompanhamento " + ("pausado." if watch.active else "retomado."), "ok")
        finally:
            connection.close()
        return redirect(request.referrer or url_for("index"))

    @app.route("/watch/<int:watch_id>/delete", methods=["POST"])
    def remove_watch(watch_id: int):
        connection = conn()
        try:
            db.delete_watch(connection, watch_id)
            flash("Viagem removida.", "ok")
        finally:
            connection.close()
        return redirect(url_for("index"))

    # ------------------------------------------------------------- ações

    @app.route("/collect", methods=["POST"])
    def collect():
        connection = conn()
        try:
            result = monitor.run_round(
                connection, config, get_provider(config), notifier=build_notifier(config)
            )
            flash(
                f"Rodada concluída: cesta em {result.basket.index:.0f} "
                f"({result.basket.size} destinos), {result.alert_count} alerta(s)."
                + (f" {len(result.errors)} falha(s)." if result.errors else ""),
                "ok" if not result.errors else "warn",
            )
            for error in result.errors[:5]:
                flash(error, "error")
        except ProviderError as exc:
            flash(f"Provedor indisponível: {exc}", "error")
        finally:
            connection.close()
        return redirect(request.referrer or url_for("index"))

    @app.route("/recalibrate", methods=["POST"])
    def recalibrate():
        connection = conn()
        try:
            proposals = calibration.propose_all(connection)
            applied = calibration.apply(connection, proposals)
            if applied:
                flash(
                    "Recalibrado: "
                    + ", ".join(f"{c.destination} {c.change_pct:+.0f}%" for c in applied),
                    "ok",
                )
            else:
                blocked = {c.blocked_reason for c in proposals if c.blocked_reason}
                flash(
                    "Nenhum destino tinha cotações suficientes para recalibrar. "
                    + (next(iter(blocked)) if len(blocked) == 1 else ""),
                    "warn",
                )
        finally:
            connection.close()
        return redirect(url_for("benchmarks_page"))

    @app.route("/benchmarks")
    def benchmarks_page():
        connection = conn()
        try:
            bases = calibration.effective_bases(connection)
            proposals = {c.destination: c for c in calibration.propose_all(connection)}
            return render_template(
                "benchmarks.html",
                table=benchmarks.describe_table(),
                bases=bases,
                proposals=proposals,
                advance_curve=benchmarks.ADVANCE_CURVE,
                month_names=benchmarks.MONTH_NAMES,
            )
        finally:
            connection.close()

    @app.route("/alerts")
    def alerts_page():
        connection = conn()
        try:
            watches = {w.id: w for w in db.list_watches(connection)}
            return render_template(
                "alerts.html", alerts=db.list_alerts(connection, limit=200), watches=watches
            )
        finally:
            connection.close()

    # --------------------------------------------------------------- API

    @app.route("/api/basket")
    def api_basket():
        connection = conn()
        try:
            basket = monitor.current_basket(connection)
            if basket is None:
                return jsonify({"error": "nenhuma rodada coletada ainda"}), 404
            payload = basket.as_dict()
            payload["summary"] = indexing.market_summary(basket)
            payload["verdicts"] = [v.as_dict() for v in indexing.evaluate_basket(basket)]
            return jsonify(payload)
        finally:
            connection.close()

    @app.route("/api/index")
    def api_index():
        connection = conn()
        try:
            limit = request.args.get("limit", default=180, type=int)
            return jsonify(
                {
                    "series": [
                        {
                            "collected_at": s.collected_at.isoformat() if s.collected_at else None,
                            "index": round(s.index_value, 2),
                            "dispersion": round(s.dispersion, 2),
                            "size": s.size,
                        }
                        for s in db.snapshot_history(connection, limit=limit)
                    ]
                }
            )
        finally:
            connection.close()

    @app.route("/api/destinations")
    def api_destinations():
        connection = conn()
        try:
            bases = calibration.effective_bases(connection)
            basket = monitor.current_basket(connection)
            verdicts = {v.destination: v for v in indexing.evaluate_basket(basket)} if basket else {}
            return jsonify(
                {
                    "destinations": [
                        {
                            **entry,
                            "base_in_use": bases[entry["iata"]]["base"],
                            "calibrated": bases[entry["iata"]]["calibrated"],
                            "verdict": (
                                verdicts[entry["iata"]].as_dict()
                                if entry["iata"] in verdicts
                                else None
                            ),
                        }
                        for entry in benchmarks.describe_table()
                    ]
                }
            )
        finally:
            connection.close()

    @app.route("/api/destinations/<code>/history")
    def api_destination_history(code: str):
        connection = conn()
        try:
            if not benchmarks.is_covered(code):
                return jsonify({"error": "destino fora da cesta"}), 404
            series = db.destination_index_series(connection, code, limit=365)
            return jsonify(
                {
                    "destination": code.upper(),
                    "series": [
                        {"collected_at": t.isoformat(), "index": round(v, 2)} for t, v in series
                    ],
                }
            )
        finally:
            connection.close()

    @app.route("/api/watches")
    def api_watches():
        connection = conn()
        try:
            basket = monitor.current_basket(connection)
            payload = []
            for watch in db.list_watches(connection):
                quote = db.latest_quote(connection, watch.id) if watch.id else None
                verdict = _watch_verdict(quote, basket)
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
                        "active": watch.active,
                        "latest_price": quote.price if quote else None,
                        "verdict": verdict.as_dict() if verdict else None,
                    }
                )
            return jsonify({"watches": payload})
        finally:
            connection.close()

    @app.route("/api/watches", methods=["POST"])
    def api_create_watch():
        try:
            watch = watch_from_form(request.get_json(silent=True) or {}, config)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        connection = conn()
        try:
            watch.id = db.insert_watch(connection, watch)
            return jsonify({"id": watch.id, "label": watch.display_name}), 201
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
                            "created_at": a.created_at.isoformat() if a.created_at else None,
                            "destination": a.destination,
                            "kind": a.kind,
                            "level": a.level,
                            "driver": a.driver,
                            "price": a.price,
                            "benchmark": a.benchmark,
                            "index": a.index_value,
                            "basket_index": a.basket_index,
                            "distortion": a.distortion,
                            "signal": a.signal,
                            "score": a.score,
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
        connection = conn()
        try:
            result = monitor.run_round(
                connection, config, get_provider(config), notifier=build_notifier(config)
            )
            return jsonify(
                {
                    "round_id": result.round_id,
                    "basket_index": round(result.basket.index, 2),
                    "size": result.basket.size,
                    "alerts": result.alert_count,
                    "errors": result.errors,
                    "verdicts": [v.as_dict() for v in result.verdicts],
                }
            )
        except ProviderError as exc:
            return jsonify({"error": str(exc)}), 502
        finally:
            connection.close()

    @app.route("/health")
    def health():
        return jsonify({"status": "ok", "provider": config.provider, "basket": list(benchmarks.BASKET)})

    return app


def _watch_verdict(quote: Optional[Quote], basket) -> Optional[Verdict]:
    """Recompõe o veredito de uma viagem a partir da cotação gravada."""
    if quote is None or not benchmarks.is_covered(quote.destination):
        return None
    reading = indexing.Reading(
        destination=quote.destination,
        price=quote.price,
        benchmark=quote.benchmark,
        index=quote.index_value,
        departure_date=quote.departure_date,
        return_date=quote.return_date,
        days_to_departure=quote.days_to_departure,
        currency=quote.currency,
        airline=quote.airline,
        stops=quote.stops,
        collected_at=quote.collected_at,
    )
    return indexing.evaluate(reading, basket)


def watch_from_form(form: Any, config: Config) -> Watch:
    """Valida e constrói uma viagem a partir do formulário web ou do JSON da API."""

    def value(key: str, default: str = "") -> str:
        raw = form.get(key, default)
        return str(raw).strip() if raw is not None else ""

    origin = value("origin", config.basket_origin).upper()[:3]
    destination = value("destination").upper()[:3]
    if len(origin) != 3:
        raise ValueError("Informe o código IATA de origem (3 letras).")
    if not benchmarks.is_covered(destination):
        raise ValueError(
            f"{destination or '(vazio)'} não está na cesta. "
            f"Destinos cobertos: {', '.join(sorted(benchmarks.BASKET))}."
        )

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

    raw_target = value("target_price")
    try:
        target = float(raw_target.replace(".", "").replace(",", ".")) if raw_target else None
    except ValueError:
        raise ValueError("Preço-alvo inválido.")

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
        currency=benchmarks.BENCHMARK_CURRENCY,
        max_stops=max_stops,
        target_price=target,
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

    def run(self) -> None:  # pragma: no cover
        interval = max(60, self.config.collect_interval_minutes * 60)
        self._stop.wait(10)
        while not self._stop.is_set():
            connection = None
            try:
                connection = db.connect(self.config.db_path)
                db.init_db(connection)
                result = monitor.run_round(
                    connection, self.config, get_provider(self.config),
                    notifier=build_notifier(self.config),
                )
                print(
                    f"[flightwatch] rodada automática: cesta {result.basket.index:.0f}, "
                    f"{result.alert_count} alerta(s) — {datetime.now():%d/%m %H:%M}",
                    flush=True,
                )
            except Exception as exc:
                print(f"[flightwatch] rodada automática falhou: {exc}", flush=True)
            finally:
                if connection is not None:
                    connection.close()
            self._stop.wait(interval + random.uniform(0, self.config.collect_jitter_seconds))
