pub mod tick;
pub mod order;

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