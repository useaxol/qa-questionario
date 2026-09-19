"""Testes do núcleo estatístico."""
from __future__ import annotations

import math
import unittest
from datetime import date, datetime, timedelta

from helpers import memory_db, seeded_route

from flightwatch import analytics, db
from flightwatch.providers.synthetic import season_factor


class TestRobustStats(unittest.TestCase):
    def test_weighted_median_respeita_pesos(self):
        self.assertEqual(analytics.weighted_median([(1, 1), (2, 1), (3, 1)]), 2)
        # O peso alto no 10 desloca a mediana para lá.
        self.assertEqual(analytics.weighted_median([(1, 1), (2, 1), (10, 20)]), 10)

    def test_median_ignora_outlier_extremo(self):
        valores = [100, 102, 98, 101, 99, 100000]
        self.assertLess(analytics.median(valores), 200)

    def test_robust_scale_positivo(self):
        self.assertGreater(analytics.robust_scale([1.0, 1.2, 0.8, 1.1, 0.9]), 0)

    def test_weighted_median_vazio_falha(self):
        with self.assertRaises(ValueError):
            analytics.weighted_median([])

    def test_percentile_of(self):
        valores = [10, 20, 30, 40]
        self.assertEqual(analytics.percentile_of(valores, 10), 75.0)
        self.assertEqual(analytics.percentile_of(valores, 40), 0.0)


class TestCalendario(unittest.TestCase):
    def test_semana_do_ano_normalizada(self):
        for dia in (date(2020, 12, 31), date(2021, 1, 1), date(2026, 6, 15)):
            self.assertTrue(1 <= analytics.week_of_year(dia) <= 52)

    def test_distancia_circular_entre_semanas(self):
        self.assertEqual(analytics.week_distance(1, 52), 1)
        self.assertEqual(analytics.week_distance(2, 50), 4)
        self.assertEqual(analytics.week_distance(10, 10), 0)

    def test_faixas_de_antecedencia(self):
        self.assertEqual(analytics.advance_bucket(0), "0-3")
        self.assertEqual(analytics.advance_bucket(45), "31-45")
        self.assertEqual(analytics.advance_bucket(5000), "181+")
        self.assertEqual(analytics.advance_bucket(None), "0-3")
        self.assertEqual(analytics.advance_bucket(-10), "0-3")


class TestAjusteDoModelo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = memory_db()
        seeded_route(cls.conn)
        history = db.route_history(cls.conn, "GRU", "LIS", "round", "ECONOMY", "BRL")
        cls.samples = analytics.samples_from_observations(history)
        cls.model = analytics.fit_route_model(cls.samples)

    def test_modelo_ajustado_com_confianca_alta(self):
        self.assertTrue(self.model.fitted)
        self.assertEqual(self.model.confidence(), "high")
        self.assertGreater(self.model.n, 300)
        self.assertGreater(self.model.base_price, 0)

    def test_escala_residual_dentro_dos_limites(self):
        self.assertGreaterEqual(self.model.residual_scale, analytics.MIN_RESIDUAL_SCALE)
        self.assertLessEqual(self.model.residual_scale, analytics.MAX_RESIDUAL_SCALE)

    def test_recupera_a_sazonalidade_verdadeira(self):
        """O modelo deve reencontrar a sazonalidade que o simulador embutiu."""
        ano = date.today().year + 1
        estimado = dict(self.model.monthly_curve(ano))
        verdadeiro = {}
        for mes in range(1, 13):
            fatores = [season_factor(date(ano, mes, dia), "GRU", "LIS") for dia in (5, 15, 25)]
            verdadeiro[mes] = 100 * (sum(fatores) / len(fatores) - 1)

        xs = [estimado[m] for m in range(1, 13)]
        ys = [verdadeiro[m] for m in range(1, 13)]
        mx, my = sum(xs) / 12, sum(ys) / 12
        cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
        sx = math.sqrt(sum((a - mx) ** 2 for a in xs))
        sy = math.sqrt(sum((b - my) ** 2 for b in ys))
        correlacao = cov / (sx * sy)
        self.assertGreater(correlacao, 0.6, f"correlação sazonal baixa: {correlacao:.2f}")

    def test_curva_de_antecedencia_sobe_perto_da_partida(self):
        curva = dict(self.model.advance_curve())
        self.assertGreater(curva["8-14"], curva["61-90"])
        self.assertGreater(curva["15-21"], curva["46-60"])

    def test_previsao_reage_a_epoca_do_ano(self):
        ano = date.today().year + 1
        natal = self.model.predict(date(ano, 12, 24), 120)
        novembro = self.model.predict(date(ano, 11, 10), 120)
        self.assertGreater(natal, novembro)


