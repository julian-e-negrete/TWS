# SPEC §6.4 T-DB-2 — shared PostgreSQL connection pool with reconnect + lazy init
import time
import psycopg2
import psycopg2.pool
from config import PG_HOST, PG_PORT, PG_DBNAME, PG_USER, PG_PASSWORD

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

def get_conn():
    global _pool
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
