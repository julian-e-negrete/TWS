pub mod websocket;

use crate::data::Order;

#[derive(Debug)]
pub enum WebSocketMessage {
    PriceUpdate(String, f64, f64),  // (exchange, price, volume)
    OrderUpdate(Order),
    Connected(String),  // exchange name
    Disconnected(String),
    Error(String),
}