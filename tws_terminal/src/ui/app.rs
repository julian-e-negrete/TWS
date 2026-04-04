use ratatui::{
    layout::{Constraint, Direction, Layout, Rect},
    style::{Color, Modifier, Style},
    text::{Line, Span},
    widgets::{Block, Borders, Paragraph, Sparkline, Table, TableState},
    Frame,
};
use crate::data::{Tick, Order};
use crate::network::WebSocketMessage;

#[derive(PartialEq)]
pub enum InputMode {
    Normal,
    EditingOrder,
}

pub struct TradingApp {
    // Market data
    pub ticks: Vec<u64>,  // Changed from f64 to u64 for Sparkline
    pub current_price: f64,
    pub volume_24h: u64,
    
    // Order management
    pub orders: Vec<Order>,
    pub orders_table_state: TableState,
    pub selected_order_index: usize,
    
    // UI state
    pub input_mode: InputMode,
    pub order_input: String,
    pub ws_connected: bool,
    pub error_message: Option<String>,
}

impl TradingApp {
    pub fn new() -> Self {
        Self {
            ticks: vec![0; 50],  // Initialize with zeros
            current_price: 0.0,
            volume_24h: 0,
            orders: Vec::new(),
            orders_table_state: TableState::default(),
            selected_order_index: 0,
            input_mode: InputMode::Normal,
            order_input: String::new(),
            ws_connected: false,
            error_message: None,
        }
    }
    
    pub fn handle_websocket_message(&mut self, msg: WebSocketMessage) {
        match msg {
            WebSocketMessage::PriceUpdate(price) => {
                self.current_price = price;
                // Convert f64 to u64 for Sparkline (scale it)
                let scaled_price = (price * 100.0) as u64;  // Keep 2 decimal precision
                self.ticks.push(scaled_price);
                if self.ticks.len() > 100 {
                    self.ticks.remove(0);
                }
            }
            WebSocketMessage::OrderUpdate(order) => {
                self.orders.push(order);
            }
            WebSocketMessage::Connected => {
                self.ws_connected = true;
                self.error_message = None;
            }
            WebSocketMessage::Disconnected => {
                self.ws_connected = false;
            }
            WebSocketMessage::Error(err) => {
                self.error_message = Some(err);
            }
        }
    }
    
    pub fn handle_input(&mut self, event: crossterm::event::KeyEvent) -> bool {
        match self.input_mode {
            InputMode::Normal => match event.code {
                crossterm::event::KeyCode::Char('q') => return false,
                crossterm::event::KeyCode::Char('o') => {
                    self.input_mode = InputMode::EditingOrder;
                    self.order_input.clear();
                }
                crossterm::event::KeyCode::Up => {
                    if self.selected_order_index > 0 {
                        self.selected_order_index -= 1;
                        self.orders_table_state.select(Some(self.selected_order_index));
                    }
                }
                crossterm::event::KeyCode::Down => {
                    if self.selected_order_index < self.orders.len().saturating_sub(1) {
                        self.selected_order_index += 1;
                        self.orders_table_state.select(Some(self.selected_order_index));
                    }
                }
                _ => {}
            },
            InputMode::EditingOrder => match event.code {
                crossterm::event::KeyCode::Enter => {
                    let parts: Vec<&str> = self.order_input.split_whitespace().collect();
                    if parts.len() == 3 {
                        let side = parts[0].to_uppercase();
                        if let (Ok(qty), Ok(price)) = (parts[1].parse::<u32>(), parts[2].parse::<f64>()) {
                            let order = Order::new(side, price, qty);
                            self.orders.push(order);
                        }
                    }
                    self.input_mode = InputMode::Normal;
                    self.order_input.clear();
                }
                crossterm::event::KeyCode::Char(c) => self.order_input.push(c),
                crossterm::event::KeyCode::Backspace => {
                    self.order_input.pop();
                }
                crossterm::event::KeyCode::Esc => {
                    self.input_mode = InputMode::Normal;
                    self.order_input.clear();
                }
                _ => {}
            },
        }
        true
    }
    
