"""Linha de comando do monitor."""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime, timedelta
from typing import List, Optional

from . import airports, analytics, charts, db, monitor, seed
from .config import Config
from .models import CABINS, Watch, parse_date
from .notifier import build_notifier, format_money
from .providers import ProviderError, available_providers, get_provider


def _config_from_args(args: argparse.Namespace) -> Config:
    config = Config.from_env()
    if getattr(args, "db", None):
        config.db_path = args.db
    if getattr(args, "provider", None):
        config.provider = args.provider
    if getattr(args, "currency", None):
        config.currency = args.currency.upper()
    if getattr(args, "quiet", False):
        config.notify_console = False
    return config


def _print_result(result: monitor.WatchResult) -> None:
    watch = result.watch
    if not result.ok:
        print(f"  ✗ {watch.display_name}: {result.error}")
        return
    assessment = result.assessment
    price = format_money(result.best.price, watch.currency)
    if assessment is None or assessment.method == "insufficient":
        print(f"  · {watch.display_name}: {price} (histórico em formação)")
        return
    expected = format_money(assessment.expected_price * max(1, watch.passengers), watch.currency)
    flag = "★" if assessment.is_deal else "·"
    print(
        f"  {flag} {watch.display_name}: {price} · padrão {expected} · "
        f"{assessment.delta_label} (z={assessment.z_score:+.2f}) "
        f"→ {assessment.severity_label}"
    )


# --------------------------------------------------------------- comandos


def cmd_init(args: argparse.Namespace) -> int:
    config = _config_from_args(args)
    with db.session(config.db_path) as conn:
        stats = db.observation_stats(conn)
    print(f"Banco pronto em {config.db_path} ({stats['observations']} cotações).")
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    config = _config_from_args(args)
    departure = parse_date(args.departure)
    return_date = parse_date(args.ret) if args.ret else None
    trip_type = "oneway" if args.oneway else "round"
    if trip_type == "round" and return_date is None:
        print("Erro: informe --return para viagens de ida e volta (ou use --oneway).", file=sys.stderr)
        return 2
    if departure is None or departure < date.today():
        print("Erro: a data de ida precisa ser futura.", file=sys.stderr)
        return 2

    watch = Watch(
        label=args.label or "",
        origin=args.origin.upper(),
        destination=args.destination.upper(),
        departure_date=departure,
        return_date=return_date,
        flex_days=args.flex,
        trip_type=trip_type,
        cabin=args.cabin.upper(),
        passengers=args.passengers,
        currency=(args.currency or config.currency).upper(),
        max_stops=args.max_stops,
        target_price=args.target,
        active=True,
        created_at=datetime.now(),
    )
    with db.session(config.db_path) as conn:
        watch.id = db.insert_watch(conn, watch)
        print(f"#{watch.id} {watch.display_name}: {airports.label(watch.origin)} → {airports.label(watch.destination)}")
        if args.backfill:
            provider = get_provider(config)
            print(f"Reconstruindo {args.backfill} dias de histórico da rota...")
            count = seed.backfill_watch(conn, provider, watch, days_back=args.backfill)
            print(f"  {count} cotações históricas gravadas.")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    config = _config_from_args(args)
    with db.session(config.db_path) as conn:
        watches = db.list_watches(conn)
        if not watches:
            print("Nenhuma rota monitorada. Use 'add' ou 'seed-demo'.")
            return 0
        for watch in watches:
            snapshot = monitor.watch_snapshot(conn, watch)
            latest, assessment = snapshot["latest"], snapshot["assessment"]
            status = "ativa " if watch.active else "pausada"
            line = (
                f"#{watch.id:<3} {status} {watch.origin}→{watch.destination} "
                f"{watch.departure_date}"
            )
            if latest:
                line += f"  {format_money(latest.price, watch.currency)}"
            if assessment and assessment.method != "insufficient":
                line += f"  ({assessment.delta_label}, {assessment.severity_label})"
            elif latest:
                line += "  (histórico em formação)"
            print(line + f"  [{snapshot['n_samples']} cotações]")
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    config = _config_from_args(args)
    with db.session(config.db_path) as conn:
        db.delete_watch(conn, args.watch_id)
    print(f"Rota #{args.watch_id} removida.")
    return 0


