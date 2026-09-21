"""Testes do índice, da cesta e da detecção de distorção."""
from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta

from helpers import synthetic_basket

from flightwatch import benchmarks, indexing
from flightwatch.indexing import INDEX_BASE, Reading


class TestIndice(unittest.TestCase):
    def test_preco_igual_ao_benchmark_da_cem(self):
        self.assertEqual(indexing.price_index(1000, 1000), 100.0)

    def test_metade_do_benchmark_da_cinquenta(self):
        self.assertEqual(indexing.price_index(500, 1000), 50.0)

    def test_benchmark_zero_nao_divide_por_zero(self):
        self.assertEqual(indexing.price_index(500, 0), INDEX_BASE)

    def test_reading_calcula_o_indice_sozinha(self):
        dep = date.today() + timedelta(days=60)
        bench = benchmarks.benchmark("LIS", dep, 60)
        reading = indexing.build_reading("LIS", bench.price * 0.8, dep, 60)
        self.assertAlmostEqual(reading.index, 80.0, places=4)
        self.assertAlmostEqual(reading.gap_pct, -20.0, places=4)


class TestCesta(unittest.TestCase):
    def test_indice_da_cesta_e_a_mediana(self):
        basket, _ = synthetic_basket({"LIS": 50.0}, default_index=100.0)
        # Um destino despencando não pode arrastar o índice de mercado.
        self.assertAlmostEqual(basket.index, 100.0, places=4)
        self.assertEqual(basket.size, 10)

    def test_cesta_precisa_de_minimo_de_leituras(self):
        dep = date.today() + timedelta(days=60)
        poucas = [
            indexing.build_reading(code, benchmarks.benchmark(code, dep, 60).price, dep, 60)
            for code in list(benchmarks.BASKET)[:3]
        ]
        self.assertFalse(indexing.build_basket(poucas).is_valid)
        self.assertTrue(synthetic_basket()[0].is_valid)

    def test_distorcao_e_a_distancia_ate_a_cesta(self):
        basket, _ = synthetic_basket({"LIS": 78.0}, default_index=101.0)
        self.assertAlmostEqual(basket.distortion_of("LIS"), 78.0 - basket.index, places=3)
        self.assertIsNone(basket.distortion_of("XXX"))

    def test_cesta_invalida_nao_reporta_distorcao(self):
        dep = date.today() + timedelta(days=60)
        basket = indexing.build_basket(
            [indexing.build_reading("LIS", benchmarks.benchmark("LIS", dep, 60).price, dep, 60)]
        )
        self.assertIsNone(basket.distortion_of("LIS"))

    def test_ranking_vai_do_mais_barato_ao_mais_caro(self):
        basket, _ = synthetic_basket({"LIS": 80.0, "HND": 120.0})
        ranked = basket.ranked()
        self.assertEqual(ranked[0].destination, "LIS")
        self.assertEqual(ranked[-1].destination, "HND")


