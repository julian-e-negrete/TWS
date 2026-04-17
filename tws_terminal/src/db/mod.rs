use anyhow::Result;
use chrono::{DateTime, NaiveDate, Utc};
use std::sync::Arc;
use tokio_postgres::{Client, NoTls};

// ─── Filter params ────────────────────────────────────────────────────────────

#[derive(Clone, Debug, Default)]
pub struct HistFilter {
    pub date:       Option<NaiveDate>,   // filter by calendar day (UTC)
    pub instrument: Option<String>,      // substring match on instrument/symbol
}

// ─── Row types ────────────────────────────────────────────────────────────────

#[derive(Clone, Debug)]
pub struct HistTick {
    pub time: DateTime<Utc>,
    pub instrument: String,
    pub bid_price: f64,
    pub ask_price: f64,
    pub last_price: f64,
    pub total_volume: i64,
}

#[derive(Clone, Debug)]
pub struct HistOrder {
    pub time: DateTime<Utc>,
    pub instrument: String,
    pub price: f64,
    pub volume: i64,
    pub side: String,
}

/// One daily OHLCV bar returned by the PPI broker API via Python subprocess.
#[derive(Clone, Debug, serde::Deserialize)]
pub struct OhlcvBar {
    pub date:   String,
    pub open:   Option<f64>,
    pub high:   Option<f64>,
    pub low:    Option<f64>,
    pub close:  Option<f64>,
    pub volume: Option<f64>,
}

#[derive(Clone, Debug)]
pub struct HistBinanceTick {
    pub timestamp: DateTime<Utc>,
    pub symbol: String,
    pub open: f64,
    pub high: f64,
    pub low: f64,
    pub close: f64,
    pub volume: f64,
}

#[derive(Clone, Debug)]
pub struct HistBinanceTrade {
    pub time: DateTime<Utc>,
    pub symbol: String,
    pub price: f64,
    pub qty: f64,
    pub is_buyer_maker: bool,
}

// ─── Connection ───────────────────────────────────────────────────────────────

pub async fn connect_arc() -> Result<Arc<Client>> {
    Ok(Arc::new(connect().await?))
}

pub async fn connect() -> Result<Client> {
    let host = std::env::var("POSTGRES_HOST").unwrap_or_else(|_| "100.112.16.115".into());
    let port = std::env::var("POSTGRES_PORT").unwrap_or_else(|_| "5432".into());
    let user = std::env::var("POSTGRES_USER").unwrap_or_else(|_| "postgres".into());
    let pass = std::env::var("POSTGRES_PASSWORD").unwrap_or_default();
    let db   = std::env::var("POSTGRES_DB").unwrap_or_else(|_| "marketdata".into());

    let dsn = format!("host={host} port={port} user={user} password={pass} dbname={db}");
    let (client, conn) = tokio_postgres::connect(&dsn, NoTls).await?;
    tokio::spawn(async move { let _ = conn.await; });
    Ok(client)
}

// ─── Queries ──────────────────────────────────────────────────────────────────

pub async fn fetch_ticks(client: &Client, limit: i64, f: &HistFilter) -> Result<Vec<HistTick>> {
    let instr = f.instrument.as_deref().map(|s| format!("%{}%", s.to_lowercase()));
    let rows = client
        .query(
            "SELECT time, instrument, \
                    bid_price::float8, ask_price::float8, last_price::float8, total_volume \
             FROM ticks \
             WHERE ($1::date IS NULL OR time::date = $1) \
               AND ($2::text IS NULL OR LOWER(instrument) LIKE $2) \
               AND ($1::date IS NOT NULL OR time > NOW() - INTERVAL '2 days') \
             ORDER BY time DESC LIMIT $3",
            &[&f.date, &instr, &limit],
        )
        .await?;

    Ok(rows.iter().map(|r| HistTick {
        time:         r.get(0),
        instrument:   r.get(1),
        bid_price:    r.get(2),
        ask_price:    r.get(3),
        last_price:   r.get(4),
        total_volume: r.get(5),
    }).collect())
}