def cmd_collect(args: argparse.Namespace) -> int:
    config = _config_from_args(args)
    with db.session(config.db_path) as conn:
        try:
            provider = get_provider(config)
        except ProviderError as exc:
            print(f"Erro: {exc}", file=sys.stderr)
            return 1
        notifier = None if args.no_notify else build_notifier(config)
        print(f"Coletando com o provedor '{provider.name}'...")
        results = monitor.run_collection(
            conn, config, provider, watch_ids=args.watch_ids or None, notifier=notifier
        )
        if not results:
            print("Nenhuma rota ativa para coletar.")
            return 0
        for result in results:
            _print_result(result)
        deals = sum(1 for r in results if r.alert)
        failed = sum(1 for r in results if not r.ok)
        print(f"\n{len(results)} rota(s) · {deals} alerta(s) · {failed} falha(s).")
    return 0


def cmd_watch_loop(args: argparse.Namespace) -> int:
    """Coleta em intervalo fixo, para rodar como serviço."""
    config = _config_from_args(args)
    interval = max(60, (args.interval or config.collect_interval_minutes) * 60)
    print(f"Monitorando a cada {interval // 60} min. Ctrl+C para sair.")
    while True:
        started = datetime.now()
        try:
            with db.session(config.db_path) as conn:
                provider = get_provider(config)
                results = monitor.run_collection(
                    conn, config, provider, notifier=build_notifier(config)
                )
                alerts = sum(1 for r in results if r.alert)
                print(f"[{started:%d/%m %H:%M}] {len(results)} rota(s), {alerts} alerta(s).")
        except KeyboardInterrupt:
            print("\nEncerrado.")
            return 0
        except Exception as exc:
            print(f"[{started:%d/%m %H:%M}] falha na coleta: {exc}", file=sys.stderr)
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            print("\nEncerrado.")
            return 0


def cmd_backfill(args: argparse.Namespace) -> int:
    config = _config_from_args(args)
    with db.session(config.db_path) as conn:
        try:
            provider = get_provider(config)
        except ProviderError as exc:
            print(f"Erro: {exc}", file=sys.stderr)
            return 1

        if args.watch_id:
            watch = db.get_watch(conn, args.watch_id)
            if watch is None:
                print(f"Rota #{args.watch_id} não encontrada.", file=sys.stderr)
                return 2
            targets = [watch]
        else:
            targets = db.list_watches(conn)

        total = 0
        for watch in targets:
            try:
                count = seed.backfill_watch(
                    conn, provider, watch, days_back=args.days, step_days=args.step
                )
            except ProviderError as exc:
                print(f"  ✗ {watch.display_name}: {exc}")
                continue
            total += count
            print(f"  {watch.display_name}: {count} cotações históricas.")
        print(f"{total} cotações gravadas.")
    return 0


def cmd_bootstrap(args: argparse.Namespace) -> int:
    """Semeia o histórico com os quartis publicados pelo provedor real."""
    config = _config_from_args(args)
    with db.session(config.db_path) as conn:
        provider = get_provider(config)
        total = 0
        for watch in db.list_watches(conn):
            count = seed.bootstrap_from_metrics(conn, provider, watch)
            total += count
            print(f"  {watch.display_name}: {count} referências de mercado.")
        print(f"{total} referências gravadas.")
    return 0