    pub fn render(&mut self, frame: &mut Frame) {
        let chunks = Layout::default()
            .direction(Direction::Vertical)
            .constraints([
                Constraint::Length(3),   // Status bar
                Constraint::Length(8),   // Price chart
                Constraint::Min(10),     // Order book
                Constraint::Length(3),   // Input line
            ])
            .split(frame.size());
        
        self.render_status_bar(chunks[0], frame);
        self.render_price_chart(chunks[1], frame);
        self.render_order_book(chunks[2], frame);
        self.render_input_area(chunks[3], frame);
    }
    
    fn render_status_bar(&self, area: Rect, frame: &mut Frame) {
        let status = if self.ws_connected {
            Span::styled("● CONNECTED", Style::default().fg(Color::Green))
        } else {
            Span::styled("○ DISCONNECTED", Style::default().fg(Color::Red))
        };
        
        let price = Span::styled(
            format!("Price: ${:.2}", self.current_price),
            Style::default().fg(Color::Cyan).add_modifier(Modifier::BOLD)
        );
        
        let error = if let Some(err) = &self.error_message {
            Span::styled(format!(" ⚠ {}", err), Style::default().fg(Color::Yellow))
        } else {
            Span::raw("")
        };
        
        let line = Line::from(vec![status, Span::raw(" | "), price, error]);
        let paragraph = Paragraph::new(line).block(Block::default().borders(Borders::TOP));
        frame.render_widget(paragraph, area);
    }
    
    fn render_price_chart(&self, area: Rect, frame: &mut Frame) {
        let sparkline = Sparkline::default()
            .block(Block::default().borders(Borders::ALL).title("Price (Last 100 ticks)"))
            .data(&self.ticks)  // Now this works with u64
            .style(Style::default().fg(Color::Green));
        
        frame.render_widget(sparkline, area);
    }
    
    fn render_order_book(&mut self, area: Rect, frame: &mut Frame) {
        let header_style = Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD);
        let header = vec!["ID", "Side", "Price", "Qty", "Status"];
        
        let rows: Vec<ratatui::widgets::Row> = self.orders.iter().map(|order| {
            let side_style = if order.side == "BUY" {
                Style::default().fg(Color::Green)
            } else {
                Style::default().fg(Color::Red)
            };
            
            ratatui::widgets::Row::new(vec![
                order.id.to_string(),
                order.side.clone(),
                format!("${:.2}", order.price),
                order.quantity.to_string(),
                order.status.clone(),
            ]).style(side_style)
        }).collect();
        
        // Fix: Add widths parameter to Table::new
        let widths = vec![
            Constraint::Length(5),
            Constraint::Length(6),
            Constraint::Length(10),
            Constraint::Length(8),
            Constraint::Length(10),
        ];
        
        let table = Table::new(rows, widths)  // Now with correct number of arguments
            .header(ratatui::widgets::Row::new(header).style(header_style))
            .block(Block::default().borders(Borders::ALL).title("Active Orders"))
            .highlight_style(Style::default().add_modifier(Modifier::BOLD))
            .highlight_symbol("> ");
        
        frame.render_stateful_widget(table, area, &mut self.orders_table_state);
    }
    
    fn render_input_area(&self, area: Rect, frame: &mut Frame) {
        let input_style = if self.input_mode == InputMode::EditingOrder {
            Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD)
        } else {
            Style::default()
        };
        
        let input_text = if self.input_mode == InputMode::EditingOrder {
            format!("> {}", self.order_input)
        } else {
            "Press 'o' to enter order".to_string()
        };
        
        let input_paragraph = Paragraph::new(input_text)
            .block(Block::default().borders(Borders::ALL).title("Order Entry"))
            .style(input_style);
        
        frame.render_widget(input_paragraph, area);
    }
}