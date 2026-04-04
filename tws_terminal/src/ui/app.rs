use std::collections::{HashMap, VecDeque};

use ratatui::{
    layout::{Constraint, Direction, Layout, Rect},
    style::{Color, Modifier, Style},
    text::{Line, Span, Text},
    widgets::{Block, Borders, List, ListItem, Paragraph, Sparkline, Table, TableState, Tabs},
    Frame,
};

use crate::data::{BinanceSymbolData, ExchangeData, Order, RecentTrade};
use crate::network::WebSocketMessage;

// ─── Tab / mode enums ─────────────────────────────────────────────────────

#[derive(PartialEq, Clone, Copy, Debug)]
pub enum ExchangeTab {
    Binance,
    Merval,
}

#[derive(PartialEq, Clone, Copy, Debug)]
pub enum SubTab {
    RealTime,
    Historical,
}

impl SubTab {
    fn toggle(self) -> Self {
        match self {
            SubTab::RealTime => SubTab::Historical,
            SubTab::Historical => SubTab::RealTime,
        }
    }
}

#[derive(PartialEq)]
pub enum InputMode {
    Normal,
    EditingOrder,
}

// ─── Helpers ──────────────────────────────────────────────────────────────

/// Format large numbers in abbreviated form: 1.2M, 345.6K, etc.
fn fmt_volume(v: f64) -> String {
    if v >= 1_000_000.0 {
        format!("{:.1}M", v / 1_000_000.0)
    } else if v >= 1_000.0 {
        format!("{:.1}K", v / 1_000.0)
    } else if v >= 1.0 {
        format!("{:.1}", v)
    } else {
        format!("{:.4}", v)
    }
}

// ─── App state ────────────────────────────────────────────────────────────

pub struct TradingApp {
    pub active_tab: ExchangeTab,
    pub binance_subtab: SubTab,
    pub merval_subtab: SubTab,

    // ── Binance live data ──
    pub symbol_map: HashMap<String, BinanceSymbolData>,
    /// Symbol keys sorted by usd_volume descending
    pub symbols_by_volume: Vec<String>,
    /// Track selection by NAME — survives re-sorts
    pub selected_symbol: Option<String>,
    /// Ring buffer of last 200 trades across all symbols
    pub recent_trades: VecDeque<RecentTrade>,

    // ── MERVAL ──
    pub merval_data: ExchangeData,

    // ── Order management ──
    pub orders: Vec<Order>,
    pub orders_table_state: TableState,
    pub selected_order_index: usize,

    // ── UI state ──
    pub input_mode: InputMode,
    pub order_input: String,
    pub binance_connected: bool,
    pub error_message: Option<String>,
}

impl TradingApp {
    pub fn new() -> Self {
        Self {
            active_tab: ExchangeTab::Binance,
            binance_subtab: SubTab::RealTime,
            merval_subtab: SubTab::RealTime,
            symbol_map: HashMap::new(),
            symbols_by_volume: Vec::new(),
            selected_symbol: None,
            recent_trades: VecDeque::new(),
            merval_data: ExchangeData::new("MERVAL", "ARS", 0),
            orders: Vec::new(),
            orders_table_state: TableState::default(),
            selected_order_index: 0,
            input_mode: InputMode::Normal,
            order_input: String::new(),
            binance_connected: false,
            error_message: None,
        }
    }

    /// Returns the index of `selected_symbol` in the current sorted list.
    /// Falls back to 0 if not found or None.
    fn selected_idx(&self) -> usize {
        self.selected_symbol
            .as_ref()
            .and_then(|s| self.symbols_by_volume.iter().position(|x| x == s))
            .unwrap_or(0)
    }

    /// Returns a reference to the currently-selected symbol's name (if any).
    fn selected_sym(&self) -> Option<&String> {
        // If we have a locked selection, use it; otherwise fall back to first
        if let Some(ref s) = self.selected_symbol {
            if self.symbol_map.contains_key(s) {
                return Some(s);
            }
        }
        self.symbols_by_volume.first()
    }

    // ─── Message routing ────────────────────────────────────────────────

