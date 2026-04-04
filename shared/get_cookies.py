# T-COOKIE-1 / SPEC §4 I-8 — canonical get_cookies, deduplicates job/ and web_scraping/matriz/
# Also stores Matriz WS session_id and conn_id from /api/v2/profile
import sys, os, json, requests
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from playwright.sync_api import sync_playwright
from shared.db_pool import get_conn, put_conn
# from config import MATRIZ_USER, MATRIZ_PASS — logic moved to settings.matriz.user/password
from scrapers.logger import get_logger

_log = get_logger("cookies")

_CACHE_INTERVAL = "2 hours"


def _is_fresh(cur) -> bool:
    cur.execute(
        "SELECT 1 FROM cookies WHERE name='_mtz_web_key' AND time > now() - interval %s",
        (_CACHE_INTERVAL,),
    )
    return cur.fetchone() is not None


def _upsert(cur, name: str, value: str):
    cur.execute(
        """INSERT INTO cookies (name, value, time) VALUES (%s, %s, now())
           ON CONFLICT (name) DO UPDATE SET value=EXCLUDED.value, time=now()""",
        (name, value),
    )


def _fetch_from_db(cur, name: str) -> str:
    cur.execute("SELECT value FROM cookies WHERE name=%s ORDER BY time DESC LIMIT 1", (name,))
    row = cur.fetchone()
    return row[0] if row else None


def get_cookies() -> str:
    """Return fresh _mtz_web_key cookie, refreshing via Playwright if stale."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        if _is_fresh(cur):
            return _fetch_from_db(cur, "_mtz_web_key")
        _log.info("cookie expired, refreshing via Playwright")
        cookie, session_id, conn_id = _playwright_login()
        _upsert(cur, "_mtz_web_key", cookie)
        if session_id:
            _upsert(cur, "mtz_session_id", session_id)
        if conn_id:
            _upsert(cur, "mtz_conn_id", conn_id)
        conn.commit()
        _log.info("cookie + WS session refreshed")
        return cookie
    except Exception as e:
        _log.error("get_cookies failed: %s", e)
        raise
    finally:
        put_conn(conn)


def get_ws_url() -> str:
    """Return the Matriz WS URL with fresh session_id and conn_id, properly URL-encoded."""
    from urllib.parse import quote

    def _build(sid, cid):
        return (
            f"wss://matriz.eco.xoms.com.ar/ws"
            f"?session_id={quote(sid, safe='')}"
            f"&conn_id={quote(cid, safe='')}"
        )

    conn = get_conn()
    try:
        cur = conn.cursor()
        if not _is_fresh(cur):
            get_cookies()
            cur = conn.cursor()
        session_id = _fetch_from_db(cur, "mtz_session_id") or ""
        conn_id = _fetch_from_db(cur, "mtz_conn_id") or ""
        if session_id and conn_id:
            return _build(session_id, conn_id)
    finally:
        put_conn(conn)

    # Session missing — force re-login
    _log.info("WS session missing, forcing re-login")
    conn2 = get_conn()
    try:
        cur = conn2.cursor()
        cur.execute("UPDATE cookies SET time = now() - interval '3 hours' WHERE name = '_mtz_web_key'")
        conn2.commit()
    finally:
        put_conn(conn2)

    get_cookies()
    conn3 = get_conn()
    try:
        cur = conn3.cursor()
        session_id = _fetch_from_db(cur, "mtz_session_id") or ""
        conn_id = _fetch_from_db(cur, "mtz_conn_id") or ""
        if not session_id or not conn_id:
            raise RuntimeError("WS session_id/conn_id not available after re-login")
        return _build(session_id, conn_id)
    finally:
        put_conn(conn3)


def get_active_gfgc_topics(cookie: str) -> list[str]:
    """SPEC §1 P2 — fetch active GFGC/GFGV option instrument IDs from Matriz ref-data at runtime."""
    try:
        r = requests.get(
            "https://matriz.eco.xoms.com.ar/api/v2/ref-data?_ds=1",
            headers={
                "Cookie": f"_mtz_web_key={cookie}",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0",
                "Accept": "application/json",
                "Referer": "https://matriz.eco.xoms.com.ar/",
            },
            timeout=15,
        )
        securities = r.json().get("securities", [])
        return [f"md.{s['id']}" for s in securities
                if "GFGC" in s.get("id", "") or "GFGV" in s.get("id", "")]
    except Exception as e:
        _log.warning("could not fetch GFGC/GFGV topics: %s", e)
        return []


def _playwright_login() -> tuple[str, str, str]:
    """Login via Playwright, return (cookie, session_id, conn_id)."""
    api_responses = {}

    with sync_playwright() as p:
        browser = p.firefox.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()

        def on_response(resp):
            if "/api/v2/profile" in resp.url and resp.status == 200:
                try:
                    api_responses["profile"] = resp.json()
                except Exception:
                    pass

        page.on("response", on_response)
        page.goto("https://matriz.eco.xoms.com.ar/", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_selector("#loginScreen_input_user", timeout=20000)
        page.fill("#loginScreen_input_user", settings.matriz.user)
        page.fill("#loginScreen_input_password", settings.matriz.password)
        page.click("#loginScreen_button_submit")
        page.wait_for_timeout(10000)
        cookies = ctx.cookies()
        browser.close()

    mtz = next((c for c in cookies if c["name"] == "_mtz_web_key"), None)
    if not mtz:
        raise RuntimeError("_mtz_web_key cookie not found after login")

    profile = api_responses.get("profile", {})
    return mtz["value"], profile.get("sessionId", ""), profile.get("connectionId", "")
