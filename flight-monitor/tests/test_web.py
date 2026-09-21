"""Testes da camada web, dos gráficos, da persistência e do provedor."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta

from helpers import (
    make_watch, memory_db, quiet_provider, synthetic_basket, test_config,
)

from flightwatch import benchmarks, charts, db, indexing, monitor
from flightwatch.models import Alert, BaseOverride, BasketSnapshot, Quote
from flightwatch.notifier import (
    JsonlFileNotifier, format_alert_text, format_money, headline,
)
from flightwatch.providers import ProviderError, get_provider
from flightwatch.providers.base import SearchQuery
from flightwatch.providers.synthetic import SyntheticProvider, market_drift, sale_factor
from flightwatch.web import create_app, watch_from_form


class TestPersistencia(unittest.TestCase):
    def setUp(self):
        self.conn = memory_db()

    def test_ciclo_de_vida_de_uma_viagem(self):
        watch = make_watch()
        watch.id = db.insert_watch(self.conn, watch)
        self.assertEqual(db.get_watch(self.conn, watch.id).destination, "LIS")
        db.set_watch_active(self.conn, watch.id, False)
        self.assertEqual(db.list_watches(self.conn, only_active=True), [])
        db.delete_watch(self.conn, watch.id)
        self.assertIsNone(db.get_watch(self.conn, watch.id))

    def test_snapshot_e_idempotente_por_rodada(self):
        agora = datetime.now()
        for valor in (100.0, 97.0):
            db.insert_snapshot(
                self.conn,
                BasketSnapshot(round_id="r1", collected_at=agora, index_value=valor, size=10),
            )
        self.assertEqual(db.latest_snapshot(self.conn).index_value, 97.0)
        self.assertEqual(db.quote_stats(self.conn)["rounds"], 1)

    def test_alerta_persistido_volta_integro(self):
        alert = Alert(
            created_at=datetime.now(), destination="LIS", level=2, driver="distortion",
            price=3000.0, benchmark=4000.0, index_value=75.0, basket_index=101.0,
            distortion=-26.0, signal=2.1, score=87.0, message="teste", payload={"a": 1},
        )
        alert.id = db.insert_alert(self.conn, alert)
        lido = db.list_alerts(self.conn)[0]
        self.assertEqual(lido.driver, "distortion")
        self.assertEqual(lido.payload, {"a": 1})
        self.assertAlmostEqual(lido.gap_pct, -25.0, places=6)
        self.assertIn("abaixo", lido.gap_label)

    def test_override_de_base_sobrescreve(self):
        for valor in (5000.0, 5500.0):
            db.upsert_base_override(
                self.conn, BaseOverride(destination="LIS", base_price=valor)
            )
        self.assertEqual(db.load_base_overrides(self.conn), {"LIS": 5500.0})
        self.assertEqual(db.clear_base_overrides(self.conn), 1)
        self.assertEqual(db.load_base_overrides(self.conn), {})

    def test_serie_do_destino_usa_a_mediana_da_rodada(self):
        agora = datetime.now()
        for index in (80.0, 90.0, 130.0):
            db.insert_quote(
                self.conn,
                Quote(
                    kind="basket", round_id="r1", origin="GRU", destination="LIS",
                    departure_date=date.today() + timedelta(days=60), days_to_departure=60,
                    currency="BRL", price=1000.0, benchmark=1000.0, index_value=index,
                    provider="fake", collected_at=agora,
                ),
            )
        serie = db.destination_index_series(self.conn, "LIS")
        self.assertEqual(len(serie), 1)
        self.assertAlmostEqual(serie[0][1], 90.0)

    def test_purga_remove_o_que_e_antigo(self):
        antigo = datetime.now() - timedelta(days=400)
        db.insert_quote(
            self.conn,
            Quote(kind="basket", round_id="velho", origin="GRU", destination="LIS",
                  departure_date=date.today(), currency="BRL", price=1.0, benchmark=1.0,
                  index_value=100.0, provider="fake", collected_at=antigo),
        )
        db.insert_quote(
            self.conn,
            Quote(kind="basket", round_id="novo", origin="GRU", destination="LIS",
                  departure_date=date.today(), currency="BRL", price=1.0, benchmark=1.0,
                  index_value=100.0, provider="fake", collected_at=datetime.now()),
        )
        self.assertEqual(db.purge_old_quotes(self.conn, keep_days=100), 1)
        self.assertEqual(db.quote_stats(self.conn)["quotes"], 1)


class TestSimulador(unittest.TestCase):
    def test_e_deterministico(self):
        provider = SyntheticProvider()
        query = _query()
        self.assertEqual(
            [o.price for o in provider.search(query)],
            [o.price for o in provider.search(query)],
        )

    def test_ancorado_no_benchmark(self):
        """Sem ruído nem deriva, o simulador devolve o próprio benchmark."""
        provider = quiet_provider()
        query = _query()
        esperado = benchmarks.benchmark("LIS", query.departure_date, 60).price
        self.assertAlmostEqual(provider.fair_price(query) / esperado, 1.0, delta=0.15)

    def test_bias_desloca_o_mercado(self):
        base = quiet_provider().fair_price(_query())
        desviado = quiet_provider(bias=1.3).fair_price(_query())
        self.assertAlmostEqual(desviado / base, 1.3, places=6)

    def test_rota_fora_da_cesta_ainda_e_cotada(self):
        query = _query(destination="MAO")
        self.assertGreater(SyntheticProvider().cheapest(query).price, 0)

    def test_nao_cota_data_passada(self):
        query = _query()
        query.departure_date = date.today() - timedelta(days=5)
        self.assertEqual(SyntheticProvider().search(query), [])

    def test_ofertas_ordenadas_e_limite_de_paradas(self):
        precos = [o.price for o in SyntheticProvider().search(_query())]
        self.assertEqual(precos, sorted(precos))
        query = _query()
        query.max_stops = 0
        self.assertEqual(SyntheticProvider().cheapest(query).stops, 0)

    def test_deriva_de_mercado_move_tudo_junto(self):
        hoje, depois = date(2026, 1, 15), date(2026, 8, 15)
        self.assertNotAlmostEqual(market_drift(hoje), market_drift(depois), places=3)

    def test_promocao_e_rara_e_forte(self):
        amostras = [
            sale_factor("LIS", date(2026, 1, 1) + timedelta(days=d)) for d in range(0, 365, 4)
        ]
        descontos = [f for f in amostras if f < 1.0]
        self.assertTrue(descontos)
        self.assertLess(len(descontos) / len(amostras), 0.25)
        self.assertLess(max(descontos), 0.90)


def _query(destination="LIS", days_ahead=60):
    departure = date.today() + timedelta(days=days_ahead)
    return SearchQuery(
        origin="GRU", destination=destination, departure_date=departure,
        return_date=departure + timedelta(days=10), currency="BRL", as_of=date.today(),
    )


class TestGraficos(unittest.TestCase):
    def test_serie_de_indice_gera_svg(self):
        pontos = [(datetime.now() - timedelta(days=i), 100 - i % 9) for i in range(30, 0, -1)]
        comparacao = [(t, 101.0) for t, _ in pontos]
        svg = charts.index_history_chart(
            pontos, comparacao, band_pct=12,
            alerts=[(pontos[4][0], pontos[4][1], 2)],
        )
        for classe in ("fw-line-index", "fw-line-compare", "fw-reference", "fw-band", "fw-alert-dot"):
            self.assertIn(classe, svg)

    def test_barras_da_cesta_separam_os_lados(self):
        svg = charts.basket_bars(
            [("Lisboa (LIS)", 78, "distorção"), ("Tóquio (HND)", 118, "acima")], 101
        )
        self.assertIn("fw-bar-low", svg)
        self.assertIn("fw-bar-high", svg)
        self.assertIn("fw-basket-mark", svg)

    def test_graficos_vazios_nao_quebram(self):
        self.assertIn("<svg", charts.index_history_chart([]))
        self.assertIn("<svg", charts.basket_bars([]))
        self.assertIn("<svg", charts.sparkline([]))

    def test_texto_e_escapado(self):
        svg = charts.basket_bars([("<script>alert(1)</script>", 90, "x")], 100)
        self.assertNotIn("<script>", svg)
        self.assertIn("&lt;script&gt;", svg)

    def test_marcacoes_de_eixo_sao_redondas(self):
        self.assertTrue(all(t % 5 == 0 for t in charts.nice_ticks(81, 119, 5)))


class TestNotificacao(unittest.TestCase):
    def setUp(self):
        self.basket, readings = synthetic_basket({"LIS": 76.0}, default_index=101.0)
        self.reading = next(r for r in readings if r.destination == "LIS")
        self.verdict = indexing.evaluate(self.reading, self.basket)

    def test_formatacao_de_dinheiro_em_portugues(self):
        self.assertEqual(format_money(12345, "BRL"), "R$12.345")
        self.assertTrue(format_money(1234, "USD").startswith("US$"))

    def test_titulo_cita_indice_e_cesta(self):
        texto = headline(self.verdict)
        self.assertIn("índice", texto)
        self.assertIn("cesta", texto)

    def test_texto_do_alerta_traz_as_razoes(self):
        texto = format_alert_text(self.verdict)
        self.assertIn("benchmark", texto)
        self.assertIn("Lisboa", texto)
        self.assertTrue(any(linha.strip().startswith("•") for linha in texto.splitlines()))

    def test_arquivo_jsonl_recebe_uma_linha(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho = os.path.join(tmp, "alerts.jsonl")
            JsonlFileNotifier(caminho).send(self.verdict, None, None, None)
            with open(caminho, encoding="utf-8") as handle:
                linhas = handle.readlines()
        self.assertEqual(len(linhas), 1)
        payload = json.loads(linhas[0])
        self.assertEqual(payload["destination"], "LIS")
        self.assertIn("verdict", payload)


class TestFormulario(unittest.TestCase):
    def setUp(self):
        self.config = test_config()
        self.base = {
            "origin": "gru",
            "destination": "lis",
            "departure_date": (date.today() + timedelta(days=60)).isoformat(),
            "return_date": (date.today() + timedelta(days=70)).isoformat(),
            "trip_type": "round",
        }

    def test_formulario_valido(self):
        watch = watch_from_form(self.base, self.config)
        self.assertEqual(watch.destination, "LIS")
        self.assertEqual(watch.currency, benchmarks.BENCHMARK_CURRENCY)

    def test_destino_fora_da_cesta_e_recusado(self):
        with self.assertRaises(ValueError) as ctx:
            watch_from_form(dict(self.base, destination="MAO"), self.config)
        self.assertIn("cesta", str(ctx.exception))

    def test_data_passada_e_recusada(self):
        with self.assertRaises(ValueError):
            watch_from_form(
                dict(self.base, departure_date=(date.today() - timedelta(days=1)).isoformat()),
                self.config,
            )

    def test_volta_antes_da_ida_e_recusada(self):
        with self.assertRaises(ValueError):
            watch_from_form(
                dict(self.base, return_date=(date.today() + timedelta(days=50)).isoformat()),
                self.config,
            )

    def test_ida_e_volta_exige_volta(self):
        dados = dict(self.base)
        dados.pop("return_date")
        with self.assertRaises(ValueError):
            watch_from_form(dados, self.config)

    def test_somente_ida_dispensa_volta(self):
        dados = dict(self.base, trip_type="oneway")
        dados.pop("return_date")
        self.assertIsNone(watch_from_form(dados, self.config).return_date)

    def test_cabine_invalida_e_recusada(self):
        with self.assertRaises(ValueError):
            watch_from_form(dict(self.base, cabin="LUXO"), self.config)

    def test_flexibilidade_e_limitada(self):
        self.assertLessEqual(watch_from_form(dict(self.base, flex_days="99"), self.config).flex_days, 7)


class TestProvedores(unittest.TestCase):
    def test_padrao_e_o_simulador(self):
        self.assertEqual(get_provider(test_config()).name, "synthetic")

    def test_provedor_desconhecido_explica_as_opcoes(self):
        with self.assertRaises(ProviderError) as ctx:
            get_provider(test_config(provider="inexistente"))
        self.assertIn("synthetic", str(ctx.exception))

    def test_amadeus_sem_credencial_falha_cedo(self):
        with self.assertRaises(ProviderError):
            get_provider(test_config(provider="amadeus"))


class TestPaginas(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        caminho = os.path.join(cls.tmpdir.name, "test.db")
        cls.config = test_config(db_path=caminho)
        provider = SyntheticProvider()
        agora = datetime.now()
        with db.session(caminho) as conn:
            for i in range(6, 0, -1):
                monitor.run_round(
                    conn, cls.config, provider, include_watches=False,
                    now=agora - timedelta(days=i),
                )
            watch = make_watch("LIS", days_ahead=90)
            cls.watch_id = db.insert_watch(conn, watch)
            monitor.run_round(conn, cls.config, provider, now=agora)
        cls.app = create_app(cls.config)
        cls.client = cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        cls.tmpdir.cleanup()

    def test_paginas_respondem(self):
        rotas = ["/", "/alerts", "/benchmarks", "/watches/new", "/health",
                 f"/watch/{self.watch_id}"] + [f"/destino/{c}" for c in benchmarks.BASKET]
        for rota in rotas:
            with self.subTest(rota=rota):
                self.assertEqual(self.client.get(rota).status_code, 200)

    def test_desconhecidos_respondem_404(self):
        self.assertEqual(self.client.get("/destino/XXX").status_code, 404)
        self.assertEqual(self.client.get("/watch/99999").status_code, 404)

    def test_painel_mostra_o_indice(self):
        corpo = self.client.get("/").get_data(as_text=True)
        self.assertIn("Índice de mercado", corpo)
        self.assertIn("cesta", corpo.lower())

    def test_api_da_cesta(self):
        dados = self.client.get("/api/basket").get_json()
        self.assertEqual(len(dados["readings"]), 10)
        self.assertIn("summary", dados)
        self.assertEqual(len(dados["verdicts"]), 10)

    def test_api_do_indice(self):
        self.assertGreaterEqual(len(self.client.get("/api/index").get_json()["series"]), 6)

    def test_api_de_destinos(self):
        dados = self.client.get("/api/destinations").get_json()["destinations"]
        self.assertEqual(len(dados), 10)
        self.assertIn("base_in_use", dados[0])

    def test_api_de_historico_do_destino(self):
        dados = self.client.get("/api/destinations/LIS/history").get_json()
        self.assertGreaterEqual(len(dados["series"]), 6)
        self.assertEqual(self.client.get("/api/destinations/XXX/history").status_code, 404)

    def test_api_cria_e_recusa_viagem(self):
        criada = self.client.post("/api/watches", json={
            "destination": "CUN",
            "departure_date": (date.today() + timedelta(days=40)).isoformat(),
            "return_date": (date.today() + timedelta(days=50)).isoformat(),
        })
        self.assertEqual(criada.status_code, 201)
        recusada = self.client.post("/api/watches", json={"destination": "MAO"})
        self.assertEqual(recusada.status_code, 400)

    def test_api_de_coleta(self):
        dados = self.client.post("/api/collect").get_json()
        self.assertEqual(len(dados["verdicts"]), 10)
        self.assertIn("basket_index", dados)


if __name__ == "__main__":
    unittest.main()
