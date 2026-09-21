"""Testes do provedor Amadeus contra respostas no formato real da API.

O ambiente de desenvolvimento não alcança a API da Amadeus, então o contrato é
verificado contra fixtures no formato documentado do Flight Offers Search v2.
Isso cobre o que mais quebra na virada para produção: o parsing da resposta e o
tratamento dos erros de credencial e de cota.
"""
from __future__ import annotations

import unittest
from datetime import date, timedelta
from unittest import mock

from helpers import test_config

from flightwatch.providers import ProviderError
from flightwatch.providers.amadeus import AmadeusProvider, parse_iso_duration
from flightwatch.providers.base import SearchQuery

TOKEN_RESPONSE = {
    "type": "amadeusOAuth2Token",
    "access_token": "abc123",
    "expires_in": 1799,
    "state": "approved",
}

# Formato do GET /v2/shopping/flight-offers (Flight Offers Search v2).
OFFERS_RESPONSE = {
    "meta": {"count": 2},
    "data": [
        {
            "type": "flight-offer",
            "id": "1",
            "source": "GDS",
            "oneWay": False,
            "numberOfBookableSeats": 9,
            "itineraries": [
                {
                    "duration": "PT11H35M",
                    "segments": [
                        {
                            "departure": {"iataCode": "GRU", "terminal": "3",
                                          "at": "2026-11-05T22:30:00"},
                            "arrival": {"iataCode": "LIS", "terminal": "1",
                                        "at": "2026-11-06T11:05:00"},
                            "carrierCode": "TP", "number": "088",
                            "duration": "PT9H35M", "id": "1", "numberOfStops": 0,
                        }
                    ],
                },
                {
                    "duration": "PT12H10M",
                    "segments": [
                        {
                            "departure": {"iataCode": "LIS", "at": "2026-11-19T10:00:00"},
                            "arrival": {"iataCode": "GRU", "at": "2026-11-19T18:10:00"},
                            "carrierCode": "TP", "number": "089", "id": "2",
                        }
                    ],
                },
            ],
            "price": {
                "currency": "BRL", "total": "4235.18", "base": "2950.00",
                "fees": [{"amount": "0.00", "type": "TICKETING"}],
                "grandTotal": "4235.18",
            },
            "validatingAirlineCodes": ["TP"],
        },
        {
            "type": "flight-offer",
            "id": "2",
            "itineraries": [
                {
                    "duration": "PT17H20M",
                    "segments": [
                        {
                            "departure": {"iataCode": "GRU", "at": "2026-11-05T18:00:00"},
                            "arrival": {"iataCode": "MAD", "at": "2026-11-06T09:30:00"},
                            "carrierCode": "IB", "id": "1",
                        },
                        {
                            "departure": {"iataCode": "MAD", "at": "2026-11-06T12:00:00"},
                            "arrival": {"iataCode": "LIS", "at": "2026-11-06T12:20:00"},
                            "carrierCode": "IB", "id": "2",
                        },
                    ],
                }
            ],
            "price": {"currency": "BRL", "total": "3890.00", "grandTotal": "3890.00"},
            "validatingAirlineCodes": ["IB"],
        },
    ],
    "dictionaries": {"carriers": {"TP": "TAP PORTUGAL", "IB": "IBERIA"}},
}


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


def build_query(**overrides) -> SearchQuery:
    departure = date.today() + timedelta(days=60)
    defaults = dict(
        origin="GRU", destination="LIS", departure_date=departure,
        return_date=departure + timedelta(days=14), currency="BRL",
        max_offers=20, as_of=date.today(),
    )
    defaults.update(overrides)
    return SearchQuery(**defaults)


class TestCredenciais(unittest.TestCase):
    def test_sem_credencial_falha_antes_de_qualquer_chamada(self):
        with self.assertRaises(ProviderError) as ctx:
            AmadeusProvider(client_id="", client_secret="")
        self.assertIn("AMADEUS_CLIENT_ID", str(ctx.exception))

    def test_credencial_recusada_explica_o_status(self):
        provider = AmadeusProvider("id", "secret")
        fake = mock.Mock()
        fake.post.return_value = FakeResponse(401, text='{"error":"invalid_client"}')
        with mock.patch("flightwatch.providers.amadeus.requests", fake):
            with self.assertRaises(ProviderError) as ctx:
                provider.search(build_query())
        self.assertIn("401", str(ctx.exception))
        self.assertIn("invalid_client", str(ctx.exception))

    def test_token_e_reaproveitado_entre_consultas(self):
        """Uma chamada de token por janela, não uma por consulta."""
        provider = AmadeusProvider("id", "secret")
        fake = mock.Mock()
        fake.post.return_value = FakeResponse(200, TOKEN_RESPONSE)
        fake.get.return_value = FakeResponse(200, OFFERS_RESPONSE)
        with mock.patch("flightwatch.providers.amadeus.requests", fake):
            provider.search(build_query())
            provider.search(build_query(destination="MAD"))
        self.assertEqual(fake.post.call_count, 1)
        self.assertEqual(fake.get.call_count, 2)


