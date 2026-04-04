import requests
import pandas as pd
from datetime import datetime
import locale
import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from psycopg2.extras import execute_values
from shared.db_pool import get_conn, put_conn
from config import dbname, user, password, host, port
from get_cookies import get_cookies

async def fetch_minute_trades_today(trades, cookie):
    now = datetime.now()
    if now.hour < 10 or now.hour >= 17:
        sys.exit(0)

    locale.setlocale(locale.LC_TIME, 'es_ES.UTF-8')
    month_name = now.strftime('%B')[:3].upper()
    year = now.strftime('%y')  # SPEC §1 P2 — derive year at runtime

    # SPEC §1 P2 — mirror wsclient instrument set: static + dynamic GFGC from ref-data
    from shared.get_cookies import get_active_gfgc_topics
    gfgc = [t.replace("md.", "") for t in get_active_gfgc_topics(cookie)]

    securities = [
        f"rx_DDF_DLR_{month_name}{year}",
        f"rx_DDF_DLR_{month_name}{year}A",
        "bm_MERV_AL30_24hs",
        "bm_MERV_AL30D_24hs",
        "bm_MERV_PESOS_1D",
        "bm_MERV_SUPV_24hs",
        "bm_MERV_GGAL_24hs",
        "bm_MERV_GGALD_24hs",
        "bm_MERV_BBDD_24hs",
        "bm_MERV_PBRD_24hs",
        *gfgc,
    ]

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.5",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "Sec-GPC": "1",
        "Cookie": f"_mtz_web_key={cookie}"
    }

    query = """
    INSERT INTO orders (instrument, time, price, volume, side)
    VALUES %s
    ON CONFLICT DO NOTHING;
    """

    for security in securities:
        url = f"https://matriz.eco.xoms.com.ar/api/v2/trades/securities/{security}?_ds=&_ds=1753889449163-979204"
        headers["Referer"] = f"https://matriz.eco.xoms.com.ar/security/{security}?interval=D"

        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code != 200:
                print(f"Error fetching {security}: Status {response.status_code}")
                continue

            df = pd.DataFrame(response.json())
            if df.empty or 'sides' not in df or df['sides'].isna().all():
                continue

            df['side'] = df['sides'].apply(lambda x: str(x[0]) if isinstance(x, list) and len(x) > 0 else None)
            _side_map = {'1': 'B', '2': 'S', 'B': 'B', 'S': 'S', 'buy': 'B', 'sell': 'S',
                         'BUY': 'B', 'SELL': 'S', 'b': 'B', 's': 'S'}
            df['side'] = df['side'].map(_side_map)
            df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce').dt.strftime('%Y-%m-%d %H:%M:%S')
            df['instrument'] = security

            # SPEC §1 P2 — infer side from ticks bid/ask midpoint for any instrument with unknown side
            if df['side'].isna().any():
                tick_instr = f"M:{security}"
                conn_tmp = get_conn()
                try:
                    cur_tmp = conn_tmp.cursor()
                    cur_tmp.execute("""
                        SELECT DISTINCT ON (date_trunc('minute', time))
                            date_trunc('minute', time) as minute,
                            bid_price, ask_price
                        FROM ticks
                        WHERE instrument = %s AND time > now() - interval '1 day'
                        ORDER BY date_trunc('minute', time), time DESC
                    """, (tick_instr,))
                    rows = cur_tmp.fetchall()
                    cur_tmp.close()
                finally:
                    put_conn(conn_tmp)

                if rows:
                    ba = pd.DataFrame(rows, columns=['minute', 'bid_price', 'ask_price'])
                    ba['minute'] = pd.to_datetime(ba['minute']).dt.tz_localize(None)
                    df['minute'] = pd.to_datetime(df['timestamp']).dt.tz_localize(None).dt.floor('min')
                    df = df.merge(ba, on='minute', how='left')
                    def _infer(row):
                        if pd.isna(row.get('bid_price')):
                            return None
                        mid = (row['bid_price'] + row['ask_price']) / 2
                        # price below mid -> sell aggressor, above mid -> buy aggressor
                        if row['price'] < mid:
                            return 'S'
                        if row['price'] > mid:
                            return 'B'
                        return 'B'  # at mid: default buy
                    df['side'] = df.apply(_infer, axis=1)

            df['side'] = df['side'].fillna('U')
            df = df.dropna(subset=['instrument', 'timestamp', 'price', 'volume'])
            if df.empty:
                continue

            records = df[["instrument", "timestamp", "price", "volume", "side"]].values.tolist()
            conn = get_conn()
            try:
                cur = conn.cursor()
                execute_values(cur, query, records)
                conn.commit()
                cur.close()
                print(f"Inserted {len(records)} records for {security}")
            except Exception as e:
                print(f"Error inserting records for {security}: {e}")
                conn.rollback()
            finally:
                put_conn(conn)

        except Exception as e:
            print(f"Error processing {security}: {e}")

if __name__ == "__main__":
    now = datetime.now()
    if now.hour < 10 or now.hour >= 17:
        sys.exit(0)
    _mtz_web_key = get_cookies()
    import asyncio
    asyncio.run(fetch_minute_trades_today([], _mtz_web_key))