pub async fn fetch_orders(client: &Client, limit: i64, f: &HistFilter) -> Result<Vec<HistOrder>> {
    let instr = f.instrument.as_deref().map(|s| format!("%{}%", s.to_lowercase()));
    let rows = client
        .query(
            "SELECT time, instrument, price::float8, volume, side \
             FROM orders \
             WHERE ($1::date IS NULL OR time::date = $1) \
               AND ($2::text IS NULL OR LOWER(instrument) LIKE $2) \
               AND ($1::date IS NOT NULL OR time > NOW() - INTERVAL '2 days') \
             ORDER BY time DESC LIMIT $3",
            &[&f.date, &instr, &limit],
        )
        .await?;

    Ok(rows.iter().map(|r| {
        let side_char: &str = r.get(4);
        HistOrder {
            time:       r.get(0),
            instrument: r.get(1),
            price:      r.get(2),
            volume:     r.get(3),
            side:       side_char.trim().to_string(),
        }
    }).collect())
}

pub async fn fetch_binance_ticks(client: &Client, limit: i64, f: &HistFilter) -> Result<Vec<HistBinanceTick>> {
    let sym = f.instrument.as_deref().map(|s| format!("%{}%", s.to_uppercase()));
    let rows = client
        .query(
            "SELECT timestamp, symbol, \
                    open::float8, high::float8, low::float8, close::float8, volume::float8 \
             FROM binance_ticks \
             WHERE ($1::date IS NULL OR timestamp::date = $1) \
               AND ($2::text IS NULL OR UPPER(symbol) LIKE $2) \
               AND ($1::date IS NOT NULL OR timestamp > NOW() - INTERVAL '2 days') \
             ORDER BY timestamp DESC LIMIT $3",
            &[&f.date, &sym, &limit],
        )
        .await?;

    Ok(rows.iter().map(|r| HistBinanceTick {
        timestamp: r.get(0),
        symbol:    r.get(1),
        open:      r.get(2),
        high:      r.get(3),
        low:       r.get(4),
        close:     r.get(5),
        volume:    r.get(6),
    }).collect())
}

pub async fn fetch_binance_trades(client: &Client, limit: i64, f: &HistFilter) -> Result<Vec<HistBinanceTrade>> {
    let sym = f.instrument.as_deref().map(|s| format!("%{}%", s.to_uppercase()));
    let rows = client
        .query(
            "SELECT time, symbol, price::float8, qty::float8, is_buyer_maker \
             FROM binance_trades \
             WHERE ($1::date IS NULL OR time::date = $1) \
               AND ($2::text IS NULL OR UPPER(symbol) LIKE $2) \
               AND ($1::date IS NOT NULL OR time > NOW() - INTERVAL '2 days') \
             ORDER BY time DESC LIMIT $3",
            &[&f.date, &sym, &limit],
        )
        .await?;

    Ok(rows.iter().map(|r| HistBinanceTrade {
        time:           r.get(0),
        symbol:         r.get(1),
        price:          r.get(2),
        qty:            r.get(3),
        is_buyer_maker: r.get(4),
    }).collect())
}

// ─── Autocomplete helpers ─────────────────────────────────────────────────────

/// Fetch last N hours of close prices for a Binance symbol, oldest first.
/// Returns scaled u64 values (close × 100) matching BinanceSymbolData.price_history format.
pub async fn fetch_binance_price_history(client: &Client, symbol: &str, hours: i64) -> Result<Vec<u64>> {
    let rows = client.query(
        "SELECT close::float8 FROM binance_ticks
         WHERE symbol = $1 AND timestamp > NOW() - ($2 || ' hours')::interval
         ORDER BY timestamp ASC",
        &[&symbol, &hours.to_string()],
    ).await?;
    Ok(rows.iter().map(|r| {
        let close: f64 = r.get(0);
        (close * 100.0) as u64
    }).collect())
}

pub async fn fetch_distinct_instruments(client: &Client) -> Result<Vec<String>> {
    let rows = client.query(
        "SELECT DISTINCT instrument FROM ticks
         WHERE time > NOW() - INTERVAL '7 days'
         ORDER BY instrument",
        &[],
    ).await?;
    if rows.is_empty() {
        // Holiday / weekend fallback
        let rows2 = client.query(
            "SELECT DISTINCT instrument FROM ticks
             WHERE time > NOW() - INTERVAL '30 days'
             ORDER BY instrument",
            &[],
        ).await?;
        return Ok(rows2.iter().map(|r| r.get::<_, String>(0)).collect());
    }
    Ok(rows.iter().map(|r| r.get::<_, String>(0)).collect())
}

