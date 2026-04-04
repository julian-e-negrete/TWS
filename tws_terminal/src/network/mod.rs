pub mod websocket;

use crate::data::Order;  // Add this import

#[derive(Debug)]
pub enum WebSocketMessage {
    PriceUpdate(f64),
    OrderUpdate(Order),  // Now Order is in scope
    Connected,
    Disconnected,
    Error(String),
}