"""
Configuration for web_scraping matriz module

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
# Note: matriz credentials are not in the standard settings
# Add them to .env as MATRIZ_USER and MATRIZ_PASSWORD if needed
user_matriz = ""
pass_matriz = ""