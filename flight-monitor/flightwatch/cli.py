"""Linha de comando do monitor."""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime, timedelta
from typing import List, Optional

from . import airports, benchmarks, calibration, db, indexing, monitor
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
    if getattr(args, "quiet", False):
        config.notify_console = False
    return config


def _print_round(result: monitor.RoundResult) -> None:
    summary = indexing.market_summary(result.basket)
    print(
        f"\nÍndice de mercado: {result.basket.index:.1f} ({summary['state']}) · "
        f"{result.basket.size} destinos · dispersão {result.basket.dispersion:.1f}"
    )
    print(f"{'dest':5} {'preço':>10} {'benchmark':>11} {'índice':>7} {'vs cesta':>9}  veredito")
    print("-" * 74)
    for verdict in sorted(result.verdicts, key=lambda v: v.index):
        distortion = f"{verdict.distortion:+.0f}" if verdict.distortion is not None else "—"
        mark = "★" if verdict.is_alert else " "
        print(
            f"{verdict.destination:5} {verdict.price:>10,.0f} {verdict.benchmark:>11,.0f} "
            f"{verdict.index:>7.0f} {distortion:>9} {mark} {verdict.label}"
        )
    for watch_result in result.watch_results:
        watch = watch_result.watch
        if not watch_result.ok:
            print(f"\n  ✗ {watch.display_name}: {watch_result.error}")
            continue
        verdict = watch_result.verdict
        mark = "★" if verdict.is_alert else "·"
        print(
            f"\n  {mark} {watch.display_name}: "
            f"{format_money(verdict.price, verdict.currency)} · índice {verdict.index:.0f} · "
            f"{verdict.label}"
        )
    if result.errors:
        print(f"\n{len(result.errors)} falha(s):")
        for error in result.errors[:10]:
            print(f"  ✗ {error}")


# --------------------------------------------------------------- comandos


def cmd_init(args: argparse.Namespace) -> int:
    config = _config_from_args(args)
    with db.session(config.db_path) as conn:
        stats = db.quote_stats(conn)
    print(f"Banco pronto em {config.db_path} ({stats['rounds']} rodadas, {stats['quotes']} cotações).")
    print(f"Cesta: {', '.join(benchmarks.BASKET)}")
    return 0


def cmd_measure(args: argparse.Namespace) -> int:
    """Mede a cesta: a operação central do app."""
    config = _config_from_args(args)
    with db.session(config.db_path) as conn:
        try:
            provider = get_provider(config)
        except ProviderError as exc:
            print(f"Erro: {exc}", file=sys.stderr)
            return 1
        spec = monitor.ProbeSpec.from_config(config)
        print(f"Medindo com o provedor '{provider.name}'.")
        print(f"Metodologia: {spec.describe()}")
        result = monitor.run_round(
            conn, config, provider,
            notifier=None if args.no_notify else build_notifier(config),
            include_watches=not args.skip_watches,
        )
        _print_round(result)
        print(f"\nRodada {result.round_id} · {result.alert_count} alerta(s).")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    config = _config_from_args(args)
    interval = max(60, (args.interval or config.collect_interval_minutes) * 60)
    print(f"Medindo a cesta a cada {interval // 60} min. Ctrl+C para sair.")
    while True:
        started = datetime.now()
        try:
            with db.session(config.db_path) as conn:
                result = monitor.run_round(
                    conn, config, get_provider(config), notifier=build_notifier(config)
                )
                print(
                    f"[{started:%d/%m %H:%M}] cesta {result.basket.index:.1f} · "
                    f"{result.alert_count} alerta(s)"
                )
        except KeyboardInterrupt:
            print("\nEncerrado.")
            return 0
        except Exception as exc:
            print(f"[{started:%d/%m %H:%M}] rodada falhou: {exc}", file=sys.stderr)
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            print("\nEncerrado.")
            return 0


