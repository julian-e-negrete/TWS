use anyhow::Result;
use tokio::sync::mpsc::UnboundedSender;
use crate::network::WebSocketMessage;
use rand::Rng;

// Use a thread-local RNG that doesn't need to be Send
pub async fn connect_websocket(tx: UnboundedSender<WebSocketMessage>) -> Result<()> {
    // Simulate connection to both exchanges
    let _ = tx.send(WebSocketMessage::Connected("binance".to_string()));
    let _ = tx.send(WebSocketMessage::Connected("merval".to_string()));
    
    let mut binance_price = 45000.0;
    let mut merval_price = 125000.0;
    
    // Simulate price updates for both exchanges
    for _ in 0..1000 {
        // Generate random values without holding RNG across await
        let (binance_change, binance_volume, merval_change, merval_volume) = {
            let mut rng = rand::thread_rng();
            (
                (rng.gen::<f64>() - 0.5) * 0.01,
                rng.gen::<f64>() * 100.0,
                (rng.gen::<f64>() - 0.5) * 0.004,
                rng.gen::<f64>() * 1000000.0,
            )
        };
        
        // Binance: Crypto-style volatility
        binance_price *= 1.0 + binance_change;
        let _ = tx.send(WebSocketMessage::PriceUpdate(
            "binance".to_string(),
            binance_price,
            binance_volume
        ));
        
        // MERVAL: Stock market style
        merval_price *= 1.0 + merval_change;
        let _ = tx.send(WebSocketMessage::PriceUpdate(
            "merval".to_string(),
            merval_price,
            merval_volume
        ));
        
        tokio::time::sleep(tokio::time::Duration::from_millis(500)).await;
    }
    
    Ok(())
}