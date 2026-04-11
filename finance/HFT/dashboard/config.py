"""
Configuration for HFT Dashboard

DEPRECATED: Use finance.config.settings instead.
"""

from finance.config import settings

# Database configuration (PostgreSQL for HFT)
dbname = settings.hft_postgres.db
user = settings.hft_postgres.user
password = settings.hft_postgres.password
host = settings.hft_postgres.host
port = settings.hft_postgres.port

# Matriz credentials
user_matriz = settings.matriz.user
pass_matriz = settings.matriz.password

# HFT SDK API Keys
api_key_prod = settings.hft_sdk.api_key_prod
api_key_UAT = settings.hft_sdk.api_key_uat