"""
Finance Configuration Module

Centralized configuration management using pydantic-settings.
Copy .env.example to .env and fill with your credentials.
"""

from settings import settings, Settings


__all__ = ["settings", "Settings"]