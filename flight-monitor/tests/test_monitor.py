"""Testes da rodada de coleta, da sondagem e dos alertas."""
from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta

from helpers import make_watch, memory_db, quiet_provider, test_config

from flightwatch import benchmarks, calibration, db, indexing, monitor
from flightwatch.models import KIND_BASKET, KIND_WATCH
from flightwatch.notifier import Notifier
from flightwatch.providers import Offer, Provider, ProviderError, SearchQuery


class FakeProvider(Provider):
    """Devolve o preço que o teste mandar, por destino."""

    name = "fake"
    supports_backfill = False

    def __init__(self, index_by_destination=None, default_index=100.0):
        self.index_by_destination = index_by_destination or {}
        self.default_index = default_index
        self.queries = []

    def search(self, query: SearchQuery):
        self.queries.append(query)
        dtd = (query.departure_date - (query.as_of or date.today())).days
        bench = benchmarks.benchmark(
            query.destination, query.departure_date, dtd,
            origin=query.origin, cabin=query.cabin, passengers=query.passengers,
        ).price
        target = self.index_by_destination.get(query.destination, self.default_index)
        return [
            Offer(
                price=bench * target / 100.0,
                currency=query.currency,
                airline="XX", stops=1, duration_minutes=600,
                departure_date=query.departure_date, return_date=query.return_date,
            )
        ]


class FailingProvider(Provider):
    name = "failing"

    def search(self, query: SearchQuery):
        raise ProviderError("provedor fora do ar")


class RecordingNotifier(Notifier):
    def __init__(self):
        self.sent = []

    def send(self, verdict, quote, watch, alert=None):
        self.sent.append((verdict, quote, watch, alert))


class TestMetodologia(unittest.TestCase):
    def test_contagem_de_sondagens_e_impar(self):
        """Com contagem par a mediana cairia entre duas cotações."""
        spec = monitor.ProbeSpec.from_config(test_config())
        self.assertEqual(len(spec.horizons) % 2, 1)

    def test_descricao_cita_a_metodologia(self):
        texto = monitor.ProbeSpec.from_config(test_config()).describe()
        self.assertIn("GRU", texto)
        self.assertIn("econômica", texto)

    def test_representante_e_a_sondagem_mediana(self):
        provider = FakeProvider()
        probe = monitor.probe_destination(
            provider, "LIS", monitor.ProbeSpec(), date.today(), {}, datetime.now()
        )
        self.assertEqual(len(probe.readings), 3)
        indices = sorted(r.index for r in probe.readings)
        self.assertAlmostEqual(probe.representative.index, indices[1], places=6)
        self.assertAlmostEqual(probe.index, indices[1], places=6)

    def test_sondagem_sem_oferta_reporta_erro(self):
        probe = monitor.probe_destination(
            FailingProvider(), "LIS", monitor.ProbeSpec(), date.today(), {}, datetime.now()
        )
        self.assertFalse(probe.ok)
        self.assertIn("fora do ar", probe.error)