def cmd_basket(args: argparse.Namespace) -> int:
    """Mostra a última medição sem cotar nada."""
    config = _config_from_args(args)
    with db.session(config.db_path) as conn:
        basket = monitor.current_basket(conn)
        if basket is None:
            print("Nenhuma rodada medida ainda. Rode 'measure'.")
            return 0
        snapshot = db.latest_snapshot(conn)
        summary = indexing.market_summary(basket)
        print(f"Medido em {snapshot.collected_at:%d/%m/%Y %H:%M}")
        print(f"Índice de mercado: {basket.index:.1f} — {summary['state']}")
        print(f"{summary['detail']}\n")
        print(f"{'dest':5} {'preço':>10} {'benchmark':>11} {'índice':>7} {'vs cesta':>9}  veredito")
        print("-" * 74)
        for verdict in sorted(indexing.evaluate_basket(basket), key=lambda v: v.index):
            distortion = f"{verdict.distortion:+.0f}" if verdict.distortion is not None else "—"
            mark = "★" if verdict.is_alert else " "
            print(
                f"{verdict.destination:5} {verdict.price:>10,.0f} {verdict.benchmark:>11,.0f} "
                f"{verdict.index:>7.0f} {distortion:>9} {mark} {verdict.label}"
            )
    return 0


def cmd_destination(args: argparse.Namespace) -> int:
    """Detalha um destino: benchmark, sazonalidade e leitura atual."""
    config = _config_from_args(args)
    code = args.code.upper()
    dest = benchmarks.get(code)
    if dest is None:
        print(f"{code} não está na cesta. Destinos: {', '.join(benchmarks.BASKET)}", file=sys.stderr)
        return 2

    with db.session(config.db_path) as conn:
        bases = calibration.effective_bases(conn)[code]
        basket = monitor.current_basket(conn)

        print(f"\n{dest.city} ({code}) · {dest.country} · {dest.region}")
        print(f"{dest.note}")
        print("-" * 70)
        print(f"Preço-base da tabela : {format_money(bases['table_base'])}")
        print(f"Preço-base em uso    : {format_money(bases['base'])}"
              + (f"  (recalibrado {bases['change_pct']:+.1f}%)" if bases["calibrated"] else ""))
        print(f"Banda normal         : ±{dest.band_pct:.0f} pontos")
        print(f"Meses mais baratos   : {', '.join(dest.cheapest_months)}")
        print(f"Distância de {config.basket_origin}     : {airports.distance_km(config.basket_origin, code):,.0f} km")

        print("\nSazonalidade (fator sobre a média anual)")
        for name, pct in dest.seasonal_table():
            bar = ("+" if pct >= 0 else "-") * min(28, int(abs(pct)))
            print(f"  {name}  {pct:+6.1f}%  {bar}")

        if basket:
            for verdict in indexing.evaluate_basket(basket):
                if verdict.destination != code:
                    continue
                print("\nÚltima leitura")
                print(f"  preço     : {format_money(verdict.price, verdict.currency)}")
                print(f"  benchmark : {format_money(verdict.benchmark, verdict.currency)}")
                print(f"  índice    : {verdict.index:.0f} ({verdict.gap_label})")
                if verdict.distortion is not None:
                    print(f"  cesta     : {verdict.basket_index:.0f} "
                          f"(distorção {verdict.distortion:+.0f} pontos)")
                print(f"  veredito  : {verdict.label} — {verdict.driver_label}")
                for reason in verdict.reasons:
                    print(f"    • {reason}")
    return 0


def cmd_table(args: argparse.Namespace) -> int:
    """Imprime a tabela de benchmark inteira, para auditoria."""
    config = _config_from_args(args)
    with db.session(config.db_path) as conn:
        bases = calibration.effective_bases(conn)
    print(f"{'dest':5} {'cidade':16} {'região':18} {'base':>10} {'em uso':>10} {'banda':>6}  meses baratos")
    print("-" * 92)
    for row in benchmarks.describe_table():
        info = bases[row["iata"]]
        flag = "*" if info["calibrated"] else " "
        print(
            f"{row['iata']:5} {row['city'][:16]:16} {row['region'][:18]:18} "
            f"{row['base_price']:>10,.0f} {info['base']:>9,.0f}{flag} "
            f"±{row['band_pct']:>4.0f}  {', '.join(row['cheapest_months'])}"
        )
    print("\n* preço-base recalibrado a partir das cotações coletadas.")
    return 0


