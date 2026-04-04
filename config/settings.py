"""
Centralized Settings Configuration

Uses pydantic-settings for type-safe environment variable management.
Loads from .env file (create from .env.example).
"""

from functools import lru_cache
from typing import List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """Database configuration settings."""

    model_config = SettingsConfigDict(env_prefix="DB_", env_file=".env", env_file_encoding="utf-8", extra="ignore")

    host: str = Field(default="localhost", description="Database host")
    port: int = Field(default=3306, description="Database port")
    user: str = Field(default="", description="Database username")
    password: str = Field(default="", description="Database password")
    name: str = Field(default="investments", description="Database name")


class PostgresSettings(BaseSettings):
    """PostgreSQL specific configuration."""

    model_config = SettingsConfigDict(env_prefix="POSTGRES_", env_file=".env", env_file_encoding="utf-8", extra="ignore")

    host: str = Field(default="localhost")
    port: int = Field(default=5432)
    user: str = Field(default="")
    password: str = Field(default="")
    db: str = Field(default="investments")


class HFTPostgresSettings(BaseSettings):
    """HFT-specific PostgreSQL configuration (marketdata)."""

    model_config = SettingsConfigDict(env_prefix="HFT_DB_", env_file=".env", env_file_encoding="utf-8", extra="ignore")

    host: str = Field(default="100.112.16.115", description="HFT PostgreSQL host")
    port: int = Field(default=5432, description="HFT PostgreSQL port")
    user: str = Field(default="postgres", description="HFT PostgreSQL user")
    password: str = Field(default="", description="HFT PostgreSQL password")
    db: str = Field(default="marketdata", description="HFT database name")


class MatrizSettings(BaseSettings):
    """Matriz web scraping credentials."""

    model_config = SettingsConfigDict(env_prefix="MATRIZ_", env_file=".env", env_file_encoding="utf-8", extra="ignore")

    user: str = Field(default="", description="Matriz username")
    password: str = Field(default="", description="Matriz password")


class HFTSDKSettings(BaseSettings):
    """HFT SDK/API keys."""

    model_config = SettingsConfigDict(env_prefix="HFT_SDK_", env_file=".env", env_file_encoding="utf-8", extra="ignore")

    api_key_prod: str = Field(default="", description="Production API key")
    api_key_uat: str = Field(default="", description="UAT API key")


class PolygonSettings(BaseSettings):
    """Polygon.io API configuration."""

    model_config = SettingsConfigDict(env_prefix="POLYGON_", env_file=".env", env_file_encoding="utf-8", extra="ignore")

    api_key: str = Field(default="", description="Polygon.io API key")


class NasdaqDataLinkSettings(BaseSettings):
    """Nasdaq Data Link (Quandl) API configuration."""

    model_config = SettingsConfigDict(env_prefix="NDL_", env_file=".env", env_file_encoding="utf-8", extra="ignore")

    api_key: str = Field(default="", description="Nasdaq Data Link API key")


class BacktraderSettings(BaseSettings):
    """Backtrader data feed API configuration."""

    model_config = SettingsConfigDict(env_prefix="BACKTRADER_", env_file=".env", env_file_encoding="utf-8", extra="ignore")

    api_key: str = Field(default="", description="Backtrader data API key")


class PPISettings(BaseSettings):
    """Portfolio Personal Inversiones API configuration."""

    model_config = SettingsConfigDict(env_prefix="PPI_", env_file=".env", env_file_encoding="utf-8", extra="ignore")

    public_key: str = Field(default="", description="PPI public key")
    private_key: str = Field(default="", description="PPI private key")
    account_number: str = Field(default="", description="PPI account number")


class BinanceSettings(BaseSettings):
    """Binance API configuration."""

    model_config = SettingsConfigDict(env_prefix="BINANCE_", env_file=".env", env_file_encoding="utf-8", extra="ignore")

    api_key: str = Field(default="", description="Binance API key")
    secret_key: str = Field(default="", description="Binance secret key")
    symbols: str = Field(default="BTCUSDT,ETHUSDT,BNBUSDT")
    interval: str = Field(default="1m")
    lookback: int = Field(default=100)


class IBSettings(BaseSettings):
    """Interactive Brokers configuration."""

    model_config = SettingsConfigDict(env_prefix="IB_", env_file=".env", env_file_encoding="utf-8", extra="ignore")

    host: str = Field(default="127.0.0.1")
    port: int = Field(default=7497)
    client_id: int = Field(default=1)