class TestVeredito(unittest.TestCase):
    """Os dois cenários que o app existe para separar."""

    def setUp(self):
        self.dep = date.today() + timedelta(days=60)

    def avaliar(self, index_alvo, index_mercado=100.0, destino="LIS"):
        basket, readings = synthetic_basket(
            {destino: index_alvo}, default_index=index_mercado
        )
        reading = next(r for r in readings if r.destination == destino)
        return indexing.evaluate(reading, basket), basket

    def test_preco_no_benchmark_e_normal(self):
        verdict, _ = self.avaliar(100.0)
        self.assertEqual(verdict.level, 0)
        self.assertFalse(verdict.is_alert)
        self.assertEqual(verdict.driver, "none")

    def test_queda_pequena_nao_alerta(self):
        verdict, _ = self.avaliar(96.0)
        self.assertFalse(verdict.is_alert)

    def test_destino_descolado_da_cesta_e_distorcao(self):
        """Nove destinos em 101 e um em 78: o sinal é do destino."""
        verdict, _ = self.avaliar(78.0, index_mercado=101.0)
        self.assertTrue(verdict.is_alert)
        self.assertGreaterEqual(verdict.level, 2)
        self.assertIn(verdict.driver, ("distortion", "both"))
        self.assertLess(verdict.distortion, -15)
        self.assertIn("distorção", verdict.label)

    def test_mercado_inteiro_barato_nao_e_distorcao(self):
        """Todos em 80: é movimento de mercado, e o rótulo precisa dizer isso."""
        verdict, _ = self.avaliar(80.0, index_mercado=80.0)
        self.assertTrue(verdict.is_alert)
        self.assertEqual(verdict.driver, "benchmark")
        self.assertAlmostEqual(verdict.distortion, 0.0, places=3)
        self.assertNotIn("distorção", verdict.label)
        self.assertIn("benchmark", verdict.label)

    def test_texto_explica_qual_sinal_mandou(self):
        distorcido, _ = self.avaliar(78.0, index_mercado=101.0)
        self.assertTrue(any("abaixo do mercado" in r for r in distorcido.reasons))
        mercado, _ = self.avaliar(80.0, index_mercado=80.0)
        self.assertTrue(any("movimento é de mercado" in r for r in mercado.reasons))

    def test_queda_absurda_e_marcada_como_suspeita(self):
        verdict, _ = self.avaliar(35.0, index_mercado=100.0)
        self.assertEqual(verdict.level, 4)
        self.assertTrue(any("tarifa-erro" in r for r in verdict.reasons))

    def test_preco_muito_acima_e_sinalizado(self):
        verdict, _ = self.avaliar(135.0, index_mercado=100.0)
        self.assertEqual(verdict.level, -1)
        self.assertFalse(verdict.is_alert)

    def test_banda_larga_exige_desvio_maior(self):
        """EZE tem banda ±16 e LIS ±12: o mesmo índice não vale o mesmo alerta."""
        estreito, _ = self.avaliar(86.0, index_mercado=100.0, destino="LIS")
        largo, _ = self.avaliar(86.0, index_mercado=100.0, destino="EZE")
        self.assertGreater(estreito.signal, largo.signal)

    def test_nota_cresce_com_o_sinal(self):
        fraco, _ = self.avaliar(95.0)
        forte, _ = self.avaliar(72.0)
        self.assertGreater(forte.score, fraco.score)
        self.assertLessEqual(forte.score, 100.0)

    def test_preco_alvo_alerta_mesmo_sem_sinal(self):
        basket, readings = synthetic_basket(default_index=100.0)
        reading = next(r for r in readings if r.destination == "LIS")
        verdict = indexing.evaluate(reading, basket, target_price=reading.price * 1.05)
        self.assertTrue(verdict.is_alert)
        self.assertTrue(any("preço-alvo" in r for r in verdict.reasons))

    def test_sem_cesta_usa_so_o_benchmark(self):
        dep = self.dep
        bench = benchmarks.benchmark("LIS", dep, 60)
        reading = indexing.build_reading("LIS", bench.price * 0.8, dep, 60)
        verdict = indexing.evaluate(reading, None)
        self.assertIsNone(verdict.distortion)
        self.assertEqual(verdict.signal_distortion, 0.0)
        self.assertTrue(any("Cesta ainda incompleta" in r for r in verdict.reasons))

    def test_serializacao_traz_os_dois_sinais(self):
        verdict, _ = self.avaliar(78.0, index_mercado=101.0)
        data = verdict.as_dict()
        for key in ("index", "basket_index", "distortion", "signal_benchmark",
                    "signal_distortion", "driver", "level", "score"):
            self.assertIn(key, data)


class TestLeituraDeMercado(unittest.TestCase):
    def test_estados_do_mercado(self):
        for index, esperado in ((80, "mercado barato"), (94, "levemente abaixo"),
                                (100, "em linha"), (108, "levemente acima"),
                                (125, "mercado caro")):
            with self.subTest(index=index):
                basket, _ = synthetic_basket(default_index=index)
                self.assertEqual(indexing.market_summary(basket)["state"], esperado)

    def test_resumo_aponta_o_mais_barato(self):
        basket, _ = synthetic_basket({"CUN": 70.0}, default_index=100.0)
        self.assertEqual(indexing.market_summary(basket)["cheapest"], "CUN")

    def test_cesta_vazia_nao_quebra(self):
        self.assertEqual(indexing.market_summary(indexing.build_basket([]))["state"], "sem dados")

    def test_avaliacao_da_cesta_ordena_pelo_sinal(self):
        basket, _ = synthetic_basket({"LIS": 75.0, "MAD": 88.0}, default_index=101.0)
        verdicts = indexing.evaluate_basket(basket)
        self.assertEqual(verdicts[0].destination, "LIS")
        self.assertGreaterEqual(verdicts[0].signal, verdicts[1].signal)


if __name__ == "__main__":
    unittest.main()
