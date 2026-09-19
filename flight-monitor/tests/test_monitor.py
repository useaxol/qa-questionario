"""Testes da coleta, do alerta e da deduplicação."""
from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta

from helpers import make_watch, memory_db, seeded_route, test_config

from flightwatch import db, monitor
from flightwatch.models import Observation
from flightwatch.notifier import Notifier
from flightwatch.providers import Offer, Provider, ProviderError, SearchQuery
from flightwatch.providers.synthetic import SyntheticProvider


class FakeProvider(Provider):
    """Provedor controlado: devolve o preço que o teste mandar."""

    name = "fake"
    supports_backfill = False

    def __init__(self, price: float):
        self.price = price
        self.queries = []

    def search(self, query: SearchQuery):
        self.queries.append(query)
        return [
            Offer(
                price=self.price,
                currency=query.currency,
                airline="XX",
                stops=1,
                duration_minutes=600,
                departure_date=query.departure_date,
                return_date=query.return_date,
            )
        ]


class FailingProvider(Provider):
    name = "failing"

    def search(self, query: SearchQuery):
        raise ProviderError("provedor fora do ar")


class RecordingNotifier(Notifier):
    def __init__(self):
        self.sent = []

    def send(self, watch, assessment, observation, alert=None):
        self.sent.append((watch, assessment, observation, alert))


class TestDatasCandidatas(unittest.TestCase):
    def test_sem_flexibilidade_cota_apenas_a_data(self):
        watch = make_watch(days_ahead=30)
        datas = monitor.candidate_dates(watch, date.today())
        self.assertEqual(datas, [watch.departure_date])

    def test_flexibilidade_cobre_os_dias_vizinhos(self):
        watch = make_watch(days_ahead=30, flex_days=2)
        datas = monitor.candidate_dates(watch, date.today())
        self.assertEqual(len(datas), 5)
        self.assertIn(watch.departure_date - timedelta(days=2), datas)
        self.assertIn(watch.departure_date + timedelta(days=2), datas)

    def test_datas_passadas_sao_descartadas(self):
        watch = make_watch(days_ahead=1, flex_days=3)
        datas = monitor.candidate_dates(watch, date.today())
        self.assertTrue(all(d >= date.today() for d in datas))

    def test_volta_acompanha_o_deslocamento_da_ida(self):
        watch = make_watch(days_ahead=30, nights=10, flex_days=1)
        nova_ida = watch.departure_date + timedelta(days=1)
        self.assertEqual(
            monitor._return_for(watch, nova_ida), nova_ida + timedelta(days=10)
        )


class TestColeta(unittest.TestCase):
    def setUp(self):
        self.conn = memory_db()
        self.config = test_config()
        seeded_route(self.conn)
        self.watch = make_watch(days_ahead=120)
        self.watch.id = db.insert_watch(self.conn, self.watch)
        model, amostras = monitor.route_model_for(self.conn, self.watch)
        self.model = model
        self.esperado = model.predict(self.watch.departure_date, 120)

    def coletar(self, preco, notifier=None):
        provider = FakeProvider(preco)
        return monitor.collect_watch(
            self.conn, self.config, provider, self.watch, notifier=notifier
        )

    def test_coleta_grava_observacao(self):
        resultado = self.coletar(self.esperado)
        self.assertTrue(resultado.ok)
        self.assertIsNotNone(resultado.best)
        self.assertEqual(len(db.watch_history(self.conn, self.watch.id)), 1)

    def test_coleta_atualiza_ultima_verificacao(self):
        self.coletar(self.esperado)
        atualizado = db.get_watch(self.conn, self.watch.id)
        self.assertIsNotNone(atualizado.last_checked_at)

    def test_preco_normal_nao_gera_alerta(self):
        resultado = self.coletar(self.esperado)
        self.assertIsNone(resultado.alert)
        self.assertEqual(db.list_alerts(self.conn), [])

    def test_queda_forte_gera_alerta_e_notifica(self):
        notifier = RecordingNotifier()
        resultado = self.coletar(self.esperado * 0.68, notifier=notifier)
        self.assertIsNotNone(resultado.alert)
        self.assertTrue(resultado.alert.notified)
        self.assertEqual(len(notifier.sent), 1)
        self.assertEqual(len(db.list_alerts(self.conn)), 1)

    def test_falha_do_provedor_e_reportada_sem_quebrar(self):
        resultado = monitor.collect_watch(
            self.conn, self.config, FailingProvider(), self.watch
        )
        self.assertFalse(resultado.ok)
        self.assertIn("fora do ar", resultado.error)

    def test_modelo_nao_e_contaminado_pela_propria_cotacao(self):
        """A avaliação compara com a história anterior, não com ela mesma."""
        antes = monitor.route_model_for(self.conn, self.watch)[0].n
        resultado = self.coletar(self.esperado * 0.68)
        self.assertEqual(resultado.assessment.n_samples, antes)

    def test_flexibilidade_grava_uma_observacao_por_data(self):
        self.watch.flex_days = 2
        resultado = self.coletar(self.esperado)
        self.assertEqual(len(resultado.observations), 5)


