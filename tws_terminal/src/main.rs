mod ui;
mod data;
mod network;

use anyhow::Result;
use crossterm::{
    event::{DisableMouseCapture, EnableMouseCapture},
    execute,
    terminal::{disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen},
};
use ratatui::backend::CrosstermBackend;
use ratatui::Terminal;
use std::io;
use tokio::sync::mpsc;
use tokio::time;

use ui::app::TradingApp;
use ui::event_handler::handle_events;
use network::websocket::connect_websocket;

#[tokio::main]
async fn main() -> Result<()> {
    // Setup terminal
    enable_raw_mode()?;
    let mut stdout = io::stdout();
    execute!(stdout, EnterAlternateScreen, EnableMouseCapture)?;
    let backend = CrosstermBackend::new(stdout);
    let mut terminal = Terminal::new(backend)?;
    
    // Create channel for WebSocket messages
    let (tx, mut rx) = mpsc::unbounded_channel();
    
    // Start WebSocket connection
    let ws_handle = tokio::spawn(async move {
        if let Err(e) = connect_websocket(tx).await {
            eprintln!("WebSocket error: {}", e);
        }
    });
    
    // Initialize app
    let mut app = TradingApp::new();
    
    // Main event loop
    let tick_rate = time::Duration::from_millis(100);
    let mut last_tick = tokio::time::Instant::now();
    
    loop {
        // Check for WebSocket messages
        while let Ok(msg) = rx.try_recv() {
            app.handle_websocket_message(msg);
        }
        
        // Draw UI
        terminal.draw(|f| app.render(f))?;
        
        // Handle input
        if let Some(event) = handle_events(tick_rate, &mut last_tick).await? {
            if !app.handle_input(event) {
                break; // Quit if app says so
            }
        }
    }
    
    // Cleanup
    disable_raw_mode()?;
    execute!(
        terminal.backend_mut(),
        LeaveAlternateScreen,
        DisableMouseCapture
    )?;
    ws_handle.abort();
    
    Ok(())
}