class TestParsingDaResposta(unittest.TestCase):
    def setUp(self):
        self.provider = AmadeusProvider("id", "secret")
        self.fake = mock.Mock()
        self.fake.post.return_value = FakeResponse(200, TOKEN_RESPONSE)
        self.fake.get.return_value = FakeResponse(200, OFFERS_RESPONSE)

    def search(self, **overrides):
        with mock.patch("flightwatch.providers.amadeus.requests", self.fake):
            return self.provider.search(build_query(**overrides))

    def test_le_as_duas_ofertas(self):
        self.assertEqual(len(self.search()), 2)

    def test_preco_vem_do_grand_total(self):
        offers = self.search()
        self.assertAlmostEqual(offers[0].price, 4235.18)
        self.assertEqual(offers[0].currency, "BRL")

    def test_paradas_saem_do_numero_de_trechos(self):
        direto, com_conexao = self.search()
        self.assertEqual(direto.stops, 0)
        self.assertEqual(com_conexao.stops, 1)

    def test_duracao_da_ida_em_minutos(self):
        self.assertEqual(self.search()[0].duration_minutes, 695)  # PT11H35M

    def test_companhia_vem_do_validating_airline(self):
        self.assertEqual([o.airline for o in self.search()], ["TP", "IB"])

    def test_data_de_ida_vem_do_primeiro_trecho(self):
        self.assertEqual(self.search()[0].departure_date, date(2026, 11, 5))

    def test_mais_barata_respeita_o_limite_de_paradas(self):
        with mock.patch("flightwatch.providers.amadeus.requests", self.fake):
            melhor = self.provider.cheapest(build_query(max_stops=0))
        self.assertEqual(melhor.stops, 0)

    def test_parametros_enviados_batem_com_a_consulta(self):
        self.search(passengers=2, cabin="BUSINESS", max_stops=0)
        params = self.fake.get.call_args.kwargs["params"]
        self.assertEqual(params["originLocationCode"], "GRU")
        self.assertEqual(params["destinationLocationCode"], "LIS")
        self.assertEqual(params["adults"], 2)
        self.assertEqual(params["currencyCode"], "BRL")
        self.assertEqual(params["travelClass"], "BUSINESS")
        self.assertEqual(params["nonStop"], "true")
        self.assertIn("returnDate", params)

    def test_somente_ida_nao_manda_data_de_volta(self):
        self.search(trip_type="oneway", return_date=None)
        self.assertNotIn("returnDate", self.fake.get.call_args.kwargs["params"])

    def test_economica_nao_manda_travel_class(self):
        """O padrão da API já é econômica; mandar o parâmetro só restringe à toa."""
        self.search()
        self.assertNotIn("travelClass", self.fake.get.call_args.kwargs["params"])

    def test_oferta_quebrada_e_descartada_sem_derrubar_as_outras(self):
        payload = {"data": [{"id": "1"}, OFFERS_RESPONSE["data"][0]]}
        self.fake.get.return_value = FakeResponse(200, payload)
        offers = self.search()
        self.assertEqual(len(offers), 1)

    def test_resposta_vazia_devolve_lista_vazia(self):
        self.fake.get.return_value = FakeResponse(200, {"data": []})
        self.assertEqual(self.search(), [])
        with mock.patch("flightwatch.providers.amadeus.requests", self.fake):
            self.assertIsNone(self.provider.cheapest(build_query()))


class TestErrosDeOperacao(unittest.TestCase):
    def setUp(self):
        self.provider = AmadeusProvider("id", "secret")
        self.fake = mock.Mock()
        self.fake.post.return_value = FakeResponse(200, TOKEN_RESPONSE)

    def test_limite_de_requisicoes_e_identificado(self):
        self.fake.get.return_value = FakeResponse(429, text="Too many requests")
        with mock.patch("flightwatch.providers.amadeus.requests", self.fake):
            with self.assertRaises(ProviderError) as ctx:
                self.provider.search(build_query())
        self.assertIn("429", str(ctx.exception))
        self.assertIn("limite", str(ctx.exception).lower())

    def test_erro_de_cota_traz_o_corpo_da_resposta(self):
        self.fake.get.return_value = FakeResponse(
            400, text='{"errors":[{"code":4926,"detail":"Quota exceeded"}]}'
        )
        with mock.patch("flightwatch.providers.amadeus.requests", self.fake):
            with self.assertRaises(ProviderError) as ctx:
                self.provider.search(build_query())
        self.assertIn("Quota exceeded", str(ctx.exception))

    def test_falha_de_rede_vira_provider_error(self):
        self.fake.get.side_effect = OSError("connection reset")
        with mock.patch("flightwatch.providers.amadeus.requests", self.fake):
            with self.assertRaises(ProviderError) as ctx:
                self.provider.search(build_query())
        self.assertIn("rede", str(ctx.exception).lower())

    def test_data_passada_e_recusada_com_orientacao(self):
        """A Amadeus só cota hoje; o erro precisa dizer o que fazer."""
        with self.assertRaises(ProviderError) as ctx:
            self.provider.search(build_query(as_of=date.today() - timedelta(days=30)))
        self.assertIn("synthetic", str(ctx.exception))


class TestDuracaoISO(unittest.TestCase):
    def test_formatos_da_api(self):
        self.assertEqual(parse_iso_duration("PT11H35M"), 695)
        self.assertEqual(parse_iso_duration("PT2H"), 120)
        self.assertEqual(parse_iso_duration("PT45M"), 45)
        self.assertEqual(parse_iso_duration("P1DT2H30M"), 1590)
        self.assertIsNone(parse_iso_duration(None))
        self.assertIsNone(parse_iso_duration("lixo"))


if __name__ == "__main__":
    unittest.main()
