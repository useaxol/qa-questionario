"""Configuração da aplicação, lida de variáveis de ambiente."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

DEFAULT_DB = os.path.join("data", "flightwatch.db")


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    try:
        return int(raw) if raw is not None else default
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    try:
        return float(raw) if raw is not None else default
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name)
    if raw is None:
        return default
    return raw.lower() in ("1", "true", "yes", "y", "on", "sim")


@dataclass
class Config:
    """Parâmetros de execução do monitor."""

    # Armazenamento
    db_path: str = DEFAULT_DB

    # Coleta
    provider: str = "synthetic"
    currency: str = "BRL"
    collect_interval_minutes: int = 180
    collect_jitter_seconds: int = 90
    request_timeout: int = 25
    max_offers: int = 20

    # Alertas
    alert_cooldown_hours: int = 12
    alert_improve_pct: float = 3.0
    notify_console: bool = True
    notify_file: Optional[str] = os.path.join("data", "alerts.jsonl")
    webhook_url: Optional[str] = None

    # Credenciais Amadeus (provider real)
    amadeus_client_id: Optional[str] = None
    amadeus_client_secret: Optional[str] = None
    amadeus_host: str = "https://test.api.amadeus.com"

    # Servidor web
    host: str = "0.0.0.0"
    port: int = 10001
    secret_key: str = "flightwatch-dev"

    extra: dict = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            db_path=_env("FLIGHTWATCH_DB", DEFAULT_DB),
            provider=_env("FLIGHTWATCH_PROVIDER", "synthetic"),
            currency=_env("FLIGHTWATCH_CURRENCY", "BRL").upper(),
            collect_interval_minutes=_env_int("FLIGHTWATCH_INTERVAL_MIN", 180),
            collect_jitter_seconds=_env_int("FLIGHTWATCH_JITTER_SEC", 90),
            request_timeout=_env_int("FLIGHTWATCH_TIMEOUT", 25),
            max_offers=_env_int("FLIGHTWATCH_MAX_OFFERS", 20),
            alert_cooldown_hours=_env_int("FLIGHTWATCH_ALERT_COOLDOWN_H", 12),
            alert_improve_pct=_env_float("FLIGHTWATCH_ALERT_IMPROVE_PCT", 3.0),
            notify_console=_env_bool("FLIGHTWATCH_NOTIFY_CONSOLE", True),
            notify_file=_env("FLIGHTWATCH_NOTIFY_FILE", os.path.join("data", "alerts.jsonl")),
            webhook_url=_env("FLIGHTWATCH_WEBHOOK_URL"),
            amadeus_client_id=_env("AMADEUS_CLIENT_ID"),
            amadeus_client_secret=_env("AMADEUS_CLIENT_SECRET"),
            amadeus_host=_env("AMADEUS_HOST", "https://test.api.amadeus.com"),
            host=_env("FLIGHTWATCH_HOST", "0.0.0.0"),
            port=_env_int("PORT", _env_int("FLIGHTWATCH_PORT", 10001)),
            secret_key=_env("FLIGHTWATCH_SECRET_KEY", "flightwatch-dev"),
        )
