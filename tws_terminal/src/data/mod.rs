use chrono::Timelike;

pub mod tick;
pub mod order;

#[allow(unused_imports)]
pub use tick::Tick;
pub use order::Order;

#[derive(Clone)]
pub struct MarketData {
    pub symbol: String,
    pub bid: f64,
    pub ask: f64,
    pub last_price: f64,
    pub volume: u64,
}

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
        
        // Update high/low
        if price > self.high_24h { self.high_24h = price; }
        if self.low_24h == 0.0 || price < self.low_24h { self.low_24h = price; }
        
        // Calculate daily change (simplified)
        if self.ticks.len() > 0 && self.ticks[0] > 0 {
            let old_price = self.ticks[0] as f64 / 100.0;
            self.daily_change = ((price - old_price) / old_price) * 100.0;
        }
        
        // Scale for sparkline based on decimal places
        let multiplier = 10_u64.pow(self.decimal_places);
        let scaled_price = (price * multiplier as f64) as u64;
        self.ticks.push(scaled_price);
        if self.ticks.len() > 100 {
            self.ticks.remove(0);
        }
        
        // Update timestamp
        use chrono::Local;
        self.last_update = Local::now().format("%H:%M:%S").to_string();
        
        // Simulate market status (for MERVAL)
        if self.name == "MERVAL" {
            let hour = chrono::Local::now().hour();
            self.market_status = if hour >= 11 && hour <= 17 {
                "Open".to_string()
            } else {
                "Closed".to_string()
            }.to_string();
        } else {
            self.market_status = "24/7".to_string();
        }
    }
}