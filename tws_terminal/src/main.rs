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
use ui::event_handler::spawn_input_task;
use network::websocket::connect_websocket;

#[tokio::main]
async fn main() -> Result<()> {
    // ── Terminal setup ───────────────────────────────────────────────────────
    enable_raw_mode()?;
    let mut stdout = io::stdout();
    execute!(stdout, EnterAlternateScreen, EnableMouseCapture)?;
    let backend = CrosstermBackend::new(stdout);
    let mut terminal = Terminal::new(backend)?;

    // ── Channel: Redis/websocket → app ───────────────────────────────────────
    let (ws_tx, mut ws_rx) = mpsc::unbounded_channel();

    // ── Spawn Redis subscriber on a separate Tokio task ──────────────────────
    let ws_handle = tokio::spawn(async move {
        // connect_websocket loops forever with retries — it never returns Ok
        if let Err(e) = connect_websocket(ws_tx).await {
            eprintln!("Redis subscriber fatal error: {e}");
        }
    });

    // ── Keyboard input on a dedicated OS thread (blocking read, not async) ───
    let mut key_rx = spawn_input_task();

    // ── App state ─────────────────────────────────────────────────────────────
    let mut app = TradingApp::new();

    // ── Render ticker: redraw at ~30 fps regardless of events ─────────────────
    let mut render_interval = time::interval(time::Duration::from_millis(33));

    // ── Main event loop ───────────────────────────────────────────────────────
    loop {
        tokio::select! {
            // Redraw tick
            _ = render_interval.tick() => {
                terminal.draw(|f| app.render(f))?;
            }

            // Redis data message
            Some(msg) = ws_rx.recv() => {
                app.handle_websocket_message(msg);
            }

            // Keyboard input
            Some(key) = key_rx.recv() => {
                if !app.handle_input(key) {
                    break; // 'q' pressed
                }
            }
        }
    }

    // ── Cleanup ───────────────────────────────────────────────────────────────
    disable_raw_mode()?;
    execute!(
        terminal.backend_mut(),
        LeaveAlternateScreen,
        DisableMouseCapture
    )?;
    ws_handle.abort();

    Ok(())
}