def cmd_recalibrate(args: argparse.Namespace) -> int:
    config = _config_from_args(args)
    with db.session(config.db_path) as conn:
        proposals = calibration.propose_all(conn, since_days=args.days)
        print(f"{'dest':5} {'base atual':>11} {'observada':>11} {'proposta':>10} {'mudança':>9}  situação")
        print("-" * 78)
        for proposal in proposals:
            status = proposal.blocked_reason or (
                f"{proposal.n_quotes} cotações em {proposal.n_months} meses"
            )
            print(
                f"{proposal.destination:5} {proposal.current_base:>11,.0f} "
                f"{proposal.observed_base:>11,.0f} {proposal.proposed_base:>10,.0f} "
                f"{proposal.change_pct:>+8.1f}%  {status}"
            )
        if args.dry_run:
            viable = sum(1 for p in proposals if p.is_actionable)
            print(f"\nSimulação: {viable} destino(s) seriam recalibrados. Rode sem --dry-run para aplicar.")
            return 0
        applied = calibration.apply(conn, proposals)
        print(f"\n{len(applied)} destino(s) recalibrado(s).")
    return 0


def cmd_reset_calibration(args: argparse.Namespace) -> int:
    config = _config_from_args(args)
    with db.session(config.db_path) as conn:
        removed = db.clear_base_overrides(conn)
    print(f"{removed} recalibração(ões) descartada(s); a tabela do código volta a valer.")
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    config = _config_from_args(args)
    destination = args.destination.upper()
    if not benchmarks.is_covered(destination):
        print(
            f"{destination} não está na cesta. Destinos: {', '.join(benchmarks.BASKET)}.\n"
            "Para acrescentar um destino, some uma entrada em flightwatch/benchmarks.py.",
            file=sys.stderr,
        )
        return 2

    departure = parse_date(args.departure)
    return_date = parse_date(args.ret) if args.ret else None
    trip_type = "oneway" if args.oneway else "round"
    if trip_type == "round" and return_date is None:
        print("Erro: informe --return para ida e volta (ou use --oneway).", file=sys.stderr)
        return 2
    if departure is None or departure < date.today():
        print("Erro: a data de ida precisa ser futura.", file=sys.stderr)
        return 2

    watch = Watch(
        label=args.label or "",
        origin=(args.origin or config.basket_origin).upper(),
        destination=destination,
        departure_date=departure,
        return_date=return_date,
        flex_days=args.flex,
        trip_type=trip_type,
        cabin=args.cabin.upper(),
        passengers=args.passengers,
        currency=benchmarks.BENCHMARK_CURRENCY,
        max_stops=args.max_stops,
        target_price=args.target,
        active=True,
        created_at=datetime.now(),
    )
    with db.session(config.db_path) as conn:
        watch.id = db.insert_watch(conn, watch)
        breakdown = benchmarks.benchmark(
            destination, departure, watch.days_to_departure(),
            origin=watch.origin, cabin=watch.cabin, passengers=watch.passengers,
        )
        print(f"#{watch.id} {watch.display_name}: {airports.label(watch.origin)} → {airports.label(destination)}")
        print(f"Benchmark para esta data e antecedência: {format_money(breakdown.price)}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    config = _config_from_args(args)
    with db.session(config.db_path) as conn:
        watches = db.list_watches(conn)
        if not watches:
            print("Nenhuma viagem acompanhada. Use 'add'.")
            return 0
        basket = monitor.current_basket(conn)
        from .web import _watch_verdict

        for watch in watches:
            quote = db.latest_quote(conn, watch.id)
            verdict = _watch_verdict(quote, basket)
            status = "ativa " if watch.active else "pausada"
            line = f"#{watch.id:<3} {status} {watch.origin}→{watch.destination} {watch.departure_date}"
            if quote:
                line += f"  {format_money(quote.price, quote.currency)}  índice {quote.index_value:.0f}"
            if verdict:
                line += f"  ({verdict.label})"
            print(line)
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    config = _config_from_args(args)
    with db.session(config.db_path) as conn:
        db.delete_watch(conn, args.watch_id)
    print(f"Viagem #{args.watch_id} removida.")
    return 0


def cmd_alerts(args: argparse.Namespace) -> int:
    config = _config_from_args(args)
    with db.session(config.db_path) as conn:
        rows = db.list_alerts(conn, limit=args.limit)
        if args.json:
            print(json.dumps(
                [
                    {
                        "id": a.id, "created_at": a.created_at.isoformat() if a.created_at else None,
                        "destination": a.destination, "level": a.level, "driver": a.driver,
                        "price": a.price, "benchmark": a.benchmark, "index": a.index_value,
                        "basket_index": a.basket_index, "distortion": a.distortion,
                        "signal": a.signal, "score": a.score, "message": a.message,
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


def cmd_doctor(args: argparse.Namespace) -> int:
    """Verifica se o app está pronto para medir de verdade."""
    config = _config_from_args(args)
    problems = 0

    print(f"Provedor configurado : {config.provider}")
    print(f"Banco                : {config.db_path}")
    print(f"Moeda do benchmark   : {benchmarks.BENCHMARK_CURRENCY}")
    print(f"Cesta                : {len(benchmarks.BASKET)} destinos — {', '.join(benchmarks.BASKET)}")
    print(f"Metodologia          : {monitor.ProbeSpec.from_config(config).describe()}")

    calls = len(benchmarks.BASKET) * len(config.probe_horizons)
    per_month = calls * (24 * 60 / max(1, config.collect_interval_minutes)) * 30
    print(
        f"Consumo estimado     : {calls} chamadas por rodada · "
        f"~{per_month:,.0f}/mês no intervalo de {config.collect_interval_minutes} min"
        .replace(",", ".")
    )

    print("\nProvedor:")
    try:
        provider = get_provider(config)
        print(f"  ✓ '{provider.name}' instanciado")
    except ProviderError as exc:
        print(f"  ✗ {exc}")
        return 1

    from .providers import SearchQuery

    probe = SearchQuery(
        origin=config.basket_origin,
        destination=benchmarks.BASKET[0],
        departure_date=date.today() + timedelta(days=60),
        return_date=date.today() + timedelta(days=70),
        currency=benchmarks.BENCHMARK_CURRENCY,
        max_offers=3,
        as_of=date.today(),
    )
    try:
        offer = provider.cheapest(probe)
        if offer is None:
            print("  ✗ consulta de teste não retornou ofertas")
            problems += 1
        else:
            print(f"  ✓ consulta de teste: {config.basket_origin}→{probe.destination} "
                  f"= {format_money(offer.price, offer.currency)}")
    except ProviderError as exc:
        print(f"  ✗ consulta de teste falhou: {exc}")
        problems += 1

    if config.provider == "synthetic":
        print("\n  ⚠ O provedor 'synthetic' simula preços. Para decidir compra, configure a Amadeus:")
        print("    export FLIGHTWATCH_PROVIDER=amadeus")
        print("    export AMADEUS_CLIENT_ID=...  AMADEUS_CLIENT_SECRET=...")

    print("\nNotificações:")
    print(f"  console: {'on' if config.notify_console else 'off'}")
    print(f"  arquivo: {config.notify_file or 'off'}")
    print(f"  webhook: {'configurado' if config.webhook_url else 'off'}")

    with db.session(config.db_path) as conn:
        stats = db.quote_stats(conn)
        overrides = db.list_base_overrides(conn)
    print(f"\nBanco: {stats['rounds']} rodadas, {stats['quotes']} cotações, "
          f"{len(overrides)} destino(s) recalibrado(s)")

    print("\n" + ("Tudo pronto." if problems == 0 else f"{problems} problema(s) encontrado(s)."))
    return 1 if problems else 0


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
        print(f"Medição automática a cada {config.collect_interval_minutes} min.")

    print(f"Painel em http://{config.host}:{config.port}  (provedor: {config.provider})")
    try:
        app.run(host=config.host, port=config.port, debug=args.debug, use_reloader=False)
    finally:
        if collector:
            collector.stop()
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    """Simula várias rodadas para o painel nascer com série e distorções."""
    config = _config_from_args(args)
    config.provider = "synthetic"
    with db.session(config.db_path) as conn:
        if db.latest_snapshot(conn) and not args.force:
            print("Já existem medições. Use --force para somar a carteira de demonstração.")
            return 1

        provider = get_provider(config)
        now = datetime.now()
        print(f"Simulando {args.rounds} rodadas diárias...")
        for i in range(args.rounds, 0, -1):
            monitor.run_round(
                conn, config, provider,
                now=now - timedelta(days=i),
                include_watches=False,
            )

        if not db.list_watches(conn):
            for label, code, days, nights in (
                ("Férias em Lisboa", "LIS", 120, 14),
                ("Nova York no fim do ano", "JFK", 95, 8),
                ("Tóquio nas cerejeiras", "HND", 175, 12),
            ):
                departure = date.today() + timedelta(days=days)
                watch = Watch(
                    label=label, origin=config.basket_origin, destination=code,
                    departure_date=departure, return_date=departure + timedelta(days=nights),
                    trip_type="round", cabin="ECONOMY", passengers=1,
                    currency=benchmarks.BENCHMARK_CURRENCY, active=True, created_at=datetime.now(),
                )
                db.insert_watch(conn, watch)

        result = monitor.run_round(conn, config, provider, notifier=build_notifier(config))
        _print_round(result)
    print("\nPronto. Suba o painel com:  python run.py serve")
    return 0


def cmd_purge(args: argparse.Namespace) -> int:
    config = _config_from_args(args)
    with db.session(config.db_path) as conn:
        removed = db.purge_old_quotes(conn, args.keep_days)
    print(f"{removed} cotações com mais de {args.keep_days} dias removidas.")
    return 0


# ----------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flightwatch",
        description="Índice de passagens: mede 10 destinos contra benchmarks estabelecidos "
                    "e alerta quando um deles se distorce em relação à cesta.",
    )
    parser.add_argument("--db", help="caminho do banco SQLite")
    parser.add_argument("--provider", choices=available_providers(), help="fonte de cotação")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="cria o banco de dados")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("measure", help="mede a cesta e avalia distorções")
    p.add_argument("--no-notify", action="store_true")
    p.add_argument("--skip-watches", action="store_true", help="medir só a cesta")
    p.add_argument("--quiet", action="store_true")
    p.set_defaults(func=cmd_measure)

    p = sub.add_parser("run", help="mede continuamente em intervalo fixo")
    p.add_argument("--interval", type=int, metavar="MIN")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("basket", help="mostra a última medição da cesta")
    p.set_defaults(func=cmd_basket)

    p = sub.add_parser("destination", help="detalha um destino da cesta")
    p.add_argument("code")
    p.set_defaults(func=cmd_destination)

    p = sub.add_parser("table", help="imprime a tabela de benchmark")
    p.set_defaults(func=cmd_table)

    p = sub.add_parser("recalibrate", help="reajusta os preços-base com as cotações coletadas")
    p.add_argument("--days", type=int, default=180, help="janela de cotações considerada")
    p.add_argument("--dry-run", action="store_true", help="apenas simula")
    p.set_defaults(func=cmd_recalibrate)

    p = sub.add_parser("reset-calibration", help="volta aos preços-base da tabela")
    p.set_defaults(func=cmd_reset_calibration)

    p = sub.add_parser("add", help="acompanha uma viagem específica")
    p.add_argument("destination", help="IATA de um destino da cesta")
    p.add_argument("departure", help="data de ida (AAAA-MM-DD)")
    p.add_argument("--return", dest="ret", help="data de volta (AAAA-MM-DD)")
    p.add_argument("--oneway", action="store_true")
    p.add_argument("--origin", help="IATA de origem (padrão: o da cesta)")
    p.add_argument("--cabin", default="ECONOMY", choices=list(CABINS))
    p.add_argument("--passengers", type=int, default=1)
    p.add_argument("--flex", type=int, default=0, help="cotar também ± N dias")
    p.add_argument("--max-stops", type=int, dest="max_stops")
    p.add_argument("--target", type=float, help="preço-alvo que sempre gera alerta")
    p.add_argument("--label", help="apelido da viagem")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("list", help="lista as viagens acompanhadas")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("remove", help="remove uma viagem")
    p.add_argument("watch_id", type=int)
    p.set_defaults(func=cmd_remove)

    p = sub.add_parser("alerts", help="lista os alertas registrados")
    p.add_argument("--limit", type=int, default=30)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_alerts)

    p = sub.add_parser("doctor", help="verifica credenciais, cota de API e configuração")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("serve", help="sobe o painel web")
    p.add_argument("--port", type=int)
    p.add_argument("--debug", action="store_true")
    p.add_argument("--with-scheduler", action="store_true")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("demo", help="simula rodadas para conhecer o app")
    p.add_argument("--rounds", type=int, default=40)
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("purge", help="descarta cotações antigas")
    p.add_argument("--keep-days", type=int, default=900)
    p.set_defaults(func=cmd_purge)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
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
