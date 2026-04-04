use crossterm::event::{Event, KeyEvent};
use tokio::sync::mpsc;

/// Spawn a background blocking thread that reads crossterm events
/// and forwards them through an mpsc channel.
/// This prevents the synchronous `crossterm::event::read()` from
/// blocking the Tokio async executor.
pub fn spawn_input_task() -> mpsc::UnboundedReceiver<KeyEvent> {
    let (tx, rx) = mpsc::unbounded_channel();

    std::thread::spawn(move || loop {
        // `read()` blocks until an event is available — safe in a dedicated OS thread
        match crossterm::event::read() {
            Ok(Event::Key(key)) => {
                if tx.send(key).is_err() {
                    break; // receiver dropped → app exited
                }
            }
            Ok(_) => {} // ignore mouse, resize, etc.
            Err(_) => break,
        }
    });

    rx
}