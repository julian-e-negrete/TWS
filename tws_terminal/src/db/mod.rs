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