class TestDeduplicacaoDeAlertas(unittest.TestCase):
    def setUp(self):
        self.conn = memory_db()
        self.config = test_config(alert_cooldown_hours=12, alert_improve_pct=3.0)
        seeded_route(self.conn)
        self.watch = make_watch(days_ahead=120)
        self.watch.id = db.insert_watch(self.conn, self.watch)
        model, _ = monitor.route_model_for(self.conn, self.watch)
        self.esperado = model.predict(self.watch.departure_date, 120)

    def coletar(self, preco, quando=None):
        return monitor.collect_watch(
            self.conn, self.config, FakeProvider(preco), self.watch, now=quando
        )

    def test_nao_repete_o_mesmo_alerta_dentro_da_carencia(self):
        agora = datetime.now()
        primeiro = self.coletar(self.esperado * 0.68, agora)
        segundo = self.coletar(self.esperado * 0.68, agora + timedelta(hours=1))
        self.assertIsNotNone(primeiro.alert)
        self.assertIsNone(segundo.alert)

    def test_repete_quando_o_preco_melhora(self):
        agora = datetime.now()
        self.coletar(self.esperado * 0.68, agora)
        melhor = self.coletar(self.esperado * 0.60, agora + timedelta(hours=1))
        self.assertIsNotNone(melhor.alert)

    def test_repete_depois_da_carencia(self):
        agora = datetime.now()
        self.coletar(self.esperado * 0.68, agora)
        depois = self.coletar(self.esperado * 0.68, agora + timedelta(hours=13))
        self.assertIsNotNone(depois.alert)


class TestPrecoAlvo(unittest.TestCase):
    def test_preco_alvo_alerta_mesmo_sem_sinal_estatistico(self):
        conn = memory_db()
        config = test_config()
        seeded_route(conn)
        watch = make_watch(days_ahead=120)
        model, _ = monitor.route_model_for(conn, watch)
        esperado = model.predict(watch.departure_date, 120)
        watch.target_price = esperado * 1.01  # alvo folgado: preço normal já atinge
        watch.id = db.insert_watch(conn, watch)

        resultado = monitor.collect_watch(conn, config, FakeProvider(esperado), watch)
        self.assertIsNotNone(resultado.alert)
        self.assertEqual(resultado.assessment.verdict, "target_hit")


class TestRodadaCompleta(unittest.TestCase):
    def test_run_collection_percorre_apenas_rotas_ativas(self):
        conn = memory_db()
        config = test_config()
        ativa = make_watch(label="ativa", days_ahead=90)
        ativa.id = db.insert_watch(conn, ativa)
        pausada = make_watch(label="pausada", destination="MAD", days_ahead=90)
        pausada.active = False
        pausada.id = db.insert_watch(conn, pausada)

        resultados = monitor.run_collection(conn, config, SyntheticProvider())
        self.assertEqual(len(resultados), 1)
        self.assertEqual(resultados[0].watch.id, ativa.id)

    def test_snapshot_traz_ultima_cotacao_e_modelo(self):
        conn = memory_db()
        config = test_config()
        seeded_route(conn)
        watch = make_watch(days_ahead=120)
        watch.id = db.insert_watch(conn, watch)
        monitor.collect_watch(conn, config, SyntheticProvider(), watch)

        snapshot = monitor.watch_snapshot(conn, watch)
        self.assertIsNotNone(snapshot["latest"])
        self.assertIsNotNone(snapshot["assessment"])
        self.assertTrue(snapshot["model"].fitted)


if __name__ == "__main__":
    unittest.main()
