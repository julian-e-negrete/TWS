use anyhow::Result;
use chrono::{DateTime, NaiveDate, Utc};
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

pub async fn fetch_distinct_instruments(client: &Client) -> Result<Vec<String>> {
    let rows = client.query(
        "SELECT DISTINCT instrument FROM ticks ORDER BY instrument", &[]
    ).await?;
    Ok(rows.iter().map(|r| r.get::<_, String>(0)).collect())
}

pub async fn fetch_distinct_dates(client: &Client) -> Result<Vec<String>> {
    let rows = client.query(
        "SELECT DISTINCT d FROM (
            SELECT time::date::text AS d FROM ticks
            UNION
            SELECT timestamp::date::text FROM binance_ticks
         ) t ORDER BY 1 DESC LIMIT 90",
        &[],
    ).await?;
    Ok(rows.iter().map(|r| r.get::<_, String>(0)).collect())
}

pub async fn fetch_distinct_binance_symbols(client: &Client) -> Result<Vec<String>> {
    let rows = client.query(
        "SELECT DISTINCT symbol FROM binance_ticks ORDER BY symbol", &[]
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
    // Get distinct liquid option instruments (have live bid/ask in last 7 days)
    let instruments = client.query(
        "SELECT DISTINCT instrument FROM ticks
         WHERE (instrument LIKE '%GFGC%' OR instrument LIKE '%GFGV%')
           AND time > NOW() - INTERVAL '7 days'
           AND bid_price > 0 AND ask_price > 0",
        &[],
    ).await?;

    let mut rows = Vec::new();
    for row in &instruments {
        let tick_instr: &str = row.get(0);
        // Strip M: prefix for orders table lookup (orders uses no M: prefix)
        let order_instr = tick_instr.trim_start_matches("M:");

        // Best bid/ask from LOB: MAX(bid) and MIN(ask) from the last session with data
        let tick = client.query_opt(
            "SELECT COALESCE(MAX(bid_price), 0)::float8, COALESCE(MIN(ask_price), 0)::float8
             FROM ticks WHERE instrument = $1
               AND time::date = (
                   SELECT MAX(time::date) FROM ticks
                   WHERE instrument = $1 AND bid_price > 0 AND ask_price > 0
               )
               AND bid_price > 0 AND ask_price > 0",
            &[&tick_instr],
        ).await?;

        // Latest executed trade price from orders
        let order = client.query_opt(
            "SELECT price::float8 FROM orders WHERE instrument = $1
             ORDER BY time DESC LIMIT 1",
            &[&order_instr],
        ).await?;

        if let Some(t) = tick {
            let bid: f64 = t.get(0);
            let ask: f64 = t.get(1);
            if bid > 0.0 && ask > 0.0 {
                rows.push(OptionRow {
                    instrument: tick_instr.to_string(),
                    last_price:  order.as_ref().map(|r| r.get::<_, f64>(0)).unwrap_or(0.0),
                    bid,
                    ask,
                });
            }
        }
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
    // Get the 3 contracts with the most recent tick data
    let rows = client.query(
        "SELECT instrument,
                last_price::float8, bid_price::float8, ask_price::float8
         FROM (
             SELECT DISTINCT ON (instrument) instrument,
                    last_price, bid_price, ask_price, time
             FROM ticks
             WHERE instrument LIKE '%DDF_DLR%'
               AND time > NOW() - INTERVAL '90 days'
             ORDER BY instrument, time DESC
         ) sub
         ORDER BY time DESC
         LIMIT 3",
        &[],
    ).await?;
    Ok(rows.iter().map(|r| FuturesRow {
        instrument: r.get(0),
        last_price:  r.get(1),
        bid:         r.get(2),
        ask:         r.get(3),
    }).collect())
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
