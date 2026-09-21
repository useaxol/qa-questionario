"""Testes da tabela de benchmark e da recalibração."""
from __future__ import annotations

import unittest
from datetime import date, timedelta

from helpers import memory_db

from flightwatch import benchmarks
from flightwatch.benchmarks import MONTH_NAMES


class TestTabela(unittest.TestCase):
    def test_cesta_tem_dez_destinos(self):
        self.assertEqual(len(benchmarks.BASKET), 10)
        self.assertEqual(len(benchmarks.DESTINATIONS), 10)

    def test_sazonalidade_tem_media_exatamente_um(self):
        """Sazonalidade redistribui o preço pelos meses, sem mudar o nível anual."""
        for code, dest in benchmarks.DESTINATIONS.items():
            with self.subTest(destino=code):
                self.assertEqual(len(dest.seasonal), 12)
                media = sum(dest.seasonal) / 12
                self.assertAlmostEqual(media, 1.0, places=3, msg=f"{code} média {media}")

    def test_todo_destino_tem_banda_e_nota(self):
        for code, dest in benchmarks.DESTINATIONS.items():
            with self.subTest(destino=code):
                self.assertGreater(dest.band_pct, 0)
                self.assertGreater(dest.base_price, 0)
                self.assertTrue(dest.note)
                self.assertEqual(len(dest.cheapest_months), 3)

    def test_meses_baratos_sao_mesmo_os_mais_baratos(self):
        for code, dest in benchmarks.DESTINATIONS.items():
            with self.subTest(destino=code):
                fatores = dict(zip(MONTH_NAMES, dest.seasonal))
                mais_caro_entre_os_baratos = max(fatores[m] for m in dest.cheapest_months)
                outros = [f for m, f in fatores.items() if m not in dest.cheapest_months]
                self.assertLessEqual(mais_caro_entre_os_baratos, min(outros))

    def test_destino_desconhecido_falha_com_mensagem_util(self):
        with self.assertRaises(KeyError) as ctx:
            benchmarks.benchmark("XXX", date.today() + timedelta(days=30), 30)
        self.assertIn("LIS", str(ctx.exception))

    def test_is_covered(self):
        self.assertTrue(benchmarks.is_covered("lis"))
        self.assertFalse(benchmarks.is_covered("XXX"))
        self.assertFalse(benchmarks.is_covered(""))


