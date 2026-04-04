// Custom widgets for your terminal
use ratatui::widgets::{Block, Borders, Paragraph};
use ratatui::layout::Rect;
use ratatui::Frame;

pub struct OrderBookWidget {
    pub bids: Vec<(f64, u32)>,
    pub asks: Vec<(f64, u32)>,
}

impl OrderBookWidget {
    pub fn render(&self, area: Rect, frame: &mut Frame) {
        let block = Block::default().borders(Borders::ALL).title("Order Book Depth");
        let paragraph = Paragraph::new(format!(
            "Bids: {:?}\nAsks: {:?}",
            &self.bids[..self.bids.len().min(5)],
            &self.asks[..self.asks.len().min(5)]
        )).block(block);
        
        frame.render_widget(paragraph, area);
    }
}