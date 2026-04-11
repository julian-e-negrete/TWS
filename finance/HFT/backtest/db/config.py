"""
Database Configuration for HFT backtest module

DEPRECATED: Use finance.config.settings instead.
"""

from finance.config import settings

# Database configuration (PostgreSQL)
dbname = settings.postgres.db
user = settings.postgres.user
password = settings.postgres.password
host = settings.postgres.host
port = settings.postgres.port

# Matriz credentials (if needed)
user_matriz = ""
pass_matriz = ""