class TestRodada(unittest.TestCase):
    def setUp(self):
        self.conn = memory_db()
        self.config = test_config()

    def test_rodada_mede_os_dez_destinos(self):
        result = monitor.run_round(self.conn, self.config, FakeProvider(), include_watches=False)
        self.assertEqual(result.basket.size, 10)
        self.assertAlmostEqual(result.basket.index, 100.0, places=3)
        self.assertEqual(result.errors, [])

    def test_rodada_grava_cotacoes_e_snapshot(self):
        result = monitor.run_round(self.conn, self.config, FakeProvider(), include_watches=False)
        stats = db.quote_stats(self.conn)
        self.assertEqual(stats["quotes"], 30)  # 10 destinos × 3 sondagens
        self.assertEqual(stats["rounds"], 1)
        snapshot = db.latest_snapshot(self.conn)
        self.assertEqual(snapshot.round_id, result.round_id)
        self.assertEqual(snapshot.size, 10)

    def test_mercado_em_linha_nao_gera_alerta(self):
        result = monitor.run_round(self.conn, self.config, FakeProvider(), include_watches=False)
        self.assertEqual(result.alerts, [])

    def test_destino_distorcido_gera_alerta(self):
        provider = FakeProvider({"LIS": 76.0}, default_index=101.0)
        notifier = RecordingNotifier()
        result = monitor.run_round(
            self.conn, self.config, provider, include_watches=False, notifier=notifier
        )
        self.assertEqual(len(result.alerts), 1)
        alerta = result.alerts[0]
        self.assertEqual(alerta.destination, "LIS")
        self.assertIn(alerta.driver, ("distortion", "both"))
        self.assertLess(alerta.distortion, -15)
        self.assertTrue(alerta.notified)
        self.assertEqual(len(notifier.sent), 1)

    def test_falha_de_um_destino_nao_derruba_a_rodada(self):
        class Parcial(FakeProvider):
            def search(self, query):
                if query.destination == "HND":
                    raise ProviderError("sem resultado para HND")
                return super().search(query)

        result = monitor.run_round(self.conn, self.config, Parcial(), include_watches=False)
        self.assertEqual(result.basket.size, 9)
        self.assertEqual(len(result.errors), 1)
        self.assertIn("HND", result.errors[0])

    def test_cesta_e_reconstruida_do_banco(self):
        provider = FakeProvider({"MAD": 82.0}, default_index=103.0)
        original = monitor.run_round(self.conn, self.config, provider, include_watches=False)
        recuperada = monitor.current_basket(self.conn)
        self.assertAlmostEqual(recuperada.index, original.basket.index, places=4)
        self.assertEqual(recuperada.size, original.basket.size)
        self.assertAlmostEqual(recuperada.index_of("MAD"), original.basket.index_of("MAD"), places=4)

    def test_indice_gravado_bate_com_a_serie(self):
        """O número do painel, do alerta e da série precisa ser o mesmo."""
        provider = FakeProvider({"LIS": 84.0}, default_index=100.0)
        monitor.run_round(self.conn, self.config, provider, include_watches=False)
        basket = monitor.current_basket(self.conn)
        serie = db.destination_index_series(self.conn, "LIS")
        self.assertAlmostEqual(basket.index_of("LIS"), serie[-1][1], places=6)


class TestDeduplicacao(unittest.TestCase):
    def setUp(self):
        self.conn = memory_db()
        self.config = test_config(alert_cooldown_hours=24, alert_improve_pct=3.0)
        self.provider = FakeProvider({"LIS": 74.0}, default_index=101.0)

    def rodar(self, quando):
        return monitor.run_round(
            self.conn, self.config, self.provider, include_watches=False, now=quando
        )

    def test_nao_repete_dentro_da_carencia(self):
        agora = datetime.now()
        self.assertEqual(len(self.rodar(agora).alerts), 1)
        self.assertEqual(len(self.rodar(agora + timedelta(hours=2)).alerts), 0)

    def test_repete_depois_da_carencia(self):
        agora = datetime.now()
        self.rodar(agora)
        self.assertEqual(len(self.rodar(agora + timedelta(hours=25)).alerts), 1)

    def test_repete_quando_o_preco_melhora(self):
        agora = datetime.now()
        self.rodar(agora)
        self.provider.index_by_destination["LIS"] = 62.0
        self.assertEqual(len(self.rodar(agora + timedelta(hours=2)).alerts), 1)


