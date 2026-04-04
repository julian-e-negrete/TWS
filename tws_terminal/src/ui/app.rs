use ratatui::{
    layout::{Constraint, Direction, Layout, Rect},
    style::{Color, Modifier, Style},
    text::{Line, Span, Text},
    widgets::{Block, Borders, Paragraph, Sparkline, Table, TableState, Tabs},
    Frame,
};
use crate::data::{Order, ExchangeData};
use crate::network::WebSocketMessage;

#[derive(PartialEq, Clone, Copy, Debug)]  // Add Debug here
pub enum ExchangeTab {
    Binance,
    Merval,
}

impl ExchangeTab {
    fn title(&self) -> &'static str {
        match self {
            ExchangeTab::Binance => " Binance ",
            ExchangeTab::Merval => " MERVAL ",
        }
    }
    
    fn color(&self) -> Color {
        match self {
            ExchangeTab::Binance => Color::Yellow,
            ExchangeTab::Merval => Color::LightBlue,
        }
    }
}

#[derive(PartialEq)]
pub enum InputMode {
    Normal,
    EditingOrder,
}

pub struct TradingApp {
    // Current active tab
    pub active_tab: ExchangeTab,
    
    // Exchange-specific data
    pub binance_data: ExchangeData,
    pub merval_data: ExchangeData,
    
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
            active_tab: ExchangeTab::Binance,
            binance_data: ExchangeData::new("Binance", "USDT", 2),
            merval_data: ExchangeData::new("MERVAL", "ARS", 0),
            orders: Vec::new(),
            orders_table_state: TableState::default(),
            selected_order_index: 0,
            input_mode: InputMode::Normal,
            order_input: String::new(),
            ws_connected: false,
            error_message: None,
        }
    }
    
    fn current_data(&mut self) -> &mut ExchangeData {
        match self.active_tab {
            ExchangeTab::Binance => &mut self.binance_data,
            ExchangeTab::Merval => &mut self.merval_data,
        }
    }
    
    pub fn handle_websocket_message(&mut self, msg: WebSocketMessage) {
        match msg {
            WebSocketMessage::PriceUpdate(exchange, price, volume) => {
                match exchange.as_str() {
                    "binance" => self.binance_data.update_price(price, volume),
                    "merval" => self.merval_data.update_price(price, volume),
                    _ => {}
                }
            }
            WebSocketMessage::OrderUpdate(order) => {
                self.orders.push(order);
            }
            WebSocketMessage::Connected(exchange) => {
                self.ws_connected = true;
                self.error_message = None;
                match exchange.as_str() {
                    "binance" => self.binance_data.connected = true,
                    "merval" => self.merval_data.connected = true,
                    _ => {}
                }
            }
            WebSocketMessage::Disconnected(exchange) => {
                match exchange.as_str() {
                    "binance" => self.binance_data.connected = false,
                    "merval" => self.merval_data.connected = false,
                    _ => {}
                }
                // Only show disconnected if both are down
                if !self.binance_data.connected && !self.merval_data.connected {
                    self.ws_connected = false;
                }
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
                crossterm::event::KeyCode::Char('1') => {
                    self.active_tab = ExchangeTab::Binance;
                }
                crossterm::event::KeyCode::Char('2') => {
                    self.active_tab = ExchangeTab::Merval;
                }
                crossterm::event::KeyCode::Right | crossterm::event::KeyCode::Tab => {
                    self.active_tab = match self.active_tab {
                        ExchangeTab::Binance => ExchangeTab::Merval,
                        ExchangeTab::Merval => ExchangeTab::Binance,
                    };
                }
                crossterm::event::KeyCode::Left => {
                    self.active_tab = match self.active_tab {
                        ExchangeTab::Binance => ExchangeTab::Merval,
                        ExchangeTab::Merval => ExchangeTab::Binance,
                    };
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
                            let order = Order::new(
                                side, 
                                price, 
                                qty, 
                                format!("{:?}", self.active_tab)
                            );
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
                Constraint::Length(3),   // Tabs
                Constraint::Length(3),   // Status bar
                Constraint::Length(10),  // Price chart & stats
                Constraint::Min(10),     // Order book
                Constraint::Length(3),   // Input line
            ])
            .split(frame.size());
        
        self.render_tabs(chunks[0], frame);
        self.render_status_bar(chunks[1], frame);
        
        // Render exchange-specific content
        match self.active_tab {
            ExchangeTab::Binance => self.render_binance_view(chunks[2], frame),
            ExchangeTab::Merval => self.render_merval_view(chunks[2], frame),
        }
        
        self.render_order_book(chunks[3], frame);
        self.render_input_area(chunks[4], frame);
    }
    
    fn render_tabs(&self, area: Rect, frame: &mut Frame) {
        let titles = vec![
            Line::from(Span::styled(
                " Binance ",
                if self.active_tab == ExchangeTab::Binance {
                    Style::default().fg(Color::Black).bg(Color::Yellow)
                } else {
                    Style::default().fg(Color::Yellow)
                }
            )),
            Line::from(Span::styled(
                " MERVAL ",
                if self.active_tab == ExchangeTab::Merval {
                    Style::default().fg(Color::Black).bg(Color::LightBlue)
                } else {
                    Style::default().fg(Color::LightBlue)
                }
            )),
        ];
        
        let tabs = Tabs::new(titles)
            .block(Block::default().borders(Borders::ALL).title("Exchanges"))
            .highlight_style(Style::default().add_modifier(Modifier::BOLD))
            .select(if self.active_tab == ExchangeTab::Binance { 0 } else { 1 });
        
        frame.render_widget(tabs, area);
    }
    
    fn render_status_bar(&self, area: Rect, frame: &mut Frame) {
        let binance_status = if self.binance_data.connected {
            Span::styled("●", Style::default().fg(Color::Green))
        } else {
            Span::styled("○", Style::default().fg(Color::Red))
        };
        
        let merval_status = if self.merval_data.connected {
            Span::styled("●", Style::default().fg(Color::Green))
        } else {
            Span::styled("○", Style::default().fg(Color::Red))
        };
        
        let current_data = match self.active_tab {
            ExchangeTab::Binance => &self.binance_data,
            ExchangeTab::Merval => &self.merval_data,
        };
        
        let price = Span::styled(
            format!("{}: ${:.2} {} | 24h Vol: {:.2} {}", 
                current_data.symbol,
                current_data.current_price,
                current_data.quote_currency,
                current_data.volume_24h,
                current_data.volume_currency
            ),
            Style::default().fg(Color::Cyan).add_modifier(Modifier::BOLD)
        );
        
        let line = Line::from(vec![
            Span::raw("Binance "),
            binance_status,
            Span::raw(" | MERVAL "),
            merval_status,
            Span::raw(" | "),
            price,
        ]);
        
        let paragraph = Paragraph::new(line).block(Block::default().borders(Borders::TOP));
        frame.render_widget(paragraph, area);
    }
    
    fn render_binance_view(&self, area: Rect, frame: &mut Frame) {
        let chunks = Layout::default()
            .direction(Direction::Horizontal)
            .constraints([
                Constraint::Percentage(50),
                Constraint::Percentage(50),
            ])
            .split(area);
        
        // Price chart
        let sparkline = Sparkline::default()
            .block(Block::default().borders(Borders::ALL).title("BTC/USDT Price"))
            .data(&self.binance_data.ticks)
            .style(Style::default().fg(Color::Green));
        frame.render_widget(sparkline, chunks[0]);
        
        // Additional Binance stats
        let stats = vec![
            Line::from(format!("24h High: ${:.2}", self.binance_data.high_24h)),
            Line::from(format!("24h Low: ${:.2}", self.binance_data.low_24h)),
            Line::from(format!("24h Volume: {:.2} {}", self.binance_data.volume_24h, self.binance_data.volume_currency)),
            Line::from(format!("Order Book Depth: {}", self.binance_data.order_book_depth)),
        ];
        
        let stats_paragraph = Paragraph::new(Text::from(stats))
            .block(Block::default().borders(Borders::ALL).title("Market Stats"));
        frame.render_widget(stats_paragraph, chunks[1]);
    }
    
    fn render_merval_view(&self, area: Rect, frame: &mut Frame) {
        let chunks = Layout::default()
            .direction(Direction::Horizontal)
            .constraints([
                Constraint::Percentage(50),
                Constraint::Percentage(50),
            ])
            .split(area);
        
        // Price chart (MERVAL uses different scaling)
        let sparkline = Sparkline::default()
            .block(Block::default().borders(Borders::ALL).title("MERVAL Index"))
            .data(&self.merval_data.ticks)
            .style(Style::default().fg(Color::LightBlue));
        frame.render_widget(sparkline, chunks[0]);
        
        // MERVAL-specific stats (Argentinian market)
        let stats = vec![
            Line::from(format!("ARS Price: ${:.0}", self.merval_data.current_price)),
            Line::from(format!("Daily Change: {:.2}%", self.merval_data.daily_change)),
            Line::from(format!("Volume (ARS): {:.0}", self.merval_data.volume_24h)),
            Line::from(format!("Market Status: {}", self.merval_data.market_status)),
            Line::from(format!("Last Update: {}", self.merval_data.last_update)),
        ];
        
        let stats_paragraph = Paragraph::new(Text::from(stats))
            .block(Block::default().borders(Borders::ALL).title("MERVAL Info"));
        frame.render_widget(stats_paragraph, chunks[1]);
    }
    
    fn render_order_book(&mut self, area: Rect, frame: &mut Frame) {
        let header_style = Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD);
        let header = vec!["ID", "Exchange", "Side", "Price", "Qty", "Status"];
        
        let rows: Vec<ratatui::widgets::Row> = self.orders.iter().map(|order| {
            // Style based on side (BUY/SELL)
            let side_style = if order.side == "BUY" {
                Style::default().fg(Color::Green)
            } else {
                Style::default().fg(Color::Red)
            };
            
            // Exchange-specific color (for potential future use)
            let _exchange_style = if order.exchange == "Binance" {
                Style::default().fg(Color::Yellow)
            } else {
                Style::default().fg(Color::LightBlue)
            };
            
            ratatui::widgets::Row::new(vec![
                order.id.to_string(),
                order.exchange.clone(),
                order.side.clone(),
                format!("${:.2}", order.price),
                order.quantity.to_string(),
                order.status.clone(),
            ]).style(side_style)  // Now side_style is defined
        }).collect();
        
        let widths = vec![
            Constraint::Length(5),
            Constraint::Length(10),
            Constraint::Length(6),
            Constraint::Length(12),
            Constraint::Length(8),
            Constraint::Length(10),
        ];
        
        let table = Table::new(rows, widths)
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
        
        let hint = match self.active_tab {
            ExchangeTab::Binance => "Format: BUY/SELL <quantity> <price> (e.g., BUY 0.01 45000)",
            ExchangeTab::Merval => "Format: BUY/SELL <quantity> <price> (e.g., BUY 100 125000)",
        };
        
        let input_text = if self.input_mode == InputMode::EditingOrder {
            format!("> {}", self.order_input)
        } else {
            format!("Press 'o' to enter order | Tab/←/→ to switch exchanges | {}", hint)
        };
        
        let input_paragraph = Paragraph::new(input_text)
            .block(Block::default().borders(Borders::ALL).title("Order Entry"))
            .style(input_style);
        
        frame.render_widget(input_paragraph, area);
    }
}