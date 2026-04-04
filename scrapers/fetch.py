# HTTP + WebSocket I/O helpers with logging — T-OBS-1, T-OBS-2 / SPEC §2.3
from scrapers.logger import get_logger

_log = get_logger("io")
_MAX_BODY = 4096  # bytes


# ── T-OBS-1: HTTP ────────────────────────────────────────────────────────────

async def async_fetch(session, method: str, url: str, **kwargs):
    """Wrap aiohttp request with request/response logging."""
    _log.info("%s %s headers=%s", method.upper(), url, kwargs.get("headers", {}))
    async with session.request(method, url, **kwargs) as resp:
        body = await resp.read()
        _log.info("← %s %s body=%s", resp.status, url, body[:_MAX_BODY])
        return resp.status, body


def sync_fetch(session, method: str, url: str, **kwargs):
    """Wrap requests.Session call with request/response logging."""
    _log.info("%s %s headers=%s", method.upper(), url, kwargs.get("headers", {}))
    resp = session.request(method, url, **kwargs)
    _log.info("← %s %s body=%s", resp.status_code, url, resp.content[:_MAX_BODY])
    return resp


# ── T-OBS-2: WebSocket ───────────────────────────────────────────────────────

def log_ws_message(platform: str, raw) -> None:
    """Call before parsing any inbound WebSocket message."""
    _log.info("WS[%s] raw=%s", platform, str(raw)[:_MAX_BODY])