pub async fn fetch_distinct_dates(client: &Client) -> Result<Vec<String>> {
    let rows = client.query(
        "SELECT DISTINCT d FROM (
            SELECT time::date::text AS d FROM ticks
              WHERE time > NOW() - INTERVAL '90 days'
            UNION
            SELECT timestamp::date::text FROM binance_ticks
              WHERE timestamp > NOW() - INTERVAL '90 days'
         ) t ORDER BY 1 DESC LIMIT 90",
        &[],
    ).await?;
    Ok(rows.iter().map(|r| r.get::<_, String>(0)).collect())
}

pub async fn fetch_distinct_binance_symbols(client: &Client) -> Result<Vec<String>> {
    let rows = client.query(
        "SELECT DISTINCT symbol FROM binance_ticks
         WHERE timestamp > NOW() - INTERVAL '7 days'
         ORDER BY symbol",
        &[],
    ).await?;
    Ok(rows.iter().map(|r| r.get::<_, String>(0)).collect())
}

// ─── Options chain & futures curve ───────────────────────────────────────────

#[derive(Clone, Debug)]
pub struct OptionRow {
    pub instrument: String,
    pub last_price: f64,
    pub bid: f64,
    pub ask: f64,
}

#[derive(Clone, Debug)]
pub struct FuturesRow {
    pub instrument: String,
    pub last_price: f64,
    pub bid: f64,
    pub ask: f64,
}

pub async fn fetch_options_chain(client: &Client) -> Result<Vec<OptionRow>> {
    // Single query: best bid/ask per instrument from last session, all options at once
    let tick_rows = client.query(
        "SELECT instrument,
                COALESCE(MAX(bid_price), 0)::float8,
                COALESCE(MIN(NULLIF(ask_price, 0)), 0)::float8
         FROM ticks
         WHERE (instrument LIKE '%GFGC%' OR instrument LIKE '%GFGV%')
           AND time > NOW() - INTERVAL '7 days'
           AND bid_price > 0 AND ask_price > 0
         GROUP BY instrument",
        &[],
    ).await?;

    if tick_rows.is_empty() { return Ok(vec![]); }

    // Single query: last trade price per option from orders
    let order_rows = client.query(
        "SELECT DISTINCT ON (instrument) instrument, price::float8
         FROM orders
         WHERE (instrument LIKE '%GFGC%' OR instrument LIKE '%GFGV%')
           AND time > NOW() - INTERVAL '7 days'
         ORDER BY instrument, time DESC",
        &[],
    ).await?;

    // Build a map: instrument (no M: prefix) → last trade price
    let mut last_price_map: std::collections::HashMap<String, f64> = std::collections::HashMap::new();
    for r in &order_rows {
        let instr: String = r.get(0);
        let price: f64 = r.get(1);
        last_price_map.insert(instr, price);
    }

    let mut rows = Vec::new();
    for r in &tick_rows {
        let instrument: String = r.get(0);
        let bid: f64 = r.get(1);
        let ask: f64 = r.get(2);
        if bid <= 0.0 || ask <= 0.0 { continue; }
        // Look up last trade — orders table has no M: prefix
        let order_key = instrument.trim_start_matches("M:").to_string();
        let last_price = last_price_map.get(&order_key).copied().unwrap_or(0.0);
        rows.push(OptionRow { instrument, last_price, bid, ask });
    }
    Ok(rows)
}

/// Fetch the most recent executed trade price for a given instrument
pub async fn fetch_last_price(client: &Client, instrument: &str) -> Result<f64> {
    // Try orders table first (actual trades), fall back to ticks last_price
    let order_instr = instrument.trim_start_matches("M:");
    let rows = client.query(
        "SELECT price::float8 FROM orders WHERE instrument = $1
         ORDER BY time DESC LIMIT 1",
        &[&order_instr],
    ).await?;
    if let Some(r) = rows.first() {
        return Ok(r.get(0));
    }
    // Fallback: ticks last_price
    let rows = client.query(
        "SELECT last_price::float8 FROM ticks WHERE instrument = $1
         ORDER BY time DESC LIMIT 1",
        &[&instrument],
    ).await?;
    Ok(rows.first().map(|r| r.get::<_, f64>(0)).unwrap_or(0.0))
}

