use chrono::{DateTime, Utc};

#[derive(Clone, Debug)]
pub struct Tick {
    pub price: f64,
    pub volume: u32,
    pub timestamp: DateTime<Utc>,
    pub side: String, // "BUY" or "SELL"
}

impl Tick {
    pub fn new(price: f64, volume: u32, side: String) -> Self {
        Self {
            price,
            volume,
            side,
            timestamp: Utc::now(),
        }
    }
}