    pub fn handle_websocket_message(&mut self, msg: WebSocketMessage) {
        match msg {
            WebSocketMessage::TickUpdate(tick) => {
                let data = self
                    .symbol_map
                    .entry(tick.symbol.clone())
                    .or_insert_with(|| BinanceSymbolData::new(&tick.symbol));
                data.update(tick.open, tick.high, tick.low, tick.close, tick.volume);

                // Re-sort by USD-equivalent volume (close × volume)
                let mut pairs: Vec<(String, f64)> = self
                    .symbol_map
                    .iter()
                    .map(|(k, v)| (k.clone(), v.volume))
                    .collect();
                pairs.sort_by(|a, b| {
                    b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal)
                });
                self.symbols_by_volume = pairs.into_iter().map(|(s, _)| s).collect();

                // Auto-select the first symbol if nothing is selected yet
                if self.selected_symbol.is_none() && !self.symbols_by_volume.is_empty() {
                    self.selected_symbol = Some(self.symbols_by_volume[0].clone());
                }
            }

            WebSocketMessage::TradeUpdate(trade) => {
                let rt = RecentTrade {
                    symbol: trade.symbol.clone(),
                    price: trade.price,
                    quantity: trade.quantity,
                    is_buyer_maker: trade.is_buyer_maker,
                    time: trade.time.clone(),
                };
                self.recent_trades.push_front(rt);
                if self.recent_trades.len() > 200 {
                    self.recent_trades.pop_back();
                }
            }

            WebSocketMessage::Connected(exchange) => {
                if exchange == "binance" {
                    self.binance_connected = true;
                    self.error_message = None;
                }
            }
            WebSocketMessage::Disconnected(exchange) => {
                if exchange == "binance" {
                    self.binance_connected = false;
                }
            }
            WebSocketMessage::Error(e) => {
                self.error_message = Some(e);
            }
            WebSocketMessage::PriceUpdate(exchange, price, volume) => {
                if exchange == "merval" {
                    self.merval_data.update_price(price, volume);
                }
            }
            WebSocketMessage::OrderUpdate(order) => {
                self.orders.push(order);
            }
        }
    }

    // ─── Keyboard input ─────────────────────────────────────────────────

    pub fn handle_input(&mut self, event: crossterm::event::KeyEvent) -> bool {
        match self.input_mode {
            InputMode::Normal => match event.code {
                crossterm::event::KeyCode::Char('q') => return false,

                crossterm::event::KeyCode::Char('o') => {
                    self.input_mode = InputMode::EditingOrder;
                    self.order_input.clear();
                }

                // Toggle sub-tab (Real-Time / Historical)
                crossterm::event::KeyCode::Char('s') => {
                    match self.active_tab {
                        ExchangeTab::Binance => self.binance_subtab = self.binance_subtab.toggle(),
                        ExchangeTab::Merval => self.merval_subtab = self.merval_subtab.toggle(),
                    }
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

                // ↑↓ navigate the symbol list (by name, not index)
                crossterm::event::KeyCode::Up => match self.active_tab {
                    ExchangeTab::Binance => {
                        let idx = self.selected_idx();
                        if idx > 0 {
                            self.selected_symbol =
                                Some(self.symbols_by_volume[idx - 1].clone());
                        }
                    }
                    ExchangeTab::Merval => {
                        if self.selected_order_index > 0 {
                            self.selected_order_index -= 1;
                            self.orders_table_state
                                .select(Some(self.selected_order_index));
                        }
                    }
                },
                crossterm::event::KeyCode::Down => match self.active_tab {
                    ExchangeTab::Binance => {
                        let idx = self.selected_idx();
                        if idx < self.symbols_by_volume.len().saturating_sub(1) {
                            self.selected_symbol =
                                Some(self.symbols_by_volume[idx + 1].clone());
                        }
                    }
                    ExchangeTab::Merval => {
                        if self.selected_order_index < self.orders.len().saturating_sub(1) {
                            self.selected_order_index += 1;
                            self.orders_table_state
                                .select(Some(self.selected_order_index));
                        }
                    }
                },

                _ => {}
            },

            InputMode::EditingOrder => match event.code {
                crossterm::event::KeyCode::Enter => {
                    let parts: Vec<&str> = self.order_input.split_whitespace().collect();
                    if parts.len() == 3 {
                        let side = parts[0].to_uppercase();
                        if let (Ok(qty), Ok(price)) =
                            (parts[1].parse::<u32>(), parts[2].parse::<f64>())
                        {
                            let order = Order::new(
                                side,
                                price,
                                qty,
                                format!("{:?}", self.active_tab),
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

    // ─── Top-level render ───────────────────────────────────────────────

    pub fn render(&mut self, frame: &mut Frame) {
        let chunks = Layout::default()
            .direction(Direction::Vertical)
            .constraints([
                Constraint::Length(3),  // Tabs
                Constraint::Length(1),  // Sub-tabs
                Constraint::Length(3),  // Status bar
                Constraint::Min(12),   // Main content
                Constraint::Length(8), // Trades / Orders
                Constraint::Length(3),  // Input line
            ])
            .split(frame.size());

        self.render_tabs(chunks[0], frame);
        self.render_subtabs(chunks[1], frame);
        self.render_status_bar(chunks[2], frame);

        let active_subtab = match self.active_tab {
            ExchangeTab::Binance => self.binance_subtab,
            ExchangeTab::Merval => self.merval_subtab,
        };

        match (self.active_tab, active_subtab) {
            (ExchangeTab::Binance, SubTab::RealTime) => {
                self.render_binance_view(chunks[3], frame);
                self.render_recent_trades(chunks[4], frame);
            }
            (ExchangeTab::Binance, SubTab::Historical) => {
                self.render_historical_placeholder("Binance", chunks[3], frame);
                self.render_historical_placeholder_bottom("Binance", chunks[4], frame);
            }
            (ExchangeTab::Merval, SubTab::RealTime) => {
                self.render_merval_view(chunks[3], frame);
                self.render_orders_table(chunks[4], frame);
            }
            (ExchangeTab::Merval, SubTab::Historical) => {
                self.render_historical_placeholder("MERVAL", chunks[3], frame);
                self.render_historical_placeholder_bottom("MERVAL", chunks[4], frame);
            }
        }

        self.render_input_area(chunks[5], frame);
    }

    // ─── Sub-tabs ────────────────────────────────────────────────────────

    fn render_subtabs(&self, area: Rect, frame: &mut Frame) {
        let active_subtab = match self.active_tab {
            ExchangeTab::Binance => self.binance_subtab,
            ExchangeTab::Merval => self.merval_subtab,
        };
        let accent = match self.active_tab {
            ExchangeTab::Binance => Color::Yellow,
            ExchangeTab::Merval => Color::LightBlue,
        };

        let rt_style = if active_subtab == SubTab::RealTime {
            Style::default().fg(Color::Black).bg(accent).add_modifier(Modifier::BOLD)
        } else {
            Style::default().fg(Color::DarkGray)
        };
        let hist_style = if active_subtab == SubTab::Historical {
            Style::default().fg(Color::Black).bg(accent).add_modifier(Modifier::BOLD)
        } else {
            Style::default().fg(Color::DarkGray)
        };

        let line = Line::from(vec![
            Span::raw(" "),
            Span::styled(" Real-Time ", rt_style),
            Span::raw(" "),
            Span::styled(" Historical ", hist_style),
            Span::styled("  [s] toggle", Style::default().fg(Color::DarkGray)),
        ]);

        frame.render_widget(Paragraph::new(line), area);
    }

    // ─── Historical placeholders ─────────────────────────────────────────

    fn render_historical_placeholder(&self, exchange: &str, area: Rect, frame: &mut Frame) {
        let lines = vec![
            Line::from(""),
            Line::from(Span::styled(
                format!("  {} Historical Data", exchange),
                Style::default().fg(Color::Cyan).add_modifier(Modifier::BOLD),
            )),
            Line::from(""),
            Line::from(Span::styled(
                "  Coming soon — connect a PostgreSQL or CSV data source",
                Style::default().fg(Color::DarkGray),
            )),
            Line::from(Span::styled(
                "  to view historical OHLCV candles and backtest results.",
                Style::default().fg(Color::DarkGray),
            )),
        ];

        let paragraph = Paragraph::new(Text::from(lines))
            .block(Block::default().borders(Borders::ALL).title(format!(" {} — Historical ", exchange)));
        frame.render_widget(paragraph, area);
    }

    fn render_historical_placeholder_bottom(&self, exchange: &str, area: Rect, frame: &mut Frame) {
        let lines = vec![
            Line::from(Span::styled(
                format!("  No historical trades loaded for {}", exchange),
                Style::default().fg(Color::DarkGray),
            )),
        ];
        let paragraph = Paragraph::new(Text::from(lines))
            .block(Block::default().borders(Borders::ALL).title(" Historical Trades "));
        frame.render_widget(paragraph, area);
    }

    // ─── Tabs ───────────────────────────────────────────────────────────

    fn render_tabs(&self, area: Rect, frame: &mut Frame) {
        let titles = vec![
            Line::from(Span::styled(
                " Binance ",
                if self.active_tab == ExchangeTab::Binance {
                    Style::default().fg(Color::Black).bg(Color::Yellow)
                } else {
                    Style::default().fg(Color::Yellow)
                },
            )),
            Line::from(Span::styled(
                " MERVAL ",
                if self.active_tab == ExchangeTab::Merval {
                    Style::default().fg(Color::Black).bg(Color::LightBlue)
                } else {
                    Style::default().fg(Color::LightBlue)
                },
            )),
        ];

        let tabs = Tabs::new(titles)
            .block(Block::default().borders(Borders::ALL).title(" TWS Terminal "))
            .highlight_style(Style::default().add_modifier(Modifier::BOLD))
            .select(if self.active_tab == ExchangeTab::Binance { 0 } else { 1 });

        frame.render_widget(tabs, area);
    }

    // ─── Status bar ─────────────────────────────────────────────────────

    fn render_status_bar(&self, area: Rect, frame: &mut Frame) {
        let dot = if self.binance_connected {
            Span::styled("● LIVE", Style::default().fg(Color::Green).add_modifier(Modifier::BOLD))
        } else {
            Span::styled("○ CONNECTING", Style::default().fg(Color::Red))
        };

        let info = if let Some(sym) = self.selected_sym() {
            if let Some(d) = self.symbol_map.get(sym) {
                let chg_color = if d.daily_change_pct >= 0.0 { Color::Green } else { Color::Red };
                Line::from(vec![
                    Span::raw("Binance "),
                    dot,
                    Span::styled(
                        format!("  {} | Close: {:.4}  O:{:.4}  H:{:.4}  L:{:.4}  Vol:{}  Chg: ",
                            sym, d.close, d.open, d.high, d.low, fmt_volume(d.volume)),
                        Style::default().fg(Color::Cyan),
                    ),
                    Span::styled(
                        format!("{:+.4}%", d.daily_change_pct),
                        Style::default().fg(chg_color).add_modifier(Modifier::BOLD),
                    ),
                ])
            } else {
                Line::from(vec![Span::raw("Binance "), dot, Span::raw("  Waiting for data...")])
            }
        } else {
            Line::from(vec![
                Span::raw("Binance "),
                dot,
                if let Some(e) = &self.error_message {
                    Span::styled(format!("  {e}"), Style::default().fg(Color::DarkGray))
                } else {
                    Span::raw("  Waiting for Redis data...")
                },
            ])
        };

        let paragraph = Paragraph::new(info).block(Block::default().borders(Borders::TOP));
        frame.render_widget(paragraph, area);
    }

    // ─── Binance view ───────────────────────────────────────────────────

    fn render_binance_view(&self, area: Rect, frame: &mut Frame) {
        let h = Layout::default()
            .direction(Direction::Horizontal)
            .constraints([Constraint::Length(42), Constraint::Min(20)])
            .split(area);

        self.render_symbol_list(h[0], frame);

        let v = Layout::default()
            .direction(Direction::Vertical)
            .constraints([Constraint::Percentage(60), Constraint::Percentage(40)])
            .split(h[1]);

        self.render_price_chart(v[0], frame);
        self.render_symbol_stats(v[1], frame);
    }

    fn render_symbol_list(&self, area: Rect, frame: &mut Frame) {
        let sel_idx = self.selected_idx();

        let items: Vec<ListItem> = self
            .symbols_by_volume
            .iter()
            .enumerate()
            .map(|(i, sym)| {
                let (close, change, vol) = self
                    .symbol_map
                    .get(sym)
                    .map(|d| (d.close, d.daily_change_pct, d.volume))
                    .unwrap_or((0.0, 0.0, 0.0));

                let selected = i == sel_idx;
                let prefix = if selected { "▶ " } else { "  " };
                let chg_color = if change >= 0.0 { Color::Green } else { Color::Red };

                let base_style = if selected {
                    Style::default()
                        .fg(Color::Black)
                        .bg(Color::Yellow)
                        .add_modifier(Modifier::BOLD)
                } else {
                    Style::default().fg(Color::White)
                };

                let line = Line::from(vec![
                    Span::styled(format!("{}{:<10}", prefix, sym), base_style),
                    Span::styled(
                        format!(" {:>12.4}", close),
                        if selected { base_style } else { Style::default().fg(Color::Cyan) },
                    ),
                    Span::styled(
                        format!(" {:>+7.2}%", change),
                        if selected { base_style } else { Style::default().fg(chg_color) },
                    ),
                    Span::styled(
                        format!(" {:>8}", fmt_volume(vol)),
                        if selected { base_style } else { Style::default().fg(Color::DarkGray) },
                    ),
                ]);

                ListItem::new(line)
            })
            .collect();

        let list = List::new(items).block(
            Block::default()
                .borders(Borders::ALL)
                .title(" Symbols (USD Vol) [↑↓] "),
        );
        frame.render_widget(list, area);
    }

    fn render_price_chart(&self, area: Rect, frame: &mut Frame) {
        let (title, history, color) =
            if let Some(sym) = self.selected_sym() {
                if let Some(d) = self.symbol_map.get(sym) {
                    if d.price_history.is_empty() {
                        (format!(" {} Waiting... ", sym), vec![], Color::DarkGray)
                    } else {
                        let color = if d.daily_change_pct >= 0.0 { Color::Green } else { Color::Red };
                        (format!(" {} Price ", sym), d.price_history.clone(), color)
                    }
                } else {
                    (" Waiting... ".to_string(), vec![], Color::DarkGray)
                }
            } else {
                (" No data ".to_string(), vec![], Color::DarkGray)
            };

        let sparkline = Sparkline::default()
            .block(Block::default().borders(Borders::ALL).title(title))
            .data(&history)
            .style(Style::default().fg(color));

        frame.render_widget(sparkline, area);
    }

    fn render_symbol_stats(&self, area: Rect, frame: &mut Frame) {
        let content: Vec<Line> = if let Some(sym) = self.selected_sym() {
            if let Some(d) = self.symbol_map.get(sym) {
                let chg_color = if d.daily_change_pct >= 0.0 { Color::Green } else { Color::Red };
                vec![
                    Line::from(vec![
                        Span::styled("Open:  ", Style::default().fg(Color::DarkGray)),
                        Span::styled(format!("{:.4}", d.open), Style::default().fg(Color::White)),
                        Span::raw("   "),
                        Span::styled("Close: ", Style::default().fg(Color::DarkGray)),
                        Span::styled(
                            format!("{:.4}", d.close),
                            Style::default().fg(Color::Cyan).add_modifier(Modifier::BOLD),
                        ),
                    ]),
                    Line::from(vec![
                        Span::styled("High:  ", Style::default().fg(Color::DarkGray)),
                        Span::styled(format!("{:.4}", d.high), Style::default().fg(Color::Green)),
                        Span::raw("   "),
                        Span::styled("Low:   ", Style::default().fg(Color::DarkGray)),
                        Span::styled(format!("{:.4}", d.low), Style::default().fg(Color::Red)),
                    ]),
                    Line::from(vec![
                        Span::styled("Vol:   ", Style::default().fg(Color::DarkGray)),
                        Span::styled(
                            format!("{}", fmt_volume(d.volume)),
                            Style::default().fg(Color::Yellow),
                        ),
                        Span::raw("   "),
                        Span::styled("Change:", Style::default().fg(Color::DarkGray)),
                        Span::styled(
                            format!(" {:+.4}%", d.daily_change_pct),
                            Style::default().fg(chg_color).add_modifier(Modifier::BOLD),
                        ),
                    ]),
                    Line::from(vec![
                        Span::styled("Updated:", Style::default().fg(Color::DarkGray)),
                        Span::styled(
                            format!(" {}", d.last_update),
                            Style::default().fg(Color::DarkGray),
                        ),
                    ]),
                ]
            } else {
                vec![Line::from("No data yet...")]
            }
        } else {
            vec![Line::from(Span::styled(
                "Connecting to Redis...",
                Style::default().fg(Color::DarkGray),
            ))]
        };

        let paragraph = Paragraph::new(Text::from(content))
            .block(Block::default().borders(Borders::ALL).title(" OHLCV "));
        frame.render_widget(paragraph, area);
    }

    // ─── Recent trades ──────────────────────────────────────────────────

    fn render_recent_trades(&self, area: Rect, frame: &mut Frame) {
        let selected_sym = self.selected_sym().cloned();
        let max_rows = (area.height as usize).saturating_sub(2);

        let items: Vec<ListItem> = self
            .recent_trades
            .iter()
            .filter(|t| {
                selected_sym
                    .as_ref()
                    .map(|s| &t.symbol == s)
                    .unwrap_or(true)
            })
            .take(max_rows)
            .map(|t| {
                let (side, color) = if t.is_buyer_maker {
                    ("SELL", Color::Red)
                } else {
                    ("BUY ", Color::Green)
                };
                ListItem::new(Line::from(vec![
                    Span::styled(
                        format!("{side} "),
                        Style::default().fg(color).add_modifier(Modifier::BOLD),
                    ),
                    Span::styled(
                        format!("{:>14.4}  ", t.price),
                        Style::default().fg(Color::White),
                    ),
                    Span::styled(
                        format!("qty {:>12.6}", t.quantity),
                        Style::default().fg(Color::Cyan),
                    ),
                    Span::styled(
                        format!("  {}", t.time),
                        Style::default().fg(Color::DarkGray),
                    ),
                ]))
            })
            .collect();

        let title = selected_sym
            .as_deref()
            .map(|s| format!(" Recent Trades — {s} "))
            .unwrap_or_else(|| " Recent Trades ".to_string());

        let list = List::new(items).block(Block::default().borders(Borders::ALL).title(title));
        frame.render_widget(list, area);
    }

    // ─── MERVAL view ────────────────────────────────────────────────────

    fn render_merval_view(&self, area: Rect, frame: &mut Frame) {
        let chunks = Layout::default()
            .direction(Direction::Horizontal)
            .constraints([Constraint::Percentage(50), Constraint::Percentage(50)])
            .split(area);

        let sparkline = Sparkline::default()
            .block(Block::default().borders(Borders::ALL).title(" MERVAL Index "))
            .data(&self.merval_data.ticks)
            .style(Style::default().fg(Color::LightBlue));
        frame.render_widget(sparkline, chunks[0]);

        let stats = vec![
            Line::from(format!("ARS Price: ${:.0}", self.merval_data.current_price)),
            Line::from(format!("Daily Change: {:.2}%", self.merval_data.daily_change)),
            Line::from(format!("Volume (ARS): {:.0}", self.merval_data.volume_24h)),
            Line::from(format!("Market Status: {}", self.merval_data.market_status)),
            Line::from(format!("Last Update: {}", self.merval_data.last_update)),
        ];

        let paragraph = Paragraph::new(Text::from(stats))
            .block(Block::default().borders(Borders::ALL).title(" MERVAL Info "));
        frame.render_widget(paragraph, chunks[1]);
    }

    // ─── Orders table ───────────────────────────────────────────────────

    fn render_orders_table(&mut self, area: Rect, frame: &mut Frame) {
        let header_style = Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD);
        let header = vec!["ID", "Exchange", "Side", "Price", "Qty", "Status"];

        let rows: Vec<ratatui::widgets::Row> = self
            .orders
            .iter()
            .map(|order| {
                let side_style = if order.side == "BUY" {
                    Style::default().fg(Color::Green)
                } else {
                    Style::default().fg(Color::Red)
                };
                ratatui::widgets::Row::new(vec![
                    order.id.to_string(),
                    order.exchange.clone(),
                    order.side.clone(),
                    format!("${:.2}", order.price),
                    order.quantity.to_string(),
                    order.status.clone(),
                ])
                .style(side_style)
            })
            .collect();

        let widths = vec![
            Constraint::Length(5),
            Constraint::Length(10),
            Constraint::Length(6),
            Constraint::Length(14),
            Constraint::Length(8),
            Constraint::Length(10),
        ];

        let table = Table::new(rows, widths)
            .header(ratatui::widgets::Row::new(header).style(header_style))
            .block(Block::default().borders(Borders::ALL).title(" Active Orders "))
            .highlight_style(Style::default().add_modifier(Modifier::BOLD))
            .highlight_symbol("> ");

        frame.render_stateful_widget(table, area, &mut self.orders_table_state);
    }

    // ─── Input / controls ───────────────────────────────────────────────

    fn render_input_area(&self, area: Rect, frame: &mut Frame) {
        let (text, style) = if self.input_mode == InputMode::EditingOrder {
            (
                format!("> {}", self.order_input),
                Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD),
            )
        } else {
            let hint = match self.active_tab {
                ExchangeTab::Binance => {
                    "[↑↓] Select symbol  [s] Real-Time/Historical  [Tab/→] MERVAL  [q] Quit"
                }
                ExchangeTab::Merval => {
                    "[o] Enter order  [↑↓] Navigate  [s] Real-Time/Historical  [Tab/→] Binance  [q] Quit"
                }
            };
            (hint.to_string(), Style::default().fg(Color::DarkGray))
        };

        let paragraph = Paragraph::new(text)
            .block(Block::default().borders(Borders::ALL).title(" Controls "))
            .style(style);
        frame.render_widget(paragraph, area);
    }
}