"""
Database Configuration for Django Dashboard

DEPRECATED: Use finance.config.settings instead.
"""

from finance.config import settings

# Backward compatibility aliases
host = settings.db.host
user = settings.db.user
password = settings.db.password
database = settings.db.name