pub async fn fetch_futures_curve(client: &Client) -> Result<Vec<FuturesRow>> {
    // Get last 3 retail DLR contracts with data in last 30 days, sorted by expiry
    let rows = client.query(
        "SELECT DISTINCT ON (instrument) instrument,
                last_price::float8, bid_price::float8, ask_price::float8
         FROM ticks
         WHERE instrument LIKE 'M:%DDF_DLR%'
           AND instrument NOT LIKE '%A'
           AND time > NOW() - INTERVAL '30 days'
         ORDER BY instrument, time DESC
         LIMIT 6",
        &[],
    ).await?;

    let mut result: Vec<FuturesRow> = rows.iter().map(|r| FuturesRow {
        instrument: r.get(0),
        last_price:  r.get(1),
        bid:         r.get(2),
        ask:         r.get(3),
    }).collect();

    // Sort by expiry month/year ascending (near → far)
    result.sort_by_key(|r| {
        let name = r.instrument.to_uppercase();
        let months = [("ENE",1u32),("FEB",2),("MAR",3),("ABR",4),("MAY",5),("JUN",6),
                      ("JUL",7),("AGO",8),("SEP",9),("OCT",10),("NOV",11),("DIC",12)];
        for (m, n) in &months {
            if let Some(pos) = name.find(m) {
                let year: u32 = name[pos+3..].chars().take(2).collect::<String>().parse().unwrap_or(99);
                return year * 100 + n;
            }
        }
        9999u32
    });
    // Keep at most 3
    result.truncate(3);
    Ok(result)
}

pub async fn fetch_futures_ticks(client: &Client, instrument: &str, limit: i64) -> Result<Vec<HistTick>> {
    let rows = client.query(
        "SELECT time, instrument,
                bid_price::float8, ask_price::float8, last_price::float8, total_volume
         FROM ticks WHERE instrument = $1
         ORDER BY time DESC LIMIT $2",
        &[&instrument, &limit],
    ).await?;
    Ok(rows.iter().map(|r| HistTick {
        time:         r.get(0),
        instrument:   r.get(1),
        bid_price:    r.get(2),
        ask_price:    r.get(3),
        last_price:   r.get(4),
        total_volume: r.get(5),
    }).collect())
}

pub async fn fetch_distinct_merval_instruments(client: &Client, _days: i64) -> Result<Vec<String>> {
    // Recursive CTE skip-scan: uses the (instrument, time DESC) composite index to jump
    // between distinct instrument values instead of scanning all rows.
    // Tested: GROUP BY on 1.4M rows = 3.8s; this CTE = 0.4s (10× faster).
    //
    // Window ladder: try 1 day first (covers current session, ~1 chunk),
    // fall back to 7 days (weekends/holidays), then 30 days.
    const QUERIES: [&str; 3] = [
        "WITH RECURSIVE t(instrument) AS (
            (SELECT instrument FROM ticks
             WHERE time > NOW() - INTERVAL '1 day'
             ORDER BY instrument LIMIT 1)
            UNION ALL
            SELECT (SELECT instrument FROM ticks
                    WHERE instrument > t.instrument
                      AND time > NOW() - INTERVAL '1 day'
                    ORDER BY instrument LIMIT 1)
            FROM t WHERE t.instrument IS NOT NULL
         )
         SELECT instrument FROM t
         WHERE instrument IS NOT NULL
           AND instrument NOT LIKE '%DDF_DLR%'
         ORDER BY instrument LIMIT 300",

        "WITH RECURSIVE t(instrument) AS (
            (SELECT instrument FROM ticks
             WHERE time > NOW() - INTERVAL '7 days'
             ORDER BY instrument LIMIT 1)
            UNION ALL
            SELECT (SELECT instrument FROM ticks
                    WHERE instrument > t.instrument
                      AND time > NOW() - INTERVAL '7 days'
                    ORDER BY instrument LIMIT 1)
            FROM t WHERE t.instrument IS NOT NULL
         )
         SELECT instrument FROM t
         WHERE instrument IS NOT NULL
           AND instrument NOT LIKE '%DDF_DLR%'
         ORDER BY instrument LIMIT 300",

        "WITH RECURSIVE t(instrument) AS (
            (SELECT instrument FROM ticks
             WHERE time > NOW() - INTERVAL '30 days'
             ORDER BY instrument LIMIT 1)
            UNION ALL
            SELECT (SELECT instrument FROM ticks
                    WHERE instrument > t.instrument
                      AND time > NOW() - INTERVAL '30 days'
                    ORDER BY instrument LIMIT 1)
            FROM t WHERE t.instrument IS NOT NULL
         )
         SELECT instrument FROM t
         WHERE instrument IS NOT NULL
           AND instrument NOT LIKE '%DDF_DLR%'
         ORDER BY instrument LIMIT 300",
    ];

    for sql in &QUERIES {
        let rows = client.query(*sql, &[]).await?;
        if !rows.is_empty() {
            return Ok(rows.iter().map(|r| r.get::<_, String>(0)).collect());
        }
    }
    Ok(vec![])
}