def cmd_seed_demo(args: argparse.Namespace) -> int:
    config = _config_from_args(args)
    config.provider = "synthetic"
    with db.session(config.db_path) as conn:
        if db.list_watches(conn) and not args.force:
            print("Já existem rotas cadastradas. Use --force para adicionar a carteira demo.")
            return 1
        print("Montando carteira de demonstração com histórico reconstruído:")
        summary = seed.seed_demo(conn, config, get_provider(config), days_back=args.days)
        print(f"\n{summary['watches']} rotas e {summary['observations']} cotações históricas.")
        print("Rodando a primeira coleta...")
        results = monitor.run_collection(
            conn, config, get_provider(config), notifier=build_notifier(config)
        )
        for result in results:
            _print_result(result)
    print("\nPronto. Suba o painel com:  python run.py serve")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    """Relatório de uma rota: padrão, sazonalidade e melhor janela de compra."""
    config = _config_from_args(args)
    with db.session(config.db_path) as conn:
        watch = db.get_watch(conn, args.watch_id)
        if watch is None:
            print(f"Rota #{args.watch_id} não encontrada.", file=sys.stderr)
            return 2
        snapshot = monitor.watch_snapshot(conn, watch)
        model: analytics.RouteModel = snapshot["model"]
        assessment = snapshot["assessment"]

        print(f"\n{watch.display_name}")
        print(f"{airports.label(watch.origin)} → {airports.label(watch.destination)}")
        print(f"Ida {watch.departure_date}" + (f" · volta {watch.return_date}" if watch.return_date else ""))
        print("-" * 68)
        print(f"Cotações no histórico da rota : {model.n}")
        if not model.fitted:
            print("Histórico insuficiente para estimar o preço padrão.")
            return 0
        print(f"Preço base da rota            : {format_money(model.base_price, watch.currency)}")
        print(f"Volatilidade típica           : ±{model.residual_scale * 100:.0f}%")
        print(f"Semanas do ano cobertas       : {model.weeks_covered}/52")
        print(f"Confiança                     : {model.confidence()}")

        if assessment:
            print("\nÚltima cotação")
            print(f"  preço   : {format_money(assessment.price * max(1, watch.passengers), watch.currency)}")
            print(f"  padrão  : {format_money(assessment.expected_price * max(1, watch.passengers), watch.currency)}")
            print(f"  desvio  : {assessment.delta_label} (z = {assessment.z_score:+.2f})")
            print(f"  veredito: {assessment.severity_label}")
            for reason in assessment.reasons:
                print(f"    • {reason}")

        year = (watch.departure_date or date.today()).year
        print("\nSazonalidade por mês de viagem (vs média anual da rota)")
        for month, pct in model.monthly_curve(year):
            bar_len = int(abs(pct) / 2)
            bar = ("+" if pct >= 0 else "-") * min(30, bar_len)
            print(f"  {charts.MONTH_ABBR[month - 1]}  {pct:+6.1f}%  {bar}")

        print("\nCurva de antecedência (vs média da rota)")
        for label, pct in model.advance_curve():
            if label not in model.advance:
                continue
            bar_len = int(abs(pct) / 2)
            bar = ("+" if pct >= 0 else "-") * min(30, bar_len)
            print(f"  {label:>8}d  {pct:+6.1f}%  {bar}")
    return 0


