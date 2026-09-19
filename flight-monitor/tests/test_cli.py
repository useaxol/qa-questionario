"""Testes da linha de comando e do backfill."""
from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, timedelta

from helpers import make_watch, memory_db, test_config

from flightwatch import analytics, db, seed
from flightwatch.cli import main
from flightwatch.providers.synthetic import SyntheticProvider


class TestBackfill(unittest.TestCase):
    def test_backfill_cobre_o_ano_e_varias_antecedencias(self):
        conn = memory_db()
        total = seed.backfill_route(
            conn, SyntheticProvider(), "GRU", "LIS", currency="BRL", days_back=420, step_days=6
        )
        self.assertGreater(total, 300)
        amostras = analytics.samples_from_observations(
            db.route_history(conn, "GRU", "LIS", "round", "ECONOMY", "BRL")
        )
        self.assertGreater(len({s.week for s in amostras}), 40)
        self.assertGreater(len({s.bucket for s in amostras}), 5)

    def test_backfill_da_serie_usa_a_data_da_viagem(self):
        conn = memory_db()
        watch = make_watch(days_ahead=200)
        watch.id = db.insert_watch(conn, watch)
        total = seed.backfill_series(conn, SyntheticProvider(), watch, days_back=90, step_days=10)
        self.assertGreater(total, 5)
        historico = db.watch_history(conn, watch.id)
        self.assertTrue(all(o.departure_date == watch.departure_date for o in historico))
        # A antecedência cai conforme a data da consulta avança.
        antecedencias = [o.days_to_departure for o in historico]
        self.assertEqual(antecedencias, sorted(antecedencias, reverse=True))

    def test_provedor_sem_backfill_recusa(self):
        from flightwatch.providers import ProviderError
        from flightwatch.providers.base import Provider, SearchQuery

        class SemBackfill(Provider):
            name = "sem"
            supports_backfill = False

            def search(self, query: SearchQuery):
                return []

        with self.assertRaises(ProviderError):
            seed.backfill_route(memory_db(), SemBackfill(), "GRU", "LIS")

    def test_bootstrap_grava_referencias_com_peso_menor(self):
        conn = memory_db()
        watch = make_watch(days_ahead=120)
        watch.id = db.insert_watch(conn, watch)
        total = seed.bootstrap_from_metrics(conn, SyntheticProvider(), watch)
        self.assertGreater(total, 0)
        historico = db.route_history(conn, "GRU", "LIS", "round", "ECONOMY", "BRL")
        self.assertTrue(all(o.source == "metric" for o in historico))
        self.assertTrue(all(o.weight < 1.0 for o in historico))


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "cli.db")

    def tearDown(self):
        self.tmpdir.cleanup()

    def run_cli(self, *args):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(["--db", self.db_path, *args])
        return code, buffer.getvalue()

    def test_init_cria_o_banco(self):
        code, saida = self.run_cli("init")
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(self.db_path))
        self.assertIn("Banco pronto", saida)

    def test_add_list_collect_e_report(self):
        ida = (date.today() + timedelta(days=120)).isoformat()
        volta = (date.today() + timedelta(days=134)).isoformat()

        code, _ = self.run_cli("add", "GRU", "LIS", ida, "--return", volta,
                               "--label", "Lisboa", "--backfill", "360")
        self.assertEqual(code, 0)

        code, saida = self.run_cli("list")
        self.assertEqual(code, 0)
        self.assertIn("GRU→LIS", saida)

        code, saida = self.run_cli("collect", "--no-notify")
        self.assertEqual(code, 0)
        self.assertIn("padrão", saida)

        code, saida = self.run_cli("report", "1")
        self.assertEqual(code, 0)
        self.assertIn("Sazonalidade por mês", saida)
        self.assertIn("Curva de antecedência", saida)

    def test_add_recusa_ida_e_volta_sem_volta(self):
        ida = (date.today() + timedelta(days=60)).isoformat()
        code, _ = self.run_cli("add", "GRU", "LIS", ida)
        self.assertEqual(code, 2)

    def test_add_recusa_data_passada(self):
        passado = (date.today() - timedelta(days=5)).isoformat()
        code, _ = self.run_cli("add", "GRU", "LIS", passado, "--oneway")
        self.assertEqual(code, 2)

    def test_report_de_rota_inexistente(self):
        self.run_cli("init")
        code, _ = self.run_cli("report", "999")
        self.assertEqual(code, 2)

    def test_alerts_em_json(self):
        self.run_cli("init")
        code, saida = self.run_cli("alerts", "--json")
        self.assertEqual(code, 0)
        self.assertIn("[]", saida)

    def test_remove(self):
        ida = (date.today() + timedelta(days=60)).isoformat()
        self.run_cli("add", "GRU", "LIS", ida, "--oneway")
        code, _ = self.run_cli("remove", "1")
        self.assertEqual(code, 0)
        _, saida = self.run_cli("list")
        self.assertIn("Nenhuma rota", saida)


if __name__ == "__main__":
    unittest.main()
