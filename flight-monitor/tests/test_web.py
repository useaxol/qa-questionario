"""Testes da camada web, dos gráficos e da persistência."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta

from helpers import make_watch, memory_db, seeded_route, test_config

from flightwatch import charts, db, monitor, seed
from flightwatch.config import Config
from flightwatch.models import Alert, Observation
from flightwatch.notifier import JsonlFileNotifier, format_alert_text, format_money
from flightwatch.providers.synthetic import SyntheticProvider
from flightwatch.web import create_app, daily_series, watch_from_form


class TestPersistencia(unittest.TestCase):
    def setUp(self):
        self.conn = memory_db()

    def test_ciclo_de_vida_de_uma_rota(self):
        watch = make_watch()
        watch.id = db.insert_watch(self.conn, watch)
        lido = db.get_watch(self.conn, watch.id)
        self.assertEqual(lido.origin, "GRU")
        self.assertEqual(lido.departure_date, watch.departure_date)
        self.assertTrue(lido.active)

        db.set_watch_active(self.conn, watch.id, False)
        self.assertFalse(db.get_watch(self.conn, watch.id).active)
        self.assertEqual(db.list_watches(self.conn, only_active=True), [])

        db.delete_watch(self.conn, watch.id)
        self.assertIsNone(db.get_watch(self.conn, watch.id))

    def test_historico_filtra_por_rota_comparavel(self):
        seeded_route(self.conn, "GRU", "LIS", days_back=60, step_days=15)
        seeded_route(self.conn, "GRU", "MAD", days_back=60, step_days=15)
        so_lis = db.route_history(self.conn, "GRU", "LIS", "round", "ECONOMY", "BRL")
        self.assertTrue(so_lis)
        self.assertTrue(all(o.destination == "LIS" for o in so_lis))

    def test_historico_respeita_o_corte_temporal(self):
        seeded_route(self.conn, days_back=200, step_days=20)
        corte = datetime.now() - timedelta(days=100)
        anteriores = db.route_history(
            self.conn, "GRU", "LIS", "round", "ECONOMY", "BRL", before=corte
        )
        self.assertTrue(all(o.observed_at < corte for o in anteriores))

    def test_alerta_persistido_volta_integro(self):
        watch = make_watch()
        watch.id = db.insert_watch(self.conn, watch)
        alerta = Alert(
            watch_id=watch.id, created_at=datetime.now(), verdict="great_deal",
            severity=2, price=3000.0, expected_price=4000.0, discount_pct=25.0,
            z_score=-2.0, percentile=95.0, confidence="high", deal_score=80.0,
            message="teste", payload={"a": 1},
        )
        alerta.id = db.insert_alert(self.conn, alerta)
        lido = db.list_alerts(self.conn)[0]
        self.assertEqual(lido.verdict, "great_deal")
        self.assertEqual(lido.payload, {"a": 1})
        self.assertAlmostEqual(lido.delta_pct, -25.0, places=6)

    def test_purga_remove_apenas_o_que_e_antigo(self):
        seeded_route(self.conn, days_back=400, step_days=30)
        antes = db.observation_stats(self.conn)["observations"]
        db.purge_old_observations(self.conn, keep_days=100)
        depois = db.observation_stats(self.conn)["observations"]
        self.assertLess(depois, antes)
        self.assertGreater(depois, 0)


class TestGraficos(unittest.TestCase):
    def test_grafico_de_historico_gera_svg(self):
        pontos = [
            (datetime.now() - timedelta(days=i), 4000 + i * 7) for i in range(30, 0, -1)
        ]
        esperado = [(t, 4200.0) for t, _ in pontos]
        svg = charts.price_history_chart(
            pontos, esperado, alerts=[(pontos[5][0], pontos[5][1], 2)], band_pct=0.12
        )
        self.assertIn("<svg", svg)
        self.assertIn("fw-line-price", svg)
        self.assertIn("fw-band", svg)
        self.assertIn("fw-alert-dot", svg)

    def test_grafico_vazio_nao_quebra(self):
        self.assertIn("<svg", charts.price_history_chart([]))
        self.assertIn("<svg", charts.sparkline([]))
        self.assertIn("<svg", charts.diverging_bars([]))

    def test_barras_divergentes_separam_os_sinais(self):
        svg = charts.diverging_bars([("a", 10.0), ("b", -10.0)])
        self.assertIn("fw-bar-high", svg)
        self.assertIn("fw-bar-low", svg)

    def test_marcacoes_de_eixo_sao_redondas(self):
        ticks = charts.nice_ticks(1234, 9876, 4)
        self.assertTrue(all(t % 500 == 0 for t in ticks), ticks)

    def test_texto_e_escapado(self):
        svg = charts.diverging_bars([("<script>", 5.0)])
        self.assertNotIn("<script>", svg)
        self.assertIn("&lt;script&gt;", svg)

    def test_serie_diaria_pega_o_menor_preco_do_dia(self):
        hoje = datetime.now().replace(hour=9)
        obs = [
            Observation(observed_at=hoje, price_per_pax=1000, price=1000),
            Observation(observed_at=hoje.replace(hour=18), price_per_pax=800, price=800),
        ]
        serie = daily_series(obs)
        self.assertEqual(len(serie), 1)
        self.assertEqual(serie[0][1], 800)


class TestNotificacao(unittest.TestCase):
    def test_formatacao_de_dinheiro(self):
        self.assertTrue(format_money(1234, "BRL").startswith("R$"))
        self.assertTrue(format_money(1234, "USD").startswith("US$"))

    def test_texto_do_alerta_cita_preco_e_motivos(self):
        conn = memory_db()
        seeded_route(conn)
        watch = make_watch(days_ahead=120)
        watch.id = db.insert_watch(conn, watch)
        resultado = monitor.collect_watch(conn, test_config(), SyntheticProvider(), watch)
        texto = format_alert_text(watch, resultado.assessment, resultado.best)
        self.assertIn("GRU", texto)
        self.assertIn("preço esperado", texto)

    def test_arquivo_jsonl_recebe_uma_linha_por_alerta(self):
        conn = memory_db()
        seeded_route(conn)
        watch = make_watch(days_ahead=120)
        watch.id = db.insert_watch(conn, watch)
        with tempfile.TemporaryDirectory() as tmp:
            caminho = os.path.join(tmp, "alerts.jsonl")
            notifier = JsonlFileNotifier(caminho)
            resultado = monitor.collect_watch(conn, test_config(), SyntheticProvider(), watch)
            notifier.send(watch, resultado.assessment, resultado.best, None)
            with open(caminho, encoding="utf-8") as handle:
                linhas = handle.readlines()
            self.assertEqual(len(linhas), 1)
            payload = json.loads(linhas[0])
            self.assertIn("assessment", payload)
            self.assertIn("watch", payload)


class TestValidacaoDeFormulario(unittest.TestCase):
    def setUp(self):
        self.config = Config()
        self.base = {
            "origin": "gru",
            "destination": "lis",
            "departure_date": (date.today() + timedelta(days=60)).isoformat(),
            "return_date": (date.today() + timedelta(days=70)).isoformat(),
            "trip_type": "round",
        }

    def test_formulario_valido(self):
        watch = watch_from_form(self.base, self.config)
        self.assertEqual(watch.origin, "GRU")
        self.assertEqual(watch.destination, "LIS")

    def test_origem_igual_ao_destino_e_recusada(self):
        dados = dict(self.base, destination="GRU")
        with self.assertRaises(ValueError):
            watch_from_form(dados, self.config)

    def test_data_passada_e_recusada(self):
        dados = dict(self.base, departure_date=(date.today() - timedelta(days=1)).isoformat())
        with self.assertRaises(ValueError):
            watch_from_form(dados, self.config)

    def test_volta_antes_da_ida_e_recusada(self):
        dados = dict(self.base, return_date=(date.today() + timedelta(days=50)).isoformat())
        with self.assertRaises(ValueError):
            watch_from_form(dados, self.config)

    def test_ida_e_volta_exige_a_volta(self):
        dados = dict(self.base)
        dados.pop("return_date")
        with self.assertRaises(ValueError):
            watch_from_form(dados, self.config)

    def test_somente_ida_dispensa_a_volta(self):
        dados = dict(self.base, trip_type="oneway")
        dados.pop("return_date")
        watch = watch_from_form(dados, self.config)
        self.assertIsNone(watch.return_date)

    def test_iata_invalido_e_recusado(self):
        with self.assertRaises(ValueError):
            watch_from_form(dict(self.base, origin="X"), self.config)

    def test_cabine_invalida_e_recusada(self):
        with self.assertRaises(ValueError):
            watch_from_form(dict(self.base, cabin="LUXO"), self.config)

    def test_flexibilidade_e_limitada(self):
        watch = watch_from_form(dict(self.base, flex_days="99"), self.config)
        self.assertLessEqual(watch.flex_days, 7)


class TestPaginasWeb(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        caminho = os.path.join(cls.tmpdir.name, "test.db")
        cls.config = test_config(db_path=caminho)
        with db.session(caminho) as conn:
            seed.seed_demo(conn, cls.config, SyntheticProvider(), days_back=120, verbose=False)
            monitor.run_collection(conn, cls.config, SyntheticProvider())
            cls.watch_id = db.list_watches(conn)[0].id
        cls.app = create_app(cls.config)
        cls.client = cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        cls.tmpdir.cleanup()

    def test_paginas_respondem(self):
        for rota in ("/", "/alerts", "/watches/new", "/health", f"/watch/{self.watch_id}"):
            with self.subTest(rota=rota):
                self.assertEqual(self.client.get(rota).status_code, 200)

    def test_rota_inexistente_responde_404(self):
        self.assertEqual(self.client.get("/watch/99999").status_code, 404)

    def test_painel_mostra_o_preco_padrao(self):
        corpo = self.client.get("/").get_data(as_text=True)
        self.assertIn("padrão", corpo)
        self.assertIn("Painel", corpo)

    def test_api_de_rotas(self):
        dados = self.client.get("/api/watches").get_json()
        self.assertIn("watches", dados)
        self.assertTrue(dados["watches"])
        primeira = dados["watches"][0]
        self.assertIn("assessment", primeira)
        self.assertIn("latest_price", primeira)

    def test_api_de_historico(self):
        dados = self.client.get(f"/api/watches/{self.watch_id}/history").get_json()
        self.assertTrue(dados["points"])

    def test_api_de_aeroportos(self):
        dados = self.client.get("/api/airports?q=lisboa").get_json()
        self.assertTrue(any(a["iata"] == "LIS" for a in dados["airports"]))

    def test_api_cria_rota(self):
        resposta = self.client.post(
            "/api/watches",
            json={
                "origin": "CGH",
                "destination": "SDU",
                "departure_date": (date.today() + timedelta(days=30)).isoformat(),
                "trip_type": "oneway",
            },
        )
        self.assertEqual(resposta.status_code, 201)
        self.assertIn("id", resposta.get_json())

    def test_api_rejeita_rota_invalida(self):
        resposta = self.client.post("/api/watches", json={"origin": "CGH"})
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("error", resposta.get_json())

    def test_api_de_coleta(self):
        resposta = self.client.post("/api/collect", json={"watch_ids": [self.watch_id]})
        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta.get_json()["results"])


if __name__ == "__main__":
    unittest.main()