def cmd_alerts(args: argparse.Namespace) -> int:
    config = _config_from_args(args)
    with db.session(config.db_path) as conn:
        rows = db.list_alerts(conn, limit=args.limit)
        if args.json:
            print(json.dumps(
                [
                    {
                        "id": a.id, "watch_id": a.watch_id,
                        "created_at": a.created_at.isoformat() if a.created_at else None,
                        "verdict": a.verdict, "severity": a.severity, "price": a.price,
                        "expected_price": a.expected_price, "discount_pct": a.discount_pct,
                        "z_score": a.z_score, "deal_score": a.deal_score, "message": a.message,
                    }
                    for a in rows
                ],
                ensure_ascii=False, indent=2,
            ))
            return 0
        if not rows:
            print("Nenhum alerta registrado.")
            return 0
        for alert in rows:
            when = alert.created_at.strftime("%d/%m %H:%M") if alert.created_at else "?"
            print(f"[{when}] {alert.message}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .web import CollectorThread, create_app

    config = _config_from_args(args)
    if args.port:
        config.port = args.port
    app = create_app(config)

    collector = None
    if args.with_scheduler:
        collector = CollectorThread(config)
        collector.start()
        print(f"Coletor automático ativo a cada {config.collect_interval_minutes} min.")

    print(f"Painel em http://{config.host}:{config.port}  (provedor: {config.provider})")
    try:
        app.run(host=config.host, port=config.port, debug=args.debug, use_reloader=False)
    finally:
        if collector:
            collector.stop()
    return 0


def cmd_purge(args: argparse.Namespace) -> int:
    config = _config_from_args(args)
    with db.session(config.db_path) as conn:
        removed = db.purge_old_observations(conn, args.keep_days)
    print(f"{removed} cotações com mais de {args.keep_days} dias removidas.")
    return 0


# ----------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flightwatch",
        description="Monitor de passagens aéreas: alerta quando o preço cai abaixo do "
                    "padrão histórico da rota para aquele período do ano.",
    )
    parser.add_argument("--db", help="caminho do banco SQLite")
    parser.add_argument("--provider", choices=available_providers(), help="fonte de cotação")
    parser.add_argument("--currency", help="moeda (padrão: BRL)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="cria o banco de dados")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("add", help="passa a monitorar uma rota")
    p.add_argument("origin", help="IATA de origem, ex.: GRU")
    p.add_argument("destination", help="IATA de destino, ex.: LIS")
    p.add_argument("departure", help="data de ida (AAAA-MM-DD)")
    p.add_argument("--return", dest="ret", help="data de volta (AAAA-MM-DD)")
    p.add_argument("--oneway", action="store_true", help="somente ida")
    p.add_argument("--cabin", default="ECONOMY", choices=[c for c in CABINS])
    p.add_argument("--passengers", type=int, default=1)
    p.add_argument("--flex", type=int, default=0, help="cotar também ± N dias")
    p.add_argument("--max-stops", type=int, dest="max_stops")
    p.add_argument("--target", type=float, help="preço-alvo que sempre gera alerta")
    p.add_argument("--label", help="apelido da rota")
    p.add_argument("--backfill", type=int, metavar="DIAS",
                   help="reconstruir N dias de histórico (provedor synthetic)")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("list", help="lista as rotas monitoradas")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("remove", help="remove uma rota")
    p.add_argument("watch_id", type=int)
    p.set_defaults(func=cmd_remove)

    p = sub.add_parser("collect", help="faz uma rodada de cotação")
    p.add_argument("watch_ids", nargs="*", type=int, help="IDs específicos (padrão: todas)")
    p.add_argument("--no-notify", action="store_true", help="não dispara notificações")
    p.add_argument("--quiet", action="store_true", help="sem saída no console")
    p.set_defaults(func=cmd_collect)

    p = sub.add_parser("run", help="coleta continuamente em intervalo fixo")
    p.add_argument("--interval", type=int, metavar="MIN", help="minutos entre coletas")
    p.set_defaults(func=cmd_watch_loop)

    p = sub.add_parser("backfill", help="reconstrói histórico das rotas (provedor synthetic)")
    p.add_argument("watch_id", nargs="?", type=int)
    p.add_argument("--days", type=int, default=420, help="quantos dias para trás")
    p.add_argument("--step", type=int, default=6, help="intervalo entre datas de consulta")
    p.set_defaults(func=cmd_backfill)

    p = sub.add_parser("bootstrap", help="semeia referências de mercado do provedor real")
    p.set_defaults(func=cmd_bootstrap)

    p = sub.add_parser("seed-demo", help="carteira de demonstração com histórico pronto")
    p.add_argument("--days", type=int, default=420)
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_seed_demo)

    p = sub.add_parser("report", help="relatório de padrão e sazonalidade de uma rota")
    p.add_argument("watch_id", type=int)
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("alerts", help="lista os alertas registrados")
    p.add_argument("--limit", type=int, default=30)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_alerts)

    p = sub.add_parser("serve", help="sobe o painel web")
    p.add_argument("--port", type=int)
    p.add_argument("--debug", action="store_true")
    p.add_argument("--with-scheduler", action="store_true",
                   help="coleta periódica em segundo plano dentro do servidor")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("purge", help="descarta cotações antigas")
    p.add_argument("--keep-days", type=int, default=900)
    p.set_defaults(func=cmd_purge)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        print("\nInterrompido.")
        return 130
    except ProviderError as exc:
        print(f"Erro do provedor: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
