"""Testes dos provedores de cotação."""
from __future__ import annotations

import unittest
from datetime import date, timedelta

from helpers import test_config

from flightwatch import airports
from flightwatch.providers import ProviderError, get_provider
from flightwatch.providers.amadeus import parse_iso_duration
from flightwatch.providers.base import SearchQuery
from flightwatch.providers.synthetic import (
    SyntheticProvider, advance_factor, base_price_usd, season_factor,
)


def query(origin="GRU", destination="LIS", days_ahead=90, as_of=None, **kw):
    ref = as_of or date.today()
    departure = ref + timedelta(days=days_ahead)
    return SearchQuery(
        origin=origin,
        destination=destination,
        departure_date=departure,
        return_date=departure + timedelta(days=10),
        currency="BRL",
        as_of=ref,
        **kw,
    )


class TestSimulador(unittest.TestCase):
    def setUp(self):
        self.provider = SyntheticProvider()

    def test_e_deterministico(self):
        q = query()
        primeiro = [o.price for o in self.provider.search(q)]
        segundo = [o.price for o in self.provider.search(q)]
        self.assertEqual(primeiro, segundo)

    def test_ofertas_vem_ordenadas_por_preco(self):
        precos = [o.price for o in self.provider.search(query())]
        self.assertEqual(precos, sorted(precos))

    def test_rota_mais_longa_custa_mais(self):
        curta = self.provider.cheapest(query("CGH", "SDU")).price
        longa = self.provider.cheapest(query("GRU", "SYD")).price
        self.assertGreater(longa, curta * 3)

    def test_nao_cota_data_passada(self):
        q = query(days_ahead=-5)
        self.assertEqual(self.provider.search(q), [])

    def test_respeita_o_limite_de_paradas(self):
        q = query(max_stops=0)
        melhor = self.provider.cheapest(q)
        self.assertEqual(melhor.stops, 0)

    def test_executiva_custa_mais_que_economica(self):
        economica = self.provider.fair_price(query())
        executiva = self.provider.fair_price(query(cabin="BUSINESS"))
        self.assertGreater(executiva, economica * 2)

    def test_preco_por_passageiro_divide_o_total(self):
        oferta = self.provider.cheapest(query(passengers=3))
        self.assertAlmostEqual(oferta.price_per_pax(3), oferta.price / 3, places=6)

    def test_moeda_altera_a_ordem_de_grandeza(self):
        em_reais = self.provider.fair_price(query())
        em_dolares = self.provider.fair_price(
            SearchQuery(
                origin="GRU", destination="LIS",
                departure_date=date.today() + timedelta(days=90),
                return_date=date.today() + timedelta(days=100),
                currency="USD", as_of=date.today(),
            )
        )
        self.assertGreater(em_reais, em_dolares * 3)

    def test_quartis_historicos_sao_ordenados(self):
        metricas = self.provider.price_metrics(query(days_ahead=200))
        self.assertIsNotNone(metricas)
        self.assertLessEqual(metricas["min"], metricas["q1"])
        self.assertLessEqual(metricas["q1"], metricas["median"])
        self.assertLessEqual(metricas["median"], metricas["q3"])
        self.assertLessEqual(metricas["q3"], metricas["max"])


class TestCurvasDoSimulador(unittest.TestCase):
    def test_comprar_em_cima_da_hora_e_mais_caro(self):
        self.assertGreater(advance_factor(2), advance_factor(60))
        self.assertGreater(advance_factor(10), advance_factor(45))

    def test_alta_estacao_e_mais_cara(self):
        ano = date.today().year + 1
        natal = season_factor(date(ano, 12, 22), "GRU", "LIS")
        novembro = season_factor(date(ano, 11, 10), "GRU", "LIS")
        self.assertGreater(natal, novembro)

    def test_sazonalidade_segue_o_hemisferio(self):
        """Para o Chile (verão em janeiro) janeiro é mais caro que julho."""
        ano = date.today().year + 1
        janeiro = season_factor(date(ano, 1, 20), "GRU", "SCL")
        julho = season_factor(date(ano, 7, 20), "GRU", "SCL")
        self.assertGreater(janeiro, julho)

    def test_preco_base_cresce_com_a_distancia(self):
        self.assertGreater(base_price_usd("GRU", "NRT"), base_price_usd("GRU", "EZE"))


class TestRegistroDeProvedores(unittest.TestCase):
    def test_provedor_padrao_e_o_simulador(self):
        self.assertEqual(get_provider(test_config()).name, "synthetic")

    def test_provedor_desconhecido_falha_com_mensagem_util(self):
        with self.assertRaises(ProviderError) as ctx:
            get_provider(test_config(provider="inexistente"))
        self.assertIn("synthetic", str(ctx.exception))

    def test_amadeus_sem_credencial_falha_cedo(self):
        with self.assertRaises(ProviderError):
            get_provider(test_config(provider="amadeus"))


class TestAmadeusHelpers(unittest.TestCase):
    def test_duracao_iso_em_minutos(self):
        self.assertEqual(parse_iso_duration("PT11H35M"), 695)
        self.assertEqual(parse_iso_duration("PT2H"), 120)
        self.assertEqual(parse_iso_duration("P1DT2H30M"), 1590)
        self.assertIsNone(parse_iso_duration(None))
        self.assertIsNone(parse_iso_duration("lixo"))


class TestAeroportos(unittest.TestCase):
    def test_busca_por_codigo_cidade_e_pais(self):
        self.assertEqual(airports.search("GRU")[0].iata, "GRU")
        self.assertTrue(any(a.iata == "LIS" for a in airports.search("lisboa")))
        self.assertTrue(any(a.country == "Japão" for a in airports.search("japao")))

    def test_distancia_conhecida_bate_com_a_realidade(self):
        # GRU-LIS tem cerca de 7.900 km.
        self.assertAlmostEqual(airports.distance_km("GRU", "LIS"), 7900, delta=300)

    def test_aeroporto_desconhecido_nao_quebra(self):
        self.assertIsNone(airports.get("ZZZ"))
        self.assertEqual(airports.distance_km("ZZZ", "LIS"), airports.FALLBACK_DISTANCE_KM)

    def test_cobertura_global(self):
        paises = {a.country for a in airports.all_airports()}
        self.assertGreater(len(paises), 50)
        self.assertGreater(len(airports.AIRPORTS), 150)


if __name__ == "__main__":
    unittest.main()
