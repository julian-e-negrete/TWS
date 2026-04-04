# SPEC §6.4 T-DB-2 — shared PostgreSQL connection pool with reconnect + lazy init
import time
import psycopg2
import psycopg2.pool
from config.settings import settings  # Fixed: settings not setting

# Then use settings instead of individual variables
# Instead of: from config.setting import PG_HOST, PG_PORT, PG_DBNAME, PG_USER, PG_PASSWORD
# Use:
PG_HOST = settings.postgres.host
PG_PORT = settings.postgres.port
PG_DBNAME = settings.postgres.db
PG_USER = settings.postgres.user
PG_PASSWORD = settings.postgres.password

_DSN = dict(host=PG_HOST, port=PG_PORT, dbname=PG_DBNAME,
            user=PG_USER, password=PG_PASSWORD, sslmode="disable")

def _make_pool(retries=10, delay=3):
    """Create pool, retrying if PG is still starting up after a server reboot."""
    for attempt in range(retries):
        try:
            return psycopg2.pool.ThreadedConnectionPool(minconn=1, maxconn=5, **_DSN)
        except psycopg2.OperationalError as e:
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                raise

_pool = _make_pool()

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

_pg_engine = None
_mysql_engine = None

def get_pg_engine() -> Engine:
    global _pg_engine
    if _pg_engine is None:
        dsn = f"postgresql://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{PG_DBNAME}"
        _pg_engine = create_engine(dsn)
    return _pg_engine

def get_mysql_engine() -> Engine:
    global _mysql_engine
    if _mysql_engine is None:
        # Using DatabaseSettings for MySQL
        m = settings.db
        dsn = f"mysql+pymysql://{m.user}:{m.password}@{m.host}:{m.port}/{m.name}"
        _mysql_engine = create_engine(dsn)
    return _mysql_engine

def get_conn():
    global _pool
    # ... rest of the file
    try:
        conn = _pool.getconn()
        # Verify connection is alive
        conn.cursor().execute("SELECT 1")
        return conn
    except psycopg2.OperationalError:
        _pool = _make_pool()
        return _pool.getconn()

def put_conn(conn):
    _pool.putconn(conn)
