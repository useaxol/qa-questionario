"""Testes da linha de comando."""
from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, timedelta

from helpers import test_config

from flightwatch import benchmarks
from flightwatch.cli import main


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
        self.assertIn("LIS", saida)

    def test_table_imprime_os_dez_destinos(self):
        code, saida = self.run_cli("table")
        self.assertEqual(code, 0)
        for code_iata in benchmarks.BASKET:
            self.assertIn(code_iata, saida)

    def test_doctor_reporta_configuracao_e_cota(self):
        code, saida = self.run_cli("doctor")
        self.assertEqual(code, 0)
        self.assertIn("chamadas por rodada", saida)
        self.assertIn("Metodologia", saida)
        self.assertIn("simula preços", saida)  # aviso do provedor sintético

    def test_measure_mede_a_cesta(self):
        code, saida = self.run_cli("measure", "--no-notify")
        self.assertEqual(code, 0)
        self.assertIn("Índice de mercado", saida)
        for code_iata in benchmarks.BASKET:
            self.assertIn(code_iata, saida)

    def test_basket_mostra_a_ultima_medicao(self):
        self.run_cli("measure", "--no-notify")
        code, saida = self.run_cli("basket")
        self.assertEqual(code, 0)
        self.assertIn("Índice de mercado", saida)

    def test_basket_sem_medicao_orienta(self):
        code, saida = self.run_cli("basket")
        self.assertEqual(code, 0)
        self.assertIn("measure", saida)

    def test_destination_detalha_um_destino(self):
        self.run_cli("measure", "--no-notify")
        code, saida = self.run_cli("destination", "lis")
        self.assertEqual(code, 0)
        self.assertIn("Sazonalidade", saida)
        self.assertIn("Preço-base", saida)

    def test_destination_fora_da_cesta_falha(self):
        code, _ = self.run_cli("destination", "MAO")
        self.assertEqual(code, 2)

    def test_add_list_e_remove(self):
        ida = (date.today() + timedelta(days=90)).isoformat()
        volta = (date.today() + timedelta(days=100)).isoformat()
        code, saida = self.run_cli("add", "LIS", ida, "--return", volta, "--label", "Lisboa")
        self.assertEqual(code, 0)
        self.assertIn("Benchmark", saida)

        code, saida = self.run_cli("list")
        self.assertEqual(code, 0)
        self.assertIn("GRU→LIS", saida)

        code, _ = self.run_cli("remove", "1")
        self.assertEqual(code, 0)
        _, saida = self.run_cli("list")
        self.assertIn("Nenhuma viagem", saida)

    def test_add_recusa_destino_fora_da_cesta(self):
        ida = (date.today() + timedelta(days=60)).isoformat()
        code, _ = self.run_cli("add", "MAO", ida, "--oneway")
        self.assertEqual(code, 2)

    def test_add_recusa_data_passada(self):
        passado = (date.today() - timedelta(days=5)).isoformat()
        code, _ = self.run_cli("add", "LIS", passado, "--oneway")
        self.assertEqual(code, 2)

    def test_add_exige_volta_em_ida_e_volta(self):
        ida = (date.today() + timedelta(days=60)).isoformat()
        code, _ = self.run_cli("add", "LIS", ida)
        self.assertEqual(code, 2)

    def test_recalibrate_dry_run_nao_aplica(self):
        self.run_cli("measure", "--no-notify")
        code, saida = self.run_cli("recalibrate", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("Simulação", saida)

    def test_reset_calibration(self):
        code, saida = self.run_cli("reset-calibration")
        self.assertEqual(code, 0)
        self.assertIn("tabela do código", saida)

    def test_alerts_em_json(self):
        self.run_cli("init")
        code, saida = self.run_cli("alerts", "--json")
        self.assertEqual(code, 0)
        self.assertIn("[]", saida)

    def test_demo_monta_serie_e_viagens(self):
        code, saida = self.run_cli("demo", "--rounds", "8")
        self.assertEqual(code, 0)
        self.assertIn("Índice de mercado", saida)
        _, lista = self.run_cli("list")
        self.assertIn("GRU→LIS", lista)

    def test_demo_nao_sobrescreve_sem_force(self):
        self.run_cli("demo", "--rounds", "4")
        code, saida = self.run_cli("demo", "--rounds", "4")
        self.assertEqual(code, 1)
        self.assertIn("--force", saida)

    def test_purge(self):
        self.run_cli("measure", "--no-notify")
        code, saida = self.run_cli("purge", "--keep-days", "0")
        self.assertEqual(code, 0)
        self.assertIn("removidas", saida)


if __name__ == "__main__":
    unittest.main()
