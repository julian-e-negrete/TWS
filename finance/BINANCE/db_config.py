"""
Database Configuration for BINANCE module

DEPRECATED: Use finance.config.settings instead.
"""

from finance.config import settings

# Backward compatibility aliases
host = settings.db.host
port = settings.db.port
user = settings.db.user
password = settings.db.password
database = settings.db.name