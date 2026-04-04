pub mod websocket;

use crate::data::Order;
use serde::Deserialize;

// ── Custom deserializer: accepts both `"1.23"` strings and `1.23` numbers ──

fn de_f64_or_str<'de, D>(de: D) -> Result<f64, D::Error>
where
    D: serde::Deserializer<'de>,
{
    use serde::de::{self, Unexpected};

    struct F64OrStr;
    impl<'de> de::Visitor<'de> for F64OrStr {
        type Value = f64;
        fn expecting(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
            write!(f, "a float or a string containing a float")
        }
        fn visit_f64<E: de::Error>(self, v: f64) -> Result<f64, E> { Ok(v) }
        fn visit_i64<E: de::Error>(self, v: i64) -> Result<f64, E> { Ok(v as f64) }
        fn visit_u64<E: de::Error>(self, v: u64) -> Result<f64, E> { Ok(v as f64) }
        fn visit_str<E: de::Error>(self, v: &str) -> Result<f64, E> {
            v.parse::<f64>().map_err(|_| de::Error::invalid_value(Unexpected::Str(v), &self))
        }
    }

    de.deserialize_any(F64OrStr)
}

fn de_u64_or_str<'de, D>(de: D) -> Result<u64, D::Error>
where
    D: serde::Deserializer<'de>,
{
    use serde::de::{self, Unexpected};

    struct U64OrStr;
    impl<'de> de::Visitor<'de> for U64OrStr {
        type Value = u64;
        fn expecting(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
            write!(f, "a u64 or a string containing a u64")
        }
        fn visit_f64<E: de::Error>(self, v: f64) -> Result<u64, E> { Ok(v as u64) }
        fn visit_i64<E: de::Error>(self, v: i64) -> Result<u64, E> { Ok(v as u64) }
        fn visit_u64<E: de::Error>(self, v: u64) -> Result<u64, E> { Ok(v) }
        fn visit_str<E: de::Error>(self, v: &str) -> Result<u64, E> {
            v.parse::<u64>().map_err(|_| de::Error::invalid_value(Unexpected::Str(v), &self))
        }
    }

    de.deserialize_any(U64OrStr)
}

// ── Binance kline / tick ────────────────────────────────────────────────────
// Matches: {"symbol":"BTCUSDT","timestamp":"...","open":"67000","high":"...","low":"...","close":"...","volume":"..."}

#[derive(Debug, Clone, Deserialize)]
pub struct BinanceTick {
    pub symbol: String,
    pub timestamp: String,
    #[serde(deserialize_with = "de_f64_or_str")]
    pub open: f64,
    #[serde(deserialize_with = "de_f64_or_str")]
    pub high: f64,
    #[serde(deserialize_with = "de_f64_or_str")]
    pub low: f64,
    #[serde(deserialize_with = "de_f64_or_str")]
    pub close: f64,
    #[serde(deserialize_with = "de_f64_or_str")]
    pub volume: f64,
}

// ── Binance individual trade ────────────────────────────────────────────────
// Matches: {"time":"...","symbol":"...","price":"81.05","qty":"0.06","is_buyer_maker":false,"trade_id":648141824}

#[derive(Debug, Clone, Deserialize)]
pub struct BinanceTrade {
    pub symbol: String,
    pub time: String,
    #[serde(deserialize_with = "de_f64_or_str")]
    pub price: f64,
    /// Field is called "qty" in the Redis payload
    #[serde(rename = "qty", deserialize_with = "de_f64_or_str")]
    pub quantity: f64,
    pub is_buyer_maker: bool,
    #[serde(deserialize_with = "de_u64_or_str")]
    pub trade_id: u64,
}

// ── App-level message enum ──────────────────────────────────────────────────

#[derive(Debug)]
pub enum WebSocketMessage {
    TickUpdate(BinanceTick),
    TradeUpdate(BinanceTrade),
    OrderUpdate(Order),
    Connected(String),
    Disconnected(String),
    Error(String),
    PriceUpdate(String, f64, f64),
}