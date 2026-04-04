use chrono::{Local, Timelike};

pub mod tick;
pub mod order;

#[allow(unused_imports)]
pub use tick::Tick;
pub use order::Order;

// ─── Binance per-symbol state ──────────────────────────────────────────────

#[derive(Clone)]
pub struct BinanceSymbolData {
    pub symbol: String,
    pub open: f64,
    pub high: f64,
    pub low: f64,
    pub close: f64,
    /// Base-asset volume from the kline (e.g. SOL, BTC)
    pub volume: f64,
    /// close × volume — USD-equivalent volume used for cross-symbol sorting
    pub usd_volume: f64,
    /// Sparkline history: normalised as relative integers within the symbol's own range
    pub price_history: Vec<u64>,
    pub daily_change_pct: f64,
    pub last_update: String,
}

impl BinanceSymbolData {
    pub fn new(symbol: &str) -> Self {
        Self {
            symbol: symbol.to_string(),
            open: 0.0,
            high: 0.0,
            low: 0.0,
            close: 0.0,
            volume: 0.0,
            usd_volume: 0.0,
            // Start EMPTY — no leading zeros that would flatten the sparkline
            price_history: Vec::new(),
            daily_change_pct: 0.0,
            last_update: "Waiting...".to_string(),
        }
    }

    pub fn update(&mut self, open: f64, high: f64, low: f64, close: f64, volume: f64) {
        // Lock the session open price on the first tick received
        if self.open == 0.0 && open > 0.0 {
            self.open = open;
        }
        self.high = high;
        self.low = low;
        self.close = close;
        self.volume = volume;
        // USD-equivalent: multiply by close so all symbols are on the same scale
        self.usd_volume = close * volume;

        if self.open > 0.0 {
            self.daily_change_pct = ((close - self.open) / self.open) * 100.0;
        }

        // Store close as a u64 integer (×100) so ratatui's Sparkline can draw it.
        // The Sparkline auto-scales to the min/max of the slice, so the absolute
        // magnitude doesn't matter — only relative movement within the symbol.
        let scaled = (close * 100.0) as u64;
        self.price_history.push(scaled);
        if self.price_history.len() > 120 {
            self.price_history.remove(0);
        }

        self.last_update = Local::now().format("%H:%M:%S").to_string();
    }
}

// ─── Recent trade ──────────────────────────────────────────────────────────

#[derive(Clone, Debug)]
pub struct RecentTrade {
    pub symbol: String,
    pub price: f64,
    pub quantity: f64,
    /// true = seller was the maker (i.e. this was a sell-side aggression)
    pub is_buyer_maker: bool,
    pub time: String,
}

// ─── MERVAL / generic exchange state (kept for Merval tab) ────────────────

#[derive(Clone)]
pub struct ExchangeData {
    pub name: String,
    pub symbol: String,
    pub quote_currency: String,
    pub volume_currency: String,
    pub current_price: f64,
    pub ticks: Vec<u64>,
    pub volume_24h: f64,
    pub high_24h: f64,
    pub low_24h: f64,
    pub daily_change: f64,
    pub order_book_depth: u32,
    pub market_status: String,
    pub last_update: String,
    pub connected: bool,
    pub decimal_places: u32,
}

impl ExchangeData {
    pub fn new(name: &str, quote_currency: &str, decimal_places: u32) -> Self {
        Self {
            name: name.to_string(),
            symbol: if name == "Binance" { "BTC/USDT".to_string() } else { "MERVAL".to_string() },
            quote_currency: quote_currency.to_string(),
            volume_currency: if name == "Binance" { "BTC".to_string() } else { "ARS".to_string() },
            current_price: 0.0,
            ticks: vec![0; 50],
            volume_24h: 0.0,
            high_24h: 0.0,
            low_24h: 0.0,
            daily_change: 0.0,
            order_book_depth: 0,
            market_status: "Unknown".to_string(),
            last_update: "Never".to_string(),
            connected: false,
            decimal_places,
        }
    }

    pub fn update_price(&mut self, price: f64, volume: f64) {
        self.current_price = price;
        self.volume_24h = volume;

        if price > self.high_24h { self.high_24h = price; }
        if self.low_24h == 0.0 || price < self.low_24h { self.low_24h = price; }

        if !self.ticks.is_empty() && self.ticks[0] > 0 {
            let old_price = self.ticks[0] as f64 / 100.0;
            self.daily_change = ((price - old_price) / old_price) * 100.0;
        }

        let multiplier = 10_u64.pow(self.decimal_places);
        let scaled_price = (price * multiplier as f64) as u64;
        self.ticks.push(scaled_price);
        if self.ticks.len() > 100 { self.ticks.remove(0); }

        self.last_update = Local::now().format("%H:%M:%S").to_string();

        if self.name == "MERVAL" {
            let hour = Local::now().hour();
            self.market_status = if hour >= 11 && hour <= 17 {
                "Open".to_string()
            } else {
                "Closed".to_string()
            };
        } else {
            self.market_status = "24/7".to_string();
        }
    }
}