"""Registro de provedores de cotação."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .base import Offer, Provider, ProviderError, SearchQuery
from .synthetic import SyntheticProvider

if TYPE_CHECKING:  # pragma: no cover
    from ..config import Config

__all__ = [
    "Offer",
    "Provider",
    "ProviderError",
    "SearchQuery",
    "SyntheticProvider",
    "get_provider",
    "available_providers",
]


def available_providers() -> tuple:
    return ("synthetic", "amadeus")


def get_provider(config: "Config") -> Provider:
    """Instancia o provedor configurado em FLIGHTWATCH_PROVIDER."""
    name = (config.provider or "synthetic").strip().lower()
    if name in ("synthetic", "sim", "demo"):
        return SyntheticProvider()
    if name == "amadeus":
        from .amadeus import AmadeusProvider

        return AmadeusProvider(
            client_id=config.amadeus_client_id or "",
            client_secret=config.amadeus_client_secret or "",
            host=config.amadeus_host,
            timeout=config.request_timeout,
        )
    raise ProviderError(
        f"Provedor desconhecido: {name!r}. Disponíveis: {', '.join(available_providers())}."
    )
