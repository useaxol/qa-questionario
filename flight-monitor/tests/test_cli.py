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


class TestDoctor(unittest.TestCase):
    """O doctor é o comando que separa 'rodou' de 'está medindo de verdade'."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "doctor.db")
        self._env = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        self.tmpdir.cleanup()

    def run_cli(self, *args, **env):
        os.environ.update({k: str(v) for k, v in env.items()})
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(["--db", self.db_path, "doctor", *args])
        return code, buffer.getvalue()

    def test_reporta_consumo_e_metodologia(self):
        code, saida = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("chamadas por rodada", saida)
        self.assertIn("Metodologia", saida)

    def test_avisa_quando_o_consumo_passa_da_cota(self):
        code, saida = self.run_cli("--quota", "100")
        self.assertEqual(code, 0)
        self.assertIn("acima da cota", saida)
        self.assertIn("FLIGHTWATCH_INTERVAL_MIN", saida)

    def test_avisa_horizontes_em_numero_par(self):
        _, saida = self.run_cli(FLIGHTWATCH_PROBE_HORIZONS="45,90")
        self.assertIn("par", saida)
        self.assertIn("ímpar", saida)

    def test_probe_all_cobre_os_dez_destinos(self):
        code, saida = self.run_cli("--probe-all")
        self.assertEqual(code, 0)
        for destino in benchmarks.BASKET:
            self.assertIn(f"GRU→{destino}", saida)
        self.assertIn("10/10 destinos cotados", saida)

    def test_avisa_que_o_simulador_nao_serve_para_comprar(self):
        _, saida = self.run_cli()
        self.assertIn("simula preços", saida)
        self.assertIn("AMADEUS_CLIENT_ID", saida)

    def test_alerta_o_ambiente_de_teste_da_amadeus(self):
        code, saida = self.run_cli(
            FLIGHTWATCH_PROVIDER="amadeus",
            AMADEUS_CLIENT_ID="x", AMADEUS_CLIENT_SECRET="y",
            AMADEUS_HOST="https://test.api.amadeus.com",
        )
        self.assertIn("ambiente de TESTE", saida)
        self.assertIn("api.amadeus.com", saida)

    def test_credencial_ausente_e_problema_nao_aviso(self):
        code, saida = self.run_cli(FLIGHTWATCH_PROVIDER="amadeus",
                                   AMADEUS_CLIENT_ID="", AMADEUS_CLIENT_SECRET="")
        self.assertEqual(code, 1)
        self.assertIn("AMADEUS_CLIENT_ID", saida)