class TestViagensAcompanhadas(unittest.TestCase):
    def setUp(self):
        self.conn = memory_db()
        self.config = test_config()

    def test_viagem_e_cotada_e_indexada(self):
        watch = make_watch("LIS", days_ahead=90)
        watch.id = db.insert_watch(self.conn, watch)
        basket = monitor.run_round(
            self.conn, self.config, FakeProvider(), include_watches=False
        ).basket
        result = monitor.collect_watch(
            self.conn, self.config, FakeProvider({"LIS": 80.0}), watch, basket
        )
        self.assertTrue(result.ok)
        self.assertAlmostEqual(result.verdict.index, 80.0, places=3)
        self.assertEqual(result.quote.kind, KIND_WATCH)

    def test_destino_fora_da_cesta_e_recusado(self):
        watch = make_watch("MAO", days_ahead=90)
        watch.id = db.insert_watch(self.conn, watch)
        result = monitor.collect_watch(self.conn, self.config, FakeProvider(), watch)
        self.assertFalse(result.ok)
        self.assertIn("não está na cesta", result.error)

    def test_flexibilidade_escolhe_o_menor_indice(self):
        """Entre datas vizinhas vence o menor índice, não o menor preço bruto:
        uma data barata só por ser baixa estação não é oportunidade."""
        watch = make_watch("CUN", days_ahead=90, flex_days=3)
        watch.id = db.insert_watch(self.conn, watch)
        result = monitor.collect_watch(self.conn, self.config, FakeProvider(), watch)
        self.assertTrue(result.ok)
        self.assertAlmostEqual(result.verdict.index, 100.0, places=2)

    def test_rodada_completa_inclui_as_viagens(self):
        watch = make_watch("JFK", days_ahead=100)
        watch.id = db.insert_watch(self.conn, watch)
        result = monitor.run_round(self.conn, self.config, FakeProvider())
        self.assertEqual(len(result.watch_results), 1)
        self.assertTrue(result.watch_results[0].ok)
        self.assertIsNotNone(db.get_watch(self.conn, watch.id).last_checked_at)

    def test_viagem_pausada_nao_e_cotada(self):
        watch = make_watch("JFK", days_ahead=100)
        watch.active = False
        db.insert_watch(self.conn, watch)
        result = monitor.run_round(self.conn, self.config, FakeProvider())
        self.assertEqual(result.watch_results, [])

    def test_datas_candidatas_descartam_o_passado(self):
        watch = make_watch("LIS", days_ahead=1, flex_days=3)
        datas = monitor.candidate_dates(watch, date.today())
        self.assertTrue(all(d >= date.today() for d in datas))


class TestRecalibracaoNaRodada(unittest.TestCase):
    def test_recalibracao_corrige_um_desvio_conhecido(self):
        """Mercado 18% acima da tabela: a recalibração precisa reencontrar isso."""
        conn = memory_db()
        config = test_config()
        provider = quiet_provider(bias=1.18)
        agora = datetime.now()
        for i in range(12):
            monitor.run_round(
                conn, config, provider, include_watches=False,
                now=agora - timedelta(days=14 * i),
            )
        antes = monitor.run_round(
            conn, config, provider, include_watches=False, now=agora
        ).basket.index
        self.assertGreater(antes, 112)

        aplicadas = calibration.apply(conn, calibration.propose_all(conn, since_days=400))
        self.assertEqual(len(aplicadas), 10)

        depois = monitor.run_round(
            conn, config, provider, include_watches=False, now=agora
        ).basket.index
        self.assertLess(abs(depois - 100), abs(antes - 100))

    def test_rodada_usa_a_base_recalibrada(self):
        conn = memory_db()
        config = test_config()
        from flightwatch.models import BaseOverride

        db.upsert_base_override(
            conn, BaseOverride(destination="LIS", base_price=8400.0, updated_at=datetime.now())
        )
        result = monitor.run_round(conn, config, FakeProvider(), include_watches=False)
        quotes = [q for q in db.quotes_for_round(conn, result.round_id) if q.destination == "LIS"]
        self.assertTrue(quotes)
        self.assertAlmostEqual(quotes[0].base_used, 8400.0, places=4)


if __name__ == "__main__":
    unittest.main()
