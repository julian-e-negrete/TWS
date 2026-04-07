use anyhow::Result;
use futures_util::StreamExt;
use tokio::sync::mpsc::UnboundedSender;

use crate::network::{BinanceTick, BinanceTrade, MatrizOrder, MatrizTick, UsFuturesTick, WebSocketMessage};

const REDIS_URL: &str = "redis://100.112.16.115:6379";
const CHANNEL_TICKS: &str = "binance:ticks";
const CHANNEL_TRADES: &str = "binance:trades";
const CHANNEL_US_FUTURES: &str = "us_futures:ticks";
const CHANNEL_MATRIZ_TICKS: &str = "matriz:ticks";
const CHANNEL_MATRIZ_ORDERS: &str = "matriz:orders";

/// Entry point: connects to Redis and subscribes to both Binance channels.
/// Retries indefinitely with a 5-second back-off on failure.
pub async fn connect_websocket(tx: UnboundedSender<WebSocketMessage>) -> Result<()> {
    loop {
        let _ = tx.send(WebSocketMessage::Error(
            "Connecting to Redis at 100.112.16.115:6379...".to_string(),
        ));

        match try_connect(tx.clone()).await {
            Ok(_) => {
                // Stream ended cleanly — reconnect anyway
            }
            Err(e) => {
                let _ = tx.send(WebSocketMessage::Error(format!("Redis error: {e}")));
            }
        }

        let _ = tx.send(WebSocketMessage::Disconnected("binance".to_string()));
        tokio::time::sleep(tokio::time::Duration::from_secs(5)).await;
    }
}

async fn try_connect(tx: UnboundedSender<WebSocketMessage>) -> Result<()> {
    let client = redis::Client::open(REDIS_URL)?;
    let conn = client.get_async_connection().await?;

    let mut pubsub = conn.into_pubsub();
    pubsub.subscribe(CHANNEL_TICKS).await?;
    pubsub.subscribe(CHANNEL_TRADES).await?;
    pubsub.subscribe(CHANNEL_US_FUTURES).await?;
    pubsub.subscribe(CHANNEL_MATRIZ_TICKS).await?;
    pubsub.subscribe(CHANNEL_MATRIZ_ORDERS).await?;

    let _ = tx.send(WebSocketMessage::Connected("binance".to_string()));

    let mut stream = pubsub.on_message();

    while let Some(msg) = stream.next().await {
        let channel = msg.get_channel_name().to_string();

        let payload: String = match msg.get_payload() {
            Ok(p) => p,
            Err(_) => continue,
        };

        match channel.as_str() {
            c if c == CHANNEL_TICKS => {
                if let Ok(tick) = serde_json::from_str::<BinanceTick>(&payload) {
                    let _ = tx.send(WebSocketMessage::TickUpdate(tick));
                }
            }
            c if c == CHANNEL_TRADES => {
                if let Ok(trade) = serde_json::from_str::<BinanceTrade>(&payload) {
                    let _ = tx.send(WebSocketMessage::TradeUpdate(trade));
                }
            }
            c if c == CHANNEL_US_FUTURES => {
                if let Ok(tick) = serde_json::from_str::<UsFuturesTick>(&payload) {
                    let _ = tx.send(WebSocketMessage::UsFuturesTick(tick));
                }
            }
            c if c == CHANNEL_MATRIZ_TICKS => {
                if let Ok(tick) = serde_json::from_str::<MatrizTick>(&payload) {
                    let _ = tx.send(WebSocketMessage::MatrizTick(tick));
                }
            }
            c if c == CHANNEL_MATRIZ_ORDERS => {
                if let Ok(order) = serde_json::from_str::<MatrizOrder>(&payload) {
                    let _ = tx.send(WebSocketMessage::MatrizOrder(order));
                }
            }
            _ => {}
        }
    }

    Err(anyhow::anyhow!("Redis pub/sub stream closed"))
}