class TestDiagnostico(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = memory_db()
        seeded_route(cls.conn)
        history = db.route_history(cls.conn, "GRU", "LIS", "round", "ECONOMY", "BRL")
        cls.samples = analytics.samples_from_observations(history)
        cls.model = analytics.fit_route_model(cls.samples)
        cls.partida = date.today() + timedelta(days=120)
        cls.esperado = cls.model.predict(cls.partida, 120)

    def avaliar(self, preco):
        return analytics.assess(preco, self.partida, 120, self.samples, self.model, "BRL")

    def test_preco_esperado_e_normal(self):
        resultado = self.avaliar(self.esperado)
        self.assertEqual(resultado.severity, 0)
        self.assertFalse(resultado.is_deal)
        self.assertAlmostEqual(resultado.z_score, 0.0, places=6)

    def test_queda_pequena_nao_vira_alerta(self):
        self.assertFalse(self.avaliar(self.esperado * 0.96).is_deal)

    def test_queda_grande_vira_oportunidade(self):
        resultado = self.avaliar(self.esperado * 0.70)
        self.assertTrue(resultado.is_deal)
        self.assertGreaterEqual(resultado.severity, 2)
        self.assertGreater(resultado.discount_pct, 25)
        self.assertGreater(resultado.deal_score, 70)

    def test_queda_absurda_e_marcada_como_suspeita(self):
        resultado = self.avaliar(self.esperado * 0.30)
        self.assertEqual(resultado.severity, 4)
        self.assertEqual(resultado.verdict, "suspicious_low")

    def test_preco_alto_e_sinalizado(self):
        self.assertEqual(self.avaliar(self.esperado * 1.45).severity, -1)

    def test_sinal_do_delta_e_intuitivo(self):
        caro = self.avaliar(self.esperado * 1.2)
        self.assertGreater(caro.delta_pct, 0)
        self.assertIn("acima", caro.delta_label)
        barato = self.avaliar(self.esperado * 0.8)
        self.assertLess(barato.delta_pct, 0)
        self.assertIn("abaixo", barato.delta_label)

    def test_percentil_aumenta_conforme_o_preco_cai(self):
        self.assertGreater(
            self.avaliar(self.esperado * 0.75).percentile,
            self.avaliar(self.esperado * 1.05).percentile,
        )

    def test_justificativas_sempre_presentes(self):
        resultado = self.avaliar(self.esperado * 0.75)
        self.assertTrue(resultado.reasons)
        self.assertTrue(any("esperado" in r for r in resultado.reasons))


class TestHistoricoCurto(unittest.TestCase):
    def test_sem_historico_nenhum_veredito(self):
        resultado = analytics.assess(1000.0, date.today() + timedelta(days=60), 60, [], None, "BRL")
        self.assertEqual(resultado.verdict, "insufficient_data")
        self.assertEqual(resultado.confidence, "none")
        self.assertFalse(resultado.is_deal)

    def test_historico_curto_usa_comparacao_relativa(self):
        partida = date.today() + timedelta(days=60)
        amostras = [
            analytics.Sample(
                price=1000.0,
                log_price=math.log(1000.0),
                week=analytics.week_of_year(partida),
                bucket="46-60",
                departure_date=partida,
                observed_at=datetime.now() - timedelta(days=i),
            )
            for i in range(5)
        ]
        resultado = analytics.assess(700.0, partida, 60, amostras, None, "BRL")
        self.assertEqual(resultado.method, "relative")
        self.assertEqual(resultado.confidence, "low")
        self.assertTrue(resultado.is_deal)

    def test_pouca_historia_exige_sinal_mais_forte(self):
        """Com confiança baixa, o mesmo z-score não deve alertar."""
        self.assertEqual(analytics._classify(-1.2, 12.0, "high"), 1)
        self.assertEqual(analytics._classify(-1.2, 12.0, "low"), 0)


if __name__ == "__main__":
    unittest.main()