class MailSettings(BaseSettings):
    """Email alerting configuration."""

    model_config = SettingsConfigDict(env_prefix="MAIL_", env_file=".env", env_file_encoding="utf-8", extra="ignore")

    server: str = Field(default="smtp.gmail.com")
    port: int = Field(default=587)
    username: str = Field(default="")
    password: str = Field(default="")
    mail_from: str = Field(default="")
    mail_to: str = Field(default="")


class RedisSettings(BaseSettings):
    """Redis cache configuration."""

    model_config = SettingsConfigDict(env_prefix="REDIS_", env_file=".env", env_file_encoding="utf-8", extra="ignore")

    host: str = Field(default="localhost")
    port: int = Field(default=6379)
    db: int = Field(default=0)
    password: Optional[str] = Field(default="")


class RabbitMQSettings(BaseSettings):
    """RabbitMQ message queue configuration."""

    model_config = SettingsConfigDict(env_prefix="RABBITMQ_", env_file=".env", env_file_encoding="utf-8", extra="ignore")

    host: str = Field(default="localhost")
    port: int = Field(default=5672)
    user: str = Field(default="guest")
    password: str = Field(default="guest")
    vhost: str = Field(default="/")


class DashboardSettings(BaseSettings):
    """Dashboard configuration."""

    model_config = SettingsConfigDict()

    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8050)
    debug: bool = Field(default=True)


class DjangoSettings(BaseSettings):
    """Django-specific configuration."""

    model_config = SettingsConfigDict(env_prefix="DJANGO_", env_file=".env", env_file_encoding="utf-8", extra="ignore")

    secret_key: str = Field(default="", description="Django secret key")
    debug: bool = Field(default=True)
    allowed_hosts: str = Field(default="localhost,127.0.0.1")


class BacktestSettings(BaseSettings):
    """Backtesting configuration."""

    model_config = SettingsConfigDict(env_prefix="BACKTEST_", env_file=".env", env_file_encoding="utf-8", extra="ignore")

    initial_capital: float = Field(default=2000000)
    commission: float = Field(default=0.001)
    slippage: float = Field(default=0.0005)


class WebScrapingSettings(BaseSettings):
    """Web scraping configuration."""

    model_config = SettingsConfigDict()

    user_agent: str = Field(
        default="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    )
    timeout: int = Field(default=30)
    max_retries: int = Field(default=3)


class AlertSettings(BaseSettings):
    """Alert threshold configuration."""

    model_config = SettingsConfigDict()

    rsi_overbought: float = Field(default=70)
    rsi_oversold: float = Field(default=30)
    price_change_percent: float = Field(default=5.0)


class Settings(BaseSettings):
    """
    Main application settings.

    Aggregates all configuration sub-modules.
    Loads from environment variables and .env file.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application settings
    environment: str = Field(default="development", description="Environment: development, staging, production")
    log_level: str = Field(default="INFO", description="Logging level")
    log_path: str = Field(default="logs/", description="Log file path")

    # Rate limiting
    rate_limit_per_minute: int = Field(default=60)

    # JWT
    jwt_secret_key: str = Field(default="")
    jwt_algorithm: str = Field(default="HS256")
    jwt_expiration_hours: int = Field(default=24)

    # Sub-settings
    db: DatabaseSettings = Field(default_factory=DatabaseSettings)
    postgres: PostgresSettings = Field(default_factory=PostgresSettings)
    hft_postgres: HFTPostgresSettings = Field(default_factory=HFTPostgresSettings)
    ppi: PPISettings = Field(default_factory=PPISettings)
    binance: BinanceSettings = Field(default_factory=BinanceSettings)
    ib: IBSettings = Field(default_factory=IBSettings)
    mail: MailSettings = Field(default_factory=MailSettings, alias="mail_settings")
    matriz: MatrizSettings = Field(default_factory=MatrizSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    rabbitmq: RabbitMQSettings = Field(default_factory=RabbitMQSettings)
    dashboard: DashboardSettings = Field(default_factory=DashboardSettings)
    django_settings: DjangoSettings = Field(default_factory=DjangoSettings)
    backtest: BacktestSettings = Field(default_factory=BacktestSettings)
    web_scraping: WebScrapingSettings = Field(default_factory=WebScrapingSettings)
    alerts: AlertSettings = Field(default_factory=AlertSettings)
    hft_sdk: HFTSDKSettings = Field(default_factory=HFTSDKSettings)
    polygon: PolygonSettings = Field(default_factory=PolygonSettings)
    ndl: NasdaqDataLinkSettings = Field(default_factory=NasdaqDataLinkSettings)
    backtrader: BacktraderSettings = Field(default_factory=BacktraderSettings)


@lru_cache()
def get_settings() -> Settings:
    """
    Get cached settings instance.

    Returns:
        Settings: Cached settings instance
    """
    return Settings()


# Global settings instance
settings = get_settings()