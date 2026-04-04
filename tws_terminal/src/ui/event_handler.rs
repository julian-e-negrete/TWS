use crossterm::event::{Event, KeyEvent, poll, read};
use std::time::Duration;

pub async fn handle_events(
    tick_rate: Duration,
    last_tick: &mut tokio::time::Instant,
) -> anyhow::Result<Option<KeyEvent>> {
    if poll(Duration::from_millis(50))? {
        if let Event::Key(key) = read()? {
            return Ok(Some(key));
        }
    }
    
    if last_tick.elapsed() >= tick_rate {
        *last_tick = tokio::time::Instant::now();
    }
    
    Ok(None)
}