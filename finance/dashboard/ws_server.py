"""
WebSocket server for real-time dashboard data — Tarea 11.2
Streams latest ticks from PostgreSQL to connected clients every second.
Run alongside the Dash app.
"""
import asyncio
import json
import websockets
import websockets.server

from finance.utils.db_pool import get_pg_engine
from finance.utils.logger import logger
from sqlalchemy import text

CLIENTS: set = set()


async def _latest_ticks() -> list[dict]:
    """Fetch last tick per active instrument."""
    with get_pg_engine().connect() as conn:
        rows = conn.execute(text("""
            SELECT DISTINCT ON (instrument)
                instrument, time, bid_price, ask_price, last_price, total_volume
            FROM ticks
            WHERE time > NOW() - INTERVAL '1 hour'
            ORDER BY instrument, time DESC
        """))
        return [dict(r._mapping) for r in rows.fetchall()]


async def _broadcast():
    """Push latest ticks to all connected clients every second."""
    while True:
        await asyncio.sleep(1)
        if not CLIENTS:
            continue
        try:
            ticks = await asyncio.get_event_loop().run_in_executor(None, lambda: asyncio.run(_latest_ticks()) if False else _latest_ticks_sync())
            payload = json.dumps(ticks, default=str)
            dead = set()
            for ws in CLIENTS.copy():
                try:
                    await ws.send(payload)
                except websockets.exceptions.ConnectionClosed:
                    dead.add(ws)
            CLIENTS -= dead
        except Exception as e:
            logger.error("Broadcast error: {e}", e=e)


def _latest_ticks_sync() -> list[dict]:
    with get_pg_engine().connect() as conn:
        rows = conn.execute(text("""
            SELECT DISTINCT ON (instrument)
                instrument, time, bid_price, ask_price, last_price, total_volume
            FROM ticks
            WHERE time > NOW() - INTERVAL '1 hour'
            ORDER BY instrument, time DESC
        """))
        return [dict(r._mapping) for r in rows.fetchall()]


async def _handler(websocket):
    CLIENTS.add(websocket)
    logger.info("WS client connected — total: {n}", n=len(CLIENTS))
    try:
        await websocket.wait_closed()
    finally:
        CLIENTS.discard(websocket)
        logger.info("WS client disconnected — total: {n}", n=len(CLIENTS))


async def main(host: str = "0.0.0.0", port: int = 8765):
    async with websockets.server.serve(_handler, host, port):
        logger.info("WebSocket server started on ws://{host}:{port}", host=host, port=port)
        await _broadcast()


if __name__ == "__main__":
    asyncio.run(main())