pub async fn fetch_instrument_price_series(client: &Client, instrument: &str) -> Result<Vec<(f64, f64)>> {
    // OHLCV by minute for the last session with data, returns (minutes_since_open, price)
    let rows = client.query(
        "WITH session AS (
            SELECT MAX(time::date) AS d FROM ticks WHERE instrument = $1
         )
         SELECT time_bucket('1 minute', time) AS bucket, LAST(last_price, time)::float8
         FROM ticks, session
         WHERE instrument = $1 AND time::date = session.d
         GROUP BY bucket ORDER BY bucket ASC",
        &[&instrument],
    ).await?;
    Ok(rows.iter().enumerate().map(|(i, r)| {
        let price: f64 = r.get(1);
        (i as f64, price)
    }).collect())
}

pub async fn fetch_instrument_price_series_with_times(
    client: &Client, instrument: &str, (bucket_interval, lookback): (&str, &str)
) -> Result<(Vec<(f64, f64)>, Vec<String>)> {
    // Get the last tick time
    let last_row = client.query_opt(
        "SELECT time FROM ticks WHERE instrument = $1 ORDER BY time DESC LIMIT 1",
        &[&instrument],
    ).await?;
    let last_time: chrono::DateTime<chrono::Utc> = match last_row {
        Some(r) => r.get(0),
        None => return Ok((vec![], vec![])),
    };

    // Compute start_time in Rust to avoid $param - INTERVAL arithmetic in SQL
    let lookback_secs: i64 = match lookback {
        "5 minutes"  => 5 * 60,
        "30 minutes" => 30 * 60,
        "1 hour"     => 3600,
        "3 days"     => 3   * 86400,
        "1 day"      => 86400,
        "7 days"     => 7   * 86400,
        "30 days"    => 30  * 86400,
        "90 days"    => 90  * 86400,
        "180 days"   => 180 * 86400,
        "365 days"   => 365 * 86400,
        _            => 30  * 86400,
    };
    let start_time = last_time - chrono::Duration::seconds(lookback_secs);

    let sql = format!(
        "SELECT time_bucket('{bucket_interval}', time) AS b, LAST(last_price, time)::float8
         FROM ticks
         WHERE instrument = $1 AND time > $2 AND time <= $3
         GROUP BY b ORDER BY b ASC"
    );
    let rows = client.query(sql.as_str(), &[&instrument, &start_time, &last_time]).await?;
    if rows.is_empty() { return Ok((vec![], vec![])); }

    let tz = chrono::FixedOffset::west_opt(3 * 3600).unwrap();
    let mut points = Vec::new();
    let mut labels = Vec::new();
    for r in &rows {
        let b: chrono::DateTime<chrono::Utc> = r.get(0);
        let price: f64 = r.get(1);
        let i = points.len();
        points.push((i as f64, price));
        labels.push(b.with_timezone(&tz).format("%d/%m %H:%M").to_string());
    }
    Ok((points, labels))
}

pub async fn fetch_instrument_orders(client: &Client, instrument: &str) -> Result<Vec<HistOrder>> {
    // orders table has no M: prefix; strip it
    let instr = instrument.trim_start_matches("M:");
    let rows = client.query(
        "SELECT time, instrument, price::float8, volume, side
         FROM orders WHERE instrument = $1
         ORDER BY time DESC LIMIT 500",
        &[&instr],
    ).await?;
    Ok(rows.iter().map(|r| {
        let side_char: &str = r.get(4);
        HistOrder {
            time:       r.get(0),
            instrument: r.get(1),
            price:      r.get(2),
            volume:     r.get(3),
            side:       side_char.trim().to_string(),
        }
    }).collect())
}

// ─── US Futures ───────────────────────────────────────────────────────────────

#[derive(Clone, Debug, serde::Deserialize)]
pub struct UsFuturesOhlcv {
    pub time:   chrono::DateTime<chrono::Utc>,
    pub symbol: String,
    pub open:   f64,
    pub high:   f64,
    pub low:    f64,
    pub close:  f64,
    pub volume: i64,
}

// ─── Markets tab ──────────────────────────────────────────────────────────────

#[derive(Clone, Debug, serde::Deserialize)]
pub struct MarketRow {
    pub symbol:      String,
    pub last_price:  f64,
    pub change_pct:  f64,
    pub region:      String,
    pub asset_class: String,
}
