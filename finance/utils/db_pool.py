"""
SQLAlchemy connection pools for PostgreSQL and MySQL.
Use get_pg_engine() / get_mysql_engine() everywhere — never create raw connections.
"""
from functools import lru_cache

from sqlalchemy import create_engine, Engine
from finance.config.settings import settings


@lru_cache(maxsize=1)
def get_pg_engine() -> Engine:
    pg = settings.postgres
    url = f"postgresql+psycopg2://{pg.user}:{pg.password}@{pg.host}:{pg.port}/{pg.db}"
    return create_engine(url, pool_size=10, max_overflow=5, pool_pre_ping=True)


@lru_cache(maxsize=1)
def get_mysql_engine() -> Engine:
    db = settings.db
    url = f"mysql+pymysql://{db.user}:{db.password}@{db.host}:{db.port}/{db.name}"
    return create_engine(url, pool_size=10, max_overflow=5, pool_pre_ping=True)