class TestCalculoDoBenchmark(unittest.TestCase):
    def setUp(self):
        self.ano = date.today().year + 1

    def test_mes_caro_custa_mais_que_mes_barato(self):
        caro = benchmarks.benchmark("LIS", date(self.ano, 12, 20), 90).price
        barato = benchmarks.benchmark("LIS", date(self.ano, 11, 10), 90).price
        self.assertGreater(caro, barato * 1.2)

    def test_comprar_em_cima_da_hora_e_mais_caro(self):
        dep = date(self.ano, 6, 15)
        self.assertGreater(
            benchmarks.benchmark("LIS", dep, 5).price,
            benchmarks.benchmark("LIS", dep, 70).price,
        )

    def test_curva_de_antecedencia_e_continua(self):
        anterior = benchmarks.advance_factor(0)
        for dtd in range(1, 400):
            atual = benchmarks.advance_factor(dtd)
            self.assertLess(abs(atual - anterior), 0.06, f"salto em {dtd} dias")
            anterior = atual

    def test_antecedencia_fora_da_curva_nao_quebra(self):
        self.assertGreater(benchmarks.advance_factor(None), 0)
        self.assertGreater(benchmarks.advance_factor(-50), 0)
        self.assertEqual(benchmarks.advance_factor(9999), benchmarks.ADVANCE_CURVE[-1][1])

    def test_executiva_custa_mais_que_economica(self):
        dep = date(self.ano, 6, 15)
        eco = benchmarks.benchmark("CDG", dep, 60).price
        exe = benchmarks.benchmark("CDG", dep, 60, cabin="BUSINESS").price
        self.assertAlmostEqual(exe / eco, benchmarks.CABIN_FACTOR["BUSINESS"], places=6)

    def test_passageiros_multiplicam_o_benchmark(self):
        dep = date(self.ano, 6, 15)
        um = benchmarks.benchmark("MIA", dep, 60).price
        tres = benchmarks.benchmark("MIA", dep, 60, passengers=3).price
        self.assertAlmostEqual(tres, um * 3, places=6)

    def test_origem_fora_de_sao_paulo_encarece(self):
        dep = date(self.ano, 6, 15)
        self.assertGreater(
            benchmarks.benchmark("LIS", dep, 60, origin="REC").price,
            benchmarks.benchmark("LIS", dep, 60, origin="GRU").price,
        )

    def test_origem_desconhecida_usa_fator_padrao(self):
        self.assertEqual(benchmarks.origin_factor("ZZZ"), benchmarks.DEFAULT_ORIGIN_FACTOR)

    def test_override_de_base_substitui_a_tabela(self):
        dep = date(self.ano, 6, 15)
        padrao = benchmarks.benchmark("LIS", dep, 60)
        dobro = benchmarks.benchmark("LIS", dep, 60, base_override=padrao.base * 2)
        self.assertAlmostEqual(dobro.price, padrao.price * 2, places=6)
        self.assertTrue(dobro.calibrated)
        self.assertFalse(padrao.calibrated)

    def test_decomposicao_reconstroi_o_preco(self):
        b = benchmarks.benchmark("HND", date(self.ano, 3, 20), 75, cabin="BUSINESS", passengers=2)
        reconstruido = b.base * b.seasonal * b.advance * b.cabin * b.origin * b.passengers
        self.assertAlmostEqual(b.price, reconstruido, places=6)


class TestRecalibracao(unittest.TestCase):
    def test_base_implicita_inverte_a_formula(self):
        b = benchmarks.benchmark("LIS", date.today() + timedelta(days=95), 95)
        # Um preço 30% acima do benchmark implica uma base 30% maior.
        implicita = benchmarks.implied_base(b.price * 1.3, b)
        self.assertAlmostEqual(implicita, b.base * 1.3, places=4)

    def test_poucas_cotacoes_bloqueiam(self):
        proposta = benchmarks.propose_calibration("LIS", [5000.0] * 5, [1, 2, 3])
        self.assertFalse(proposta.is_actionable)
        self.assertIn("cotações", proposta.blocked_reason)
        self.assertEqual(proposta.proposed_base, proposta.current_base)

    def test_meses_concentrados_bloqueiam(self):
        """Sem espalhamento a mediana descreveria só a época coletada."""
        proposta = benchmarks.propose_calibration("LIS", [5000.0] * 40, [7, 7, 7])
        self.assertFalse(proposta.is_actionable)
        self.assertIn("mês", proposta.blocked_reason)

    def test_proposta_viavel_move_a_base(self):
        proposta = benchmarks.propose_calibration("LIS", [4600.0] * 40, [1, 4, 7, 10])
        self.assertTrue(proposta.is_actionable)
        self.assertGreater(proposta.proposed_base, proposta.current_base)
        self.assertAlmostEqual(proposta.observed_base, 4600.0)

    def test_passo_e_limitado(self):
        """A base acompanha o mercado; não persegue um período atípico."""
        proposta = benchmarks.propose_calibration("LIS", [40000.0] * 40, [1, 4, 7, 10])
        limite = proposta.current_base * (1 + benchmarks.MAX_CALIBRATION_STEP)
        self.assertAlmostEqual(proposta.proposed_base, limite, places=4)
        self.assertAlmostEqual(proposta.change_pct, 100 * benchmarks.MAX_CALIBRATION_STEP, places=4)

    def test_mediana_ignora_outlier(self):
        valores = [4200.0] * 39 + [999999.0]
        proposta = benchmarks.propose_calibration("LIS", valores, [1, 4, 7, 10])
        self.assertAlmostEqual(proposta.observed_base, 4200.0)


if __name__ == "__main__":
    unittest.main()
