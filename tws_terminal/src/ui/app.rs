use std::collections::{HashMap, VecDeque};

use ratatui::{
    layout::{Constraint, Direction, Layout, Rect},
    style::{Color, Modifier, Style},
    text::{Line, Span, Text},
    widgets::{Block, Borders, List, ListItem, Paragraph, Sparkline, Table, TableState, Tabs},
    Frame,
};

use crate::data::{BinanceSymbolData, ExchangeData, Order, RecentTrade};
use crate::db::{HistBinanceTick, HistBinanceTrade, HistFilter, HistOrder, HistTick};
use crate::network::WebSocketMessage;
use tokio::sync::mpsc::UnboundedSender;

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

/// Sub-tabs inside MERVAL Historical view
#[derive(PartialEq, Clone, Copy, Debug)]
pub enum MervalHistTab { Stocks, Options, Bonds, Favorites }

impl MervalHistTab {
    fn label(self) -> &'static str {
        match self {
            MervalHistTab::Stocks    => "Stocks",
            MervalHistTab::Options   => "Options",
            MervalHistTab::Bonds     => "Bonds",
            MervalHistTab::Favorites => "Favorites",
        }
    }
    /// Returns true if the instrument belongs to this category.
    pub fn matches(self, instrument: &str) -> bool {
        let i = instrument.to_uppercase();
        match self {
            // Options: contain GFGC or GFGV (GGAL options series)
            MervalHistTab::Options => i.contains("GFGC") || i.contains("GFGV"),
            // Bonds: AL30, GD30, AE38, etc. — contain "AL" or "GD" or "AE" followed by digits
            MervalHistTab::Bonds => {
                i.contains("AL30") || i.contains("GD30") || i.contains("AE38")
                    || i.contains("AL35") || i.contains("GD35") || i.contains("BOND")
            }
            // Stocks: GGAL, SUPV, PAMP, YPFD, etc. — not options, not bonds
            MervalHistTab::Stocks => {
                !MervalHistTab::Options.matches(instrument)
                    && !MervalHistTab::Bonds.matches(instrument)
            }
            MervalHistTab::Favorites => false, // handled separately
        }
    }
}

#[derive(PartialEq)]
pub enum InputMode {
    Normal,
    EditingOrder,
    FilterEdit,
    AddingFavorite,
}

// ─── Filter UI state ──────────────────────────────────────────────────────

#[derive(PartialEq, Clone, Copy)]
pub enum FilterField { Date, Instrument }

pub struct FilterState {
    pub date_input:       String,
    pub instrument_input: String,
    pub active_field:     FilterField,
    pub filter:           HistFilter,
    /// Filtered candidates shown in dropdown
    pub dropdown:         Vec<String>,
    pub dropdown_idx:     usize,
}

impl FilterState {
    fn new() -> Self {
        Self {
            date_input:       String::new(),
            instrument_input: String::new(),
            active_field:     FilterField::Date,
            filter:           HistFilter::default(),
            dropdown:         Vec::new(),
            dropdown_idx:     0,
        }
    }

    fn commit(&mut self) {
        use chrono::NaiveDate;
        self.filter.date = NaiveDate::parse_from_str(self.date_input.trim(), "%Y-%m-%d").ok();
        let s = self.instrument_input.trim().to_string();
        self.filter.instrument = if s.is_empty() { None } else { Some(s) };
    }

    /// Recompute dropdown from `candidates` based on current active field input.
    pub fn refresh_dropdown(&mut self, instruments: &[String], dates: &[String]) {
        let (query, pool) = match self.active_field {
            FilterField::Instrument => (self.instrument_input.to_lowercase(), instruments),
            FilterField::Date       => (self.date_input.clone(), dates),
        };
        self.dropdown = pool.iter()
            .filter(|s| query.is_empty() || s.to_lowercase().contains(&query))
            .cloned()
            .collect();
        self.dropdown_idx = 0;
    }
}

// ─── DB messages ──────────────────────────────────────────────────────────

pub enum DbMessage {
    Ticks(Vec<HistTick>),
    Orders(Vec<HistOrder>),
    BinanceTicks(Vec<HistBinanceTick>),
    BinanceTrades(Vec<HistBinanceTrade>),
    Instruments(Vec<String>),
    Dates(Vec<String>),
    BinanceSymbols(Vec<String>),
    Error(String),
}

// ─── Historical panel focus ───────────────────────────────────────────────

#[derive(PartialEq, Clone, Copy)]
pub enum HistFocus { Top, Bottom }

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

    // ── Historical data (from PostgreSQL) ──
    pub hist_ticks: Vec<HistTick>,
    pub hist_orders: Vec<HistOrder>,
    pub hist_binance_ticks: Vec<HistBinanceTick>,
    pub hist_binance_trades: Vec<HistBinanceTrade>,
    pub hist_loading: bool,
    pub hist_error: Option<String>,

    // ── Historical table scroll states ──
    pub hist_ticks_state:          TableState,
    pub hist_orders_state:         TableState,
    pub hist_binance_ticks_state:  TableState,
    pub hist_binance_trades_state: TableState,
    pub hist_focus: HistFocus,

    // ── MERVAL historical sub-tab ──
    pub merval_hist_tab: MervalHistTab,

    // ── Favorites ──
    pub favorites: Vec<String>,
    pub fav_selected: usize,
    pub fav_input: String,
    pub fav_ticks_state:  TableState,
    pub fav_orders_state: TableState,
    pub fav_focus: HistFocus,

    // ── DB channel sender (set by main) ──
    pub db_tx: Option<UnboundedSender<DbMessage>>,

    // ── Historical filter ──
    pub filter: FilterState,

    // ── Autocomplete candidates ──
    pub available_instruments:     Vec<String>,
    pub available_dates:           Vec<String>,
    pub available_binance_symbols: Vec<String>,
    /// Dropdown for AddingFavorite mode
    pub fav_dropdown:     Vec<String>,
    pub fav_dropdown_idx: usize,
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
            hist_ticks: Vec::new(),
            hist_orders: Vec::new(),
            hist_binance_ticks: Vec::new(),
            hist_binance_trades: Vec::new(),
            hist_loading: false,
            hist_error: None,
            hist_ticks_state:          TableState::default(),
            hist_orders_state:         TableState::default(),
            hist_binance_ticks_state:  TableState::default(),
            hist_binance_trades_state: TableState::default(),
            hist_focus: HistFocus::Top,
            merval_hist_tab: MervalHistTab::Stocks,
            favorites: Vec::new(),
            fav_selected: 0,
            fav_input: String::new(),
            fav_ticks_state:  TableState::default(),
            fav_orders_state: TableState::default(),
            fav_focus: HistFocus::Top,
            db_tx: None,
            filter: FilterState::new(),
            available_instruments:     Vec::new(),
            available_dates:           Vec::new(),
            available_binance_symbols: Vec::new(),
            fav_dropdown:     Vec::new(),
            fav_dropdown_idx: 0,
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

    fn do_refresh_dropdown(&mut self) {
        let instruments = match self.active_tab {
            ExchangeTab::Binance => self.available_binance_symbols.clone(),
            ExchangeTab::Merval  => self.available_instruments.clone(),
        };
        let dates = self.available_dates.clone();
        self.filter.refresh_dropdown(&instruments, &dates);
    }

    fn hist_scroll(&mut self, delta: i64) {
        if self.active_tab == ExchangeTab::Merval
            && self.merval_subtab == SubTab::Historical
            && self.merval_hist_tab == MervalHistTab::Favorites
        {
            let fav = self.selected_favorite();
            let (state, len) = match self.fav_focus {
                HistFocus::Top => {
                    let l = self.hist_ticks.iter().filter(|r| fav.as_deref().map(|f| r.instrument.to_uppercase().contains(&f.to_uppercase())).unwrap_or(false)).count();
                    (&mut self.fav_ticks_state, l)
                }
                HistFocus::Bottom => {
                    let l = self.hist_orders.iter().filter(|r| fav.as_deref().map(|f| r.instrument.to_uppercase().contains(&f.to_uppercase())).unwrap_or(false)).count();
                    (&mut self.fav_orders_state, l)
                }
            };
            if len == 0 { return; }
            let cur = state.selected().unwrap_or(0) as i64;
            state.select(Some((cur + delta).clamp(0, len as i64 - 1) as usize));
            return;
        }

        let (state, len) = match (self.active_tab, self.hist_focus) {
            (ExchangeTab::Binance, HistFocus::Top)    => (&mut self.hist_binance_ticks_state,  self.hist_binance_ticks.len()),
            (ExchangeTab::Binance, HistFocus::Bottom) => (&mut self.hist_binance_trades_state, self.hist_binance_trades.len()),
            (ExchangeTab::Merval,  HistFocus::Top)    => (&mut self.hist_ticks_state,          self.hist_ticks.len()),
            (ExchangeTab::Merval,  HistFocus::Bottom) => (&mut self.hist_orders_state,         self.hist_orders.len()),
        };
        if len == 0 { return; }
        let cur = state.selected().unwrap_or(0) as i64;
        let next = (cur + delta).clamp(0, len as i64 - 1) as usize;
        state.select(Some(next));
    }

    fn selected_favorite(&self) -> Option<String> {
        self.favorites.get(self.fav_selected).cloned()
    }

    // ─── DB message handler ─────────────────────────────────────────────

    pub fn handle_db_message(&mut self, msg: DbMessage) {
        self.hist_loading = false;
        match msg {
            DbMessage::Ticks(rows)          => self.hist_ticks = rows,
            DbMessage::Orders(rows)         => self.hist_orders = rows,
            DbMessage::BinanceTicks(rows)   => self.hist_binance_ticks = rows,
            DbMessage::BinanceTrades(rows)  => self.hist_binance_trades = rows,
            DbMessage::Instruments(list)    => self.available_instruments = list,
            DbMessage::Dates(list)          => self.available_dates = list,
            DbMessage::BinanceSymbols(list) => self.available_binance_symbols = list,
            DbMessage::Error(e)             => self.hist_error = Some(e),
        }
    }

    /// Spawn a background task that queries all 4 tables and sends results back.
    fn trigger_historical_fetch(&mut self) {
        let Some(tx) = self.db_tx.clone() else { return };
        if self.hist_loading { return; }
        self.hist_loading = true;
        self.hist_error = None;

        let f = self.filter.filter.clone();
        let need_autocomplete = self.available_instruments.is_empty();

        tokio::spawn(async move {
            let client = match crate::db::connect().await {
                Ok(c) => c,
                Err(e) => {
                    let _ = tx.send(DbMessage::Error(format!("DB connect: {e}")));
                    return;
                }
            };

            macro_rules! send {
                ($fut:expr, $variant:ident) => {
                    match $fut.await {
                        Ok(rows) => { let _ = tx.send(DbMessage::$variant(rows)); }
                        Err(e)   => { let _ = tx.send(DbMessage::Error(format!("{e}"))); }
                    }
                };
            }

            send!(crate::db::fetch_ticks(&client, 200, &f),          Ticks);
            send!(crate::db::fetch_orders(&client, 200, &f),         Orders);
            send!(crate::db::fetch_binance_ticks(&client, 200, &f),  BinanceTicks);
            send!(crate::db::fetch_binance_trades(&client, 200, &f), BinanceTrades);

            if need_autocomplete {
                send!(crate::db::fetch_distinct_instruments(&client),    Instruments);
                send!(crate::db::fetch_distinct_dates(&client),          Dates);
                send!(crate::db::fetch_distinct_binance_symbols(&client),BinanceSymbols);
            }
        });
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

                // Open filter editor (only meaningful on Historical subtab)
                crossterm::event::KeyCode::Char('f') => {
                    self.input_mode = InputMode::FilterEdit;
                    self.filter.active_field = FilterField::Date;
                    self.do_refresh_dropdown();
                }

                // Toggle sub-tab (Real-Time / Historical)
                crossterm::event::KeyCode::Char('s') => {
                    match self.active_tab {
                        ExchangeTab::Binance => {
                            self.binance_subtab = self.binance_subtab.toggle();
                            if self.binance_subtab == SubTab::Historical {
                                self.trigger_historical_fetch();
                            }
                        }
                        ExchangeTab::Merval => {
                            self.merval_subtab = self.merval_subtab.toggle();
                            if self.merval_subtab == SubTab::Historical {
                                self.trigger_historical_fetch();
                            }
                        }
                    }
                }

                crossterm::event::KeyCode::Char('1') => {
                    if self.active_tab == ExchangeTab::Merval && self.merval_subtab == SubTab::Historical {
                        self.merval_hist_tab = MervalHistTab::Stocks;
                    } else {
                        self.active_tab = ExchangeTab::Binance;
                    }
                }
                crossterm::event::KeyCode::Char('2') => {
                    if self.active_tab == ExchangeTab::Merval && self.merval_subtab == SubTab::Historical {
                        self.merval_hist_tab = MervalHistTab::Options;
                    } else {
                        self.active_tab = ExchangeTab::Merval;
                    }
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

                // ↑↓ navigate
                crossterm::event::KeyCode::Up => {
                    let subtab = match self.active_tab {
                        ExchangeTab::Binance => self.binance_subtab,
                        ExchangeTab::Merval  => self.merval_subtab,
                    };
                    if subtab == SubTab::Historical {
                        self.hist_scroll(-1);
                    } else {
                        match self.active_tab {
                            ExchangeTab::Binance => {
                                let idx = self.selected_idx();
                                if idx > 0 { self.selected_symbol = Some(self.symbols_by_volume[idx - 1].clone()); }
                            }
                            ExchangeTab::Merval => {
                                if self.selected_order_index > 0 {
                                    self.selected_order_index -= 1;
                                    self.orders_table_state.select(Some(self.selected_order_index));
                                }
                            }
                        }
                    }
                }
                crossterm::event::KeyCode::Down => {
                    let subtab = match self.active_tab {
                        ExchangeTab::Binance => self.binance_subtab,
                        ExchangeTab::Merval  => self.merval_subtab,
                    };
                    if subtab == SubTab::Historical {
                        self.hist_scroll(1);
                    } else {
                        match self.active_tab {
                            ExchangeTab::Binance => {
                                let idx = self.selected_idx();
                                if idx < self.symbols_by_volume.len().saturating_sub(1) {
                                    self.selected_symbol = Some(self.symbols_by_volume[idx + 1].clone());
                                }
                            }
                            ExchangeTab::Merval => {
                                if self.selected_order_index < self.orders.len().saturating_sub(1) {
                                    self.selected_order_index += 1;
                                    self.orders_table_state.select(Some(self.selected_order_index));
                                }
                            }
                        }
                    }
                }
                // Switch focus between top/bottom historical panel
                crossterm::event::KeyCode::Char('p') => {
                    let subtab = match self.active_tab {
                        ExchangeTab::Binance => self.binance_subtab,
                        ExchangeTab::Merval  => self.merval_subtab,
                    };
                    if subtab == SubTab::Historical {
                        if self.active_tab == ExchangeTab::Merval && self.merval_hist_tab == MervalHistTab::Favorites {
                            self.fav_focus = match self.fav_focus {
                                HistFocus::Top    => HistFocus::Bottom,
                                HistFocus::Bottom => HistFocus::Top,
                            };
                        } else {
                            self.hist_focus = match self.hist_focus {
                                HistFocus::Top    => HistFocus::Bottom,
                                HistFocus::Bottom => HistFocus::Top,
                            };
                        }
                    }
                }

                // MERVAL historical category tabs: [3] [4] (1 and 2 handled above)
                crossterm::event::KeyCode::Char('3') => {
                    if self.active_tab == ExchangeTab::Merval && self.merval_subtab == SubTab::Historical {
                        self.merval_hist_tab = MervalHistTab::Bonds;
                    }
                }
                crossterm::event::KeyCode::Char('4') => {
                    if self.active_tab == ExchangeTab::Merval && self.merval_subtab == SubTab::Historical {
                        self.merval_hist_tab = MervalHistTab::Favorites;
                    }
                }

                // Favorites: [a] add, [d] delete, [←→] navigate list
                crossterm::event::KeyCode::Char('a') => {
                    if self.active_tab == ExchangeTab::Merval
                        && self.merval_subtab == SubTab::Historical
                        && self.merval_hist_tab == MervalHistTab::Favorites
                    {
                        self.input_mode = InputMode::AddingFavorite;
                        self.fav_input.clear();
                        self.fav_dropdown = self.available_instruments.clone();
                        self.fav_dropdown_idx = 0;
                    }
                }
                crossterm::event::KeyCode::Char('d') => {
                    if self.active_tab == ExchangeTab::Merval
                        && self.merval_subtab == SubTab::Historical
                        && self.merval_hist_tab == MervalHistTab::Favorites
                        && !self.favorites.is_empty()
                    {
                        self.favorites.remove(self.fav_selected);
                        if self.fav_selected > 0 { self.fav_selected -= 1; }
                    }
                }
                crossterm::event::KeyCode::Right | crossterm::event::KeyCode::Tab => {
                    if self.active_tab == ExchangeTab::Merval
                        && self.merval_subtab == SubTab::Historical
                        && self.merval_hist_tab == MervalHistTab::Favorites
                        && self.fav_selected + 1 < self.favorites.len()
                    {
                        self.fav_selected += 1;
                        self.fav_ticks_state  = TableState::default();
                        self.fav_orders_state = TableState::default();
                    } else {
                        self.active_tab = match self.active_tab {
                            ExchangeTab::Binance => ExchangeTab::Merval,
                            ExchangeTab::Merval  => ExchangeTab::Binance,
                        };
                    }
                }
                crossterm::event::KeyCode::Left => {
                    if self.active_tab == ExchangeTab::Merval
                        && self.merval_subtab == SubTab::Historical
                        && self.merval_hist_tab == MervalHistTab::Favorites
                        && self.fav_selected > 0
                    {
                        self.fav_selected -= 1;
                        self.fav_ticks_state  = TableState::default();
                        self.fav_orders_state = TableState::default();
                    } else {
                        self.active_tab = match self.active_tab {
                            ExchangeTab::Binance => ExchangeTab::Merval,
                            ExchangeTab::Merval  => ExchangeTab::Binance,
                        };
                    }
                }

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

            InputMode::FilterEdit => match event.code {
                crossterm::event::KeyCode::Tab => {
                    self.filter.active_field = match self.filter.active_field {
                        FilterField::Date       => FilterField::Instrument,
                        FilterField::Instrument => FilterField::Date,
                    };
                    self.do_refresh_dropdown();
                }
                crossterm::event::KeyCode::Up => {
                    if self.filter.dropdown_idx > 0 { self.filter.dropdown_idx -= 1; }
                }
                crossterm::event::KeyCode::Down => {
                    if self.filter.dropdown_idx + 1 < self.filter.dropdown.len() {
                        self.filter.dropdown_idx += 1;
                    }
                }
                crossterm::event::KeyCode::Enter => {
                    // If a dropdown item is highlighted, select it
                    if !self.filter.dropdown.is_empty() {
                        let chosen = self.filter.dropdown[self.filter.dropdown_idx].clone();
                        match self.filter.active_field {
                            FilterField::Instrument => self.filter.instrument_input = chosen,
                            FilterField::Date       => self.filter.date_input = chosen,
                        }
                    }
                    self.filter.commit();
                    self.input_mode = InputMode::Normal;
                    self.hist_loading = false;
                    self.trigger_historical_fetch();
                }
                crossterm::event::KeyCode::Esc => {
                    self.input_mode = InputMode::Normal;
                    self.filter.dropdown.clear();
                }
                crossterm::event::KeyCode::Backspace => {
                    match self.filter.active_field {
                        FilterField::Date       => { self.filter.date_input.pop(); }
                        FilterField::Instrument => { self.filter.instrument_input.pop(); }
                    }
                    self.do_refresh_dropdown();
                }
                crossterm::event::KeyCode::Char(c) => {
                    match self.filter.active_field {
                        FilterField::Date       => self.filter.date_input.push(c),
                        FilterField::Instrument => self.filter.instrument_input.push(c),
                    }
                    self.do_refresh_dropdown();
                }
                _ => {}
            },

            InputMode::AddingFavorite => match event.code {
                crossterm::event::KeyCode::Up => {
                    if self.fav_dropdown_idx > 0 { self.fav_dropdown_idx -= 1; }
                }
                crossterm::event::KeyCode::Down => {
                    if self.fav_dropdown_idx + 1 < self.fav_dropdown.len() {
                        self.fav_dropdown_idx += 1;
                    }
                }
                crossterm::event::KeyCode::Enter => {
                    let s = if !self.fav_dropdown.is_empty() {
                        self.fav_dropdown[self.fav_dropdown_idx].clone()
                    } else {
                        self.fav_input.trim().to_uppercase()
                    };
                    if !s.is_empty() && !self.favorites.contains(&s) {
                        self.favorites.push(s);
                        self.fav_selected = self.favorites.len() - 1;
                    }
                    self.input_mode = InputMode::Normal;
                    self.fav_input.clear();
                    self.fav_dropdown.clear();
                }
                crossterm::event::KeyCode::Char(c) => {
                    self.fav_input.push(c);
                    let q = self.fav_input.to_lowercase();
                    self.fav_dropdown = self.available_instruments.iter()
                        .filter(|s| s.to_lowercase().contains(&q))
                        .cloned().collect();
                    self.fav_dropdown_idx = 0;
                }
                crossterm::event::KeyCode::Backspace => {
                    self.fav_input.pop();
                    let q = self.fav_input.to_lowercase();
                    self.fav_dropdown = self.available_instruments.iter()
                        .filter(|s| q.is_empty() || s.to_lowercase().contains(&q))
                        .cloned().collect();
                    self.fav_dropdown_idx = 0;
                }
                crossterm::event::KeyCode::Esc => {
                    self.input_mode = InputMode::Normal;
                    self.fav_input.clear();
                    self.fav_dropdown.clear();
                }
                _ => {}
            },
        }
        true
    }

    // ─── Top-level render ───────────────────────────────────────────────

    pub fn render(&mut self, frame: &mut Frame) {
        let active_subtab = match self.active_tab {
            ExchangeTab::Binance => self.binance_subtab,
            ExchangeTab::Merval => self.merval_subtab,
        };
        let show_filter_bar = active_subtab == SubTab::Historical;

        let constraints = if show_filter_bar {
            vec![
                Constraint::Length(3),  // Tabs
                Constraint::Length(1),  // Sub-tabs
                Constraint::Length(3),  // Status bar
                Constraint::Length(3),  // Filter bar
                Constraint::Min(12),    // Main content
                Constraint::Length(8),  // Trades / Orders
                Constraint::Length(3),  // Input line
            ]
        } else {
            vec![
                Constraint::Length(3),
                Constraint::Length(1),
                Constraint::Length(3),
                Constraint::Min(12),
                Constraint::Length(8),
                Constraint::Length(3),
            ]
        };

        let chunks = Layout::default()
            .direction(Direction::Vertical)
            .constraints(constraints)
            .split(frame.size());

        self.render_tabs(chunks[0], frame);
        self.render_subtabs(chunks[1], frame);
        self.render_status_bar(chunks[2], frame);

        if show_filter_bar {
            self.render_filter_bar(chunks[3], frame);
            match (self.active_tab, active_subtab) {
                (ExchangeTab::Binance, SubTab::Historical) => {
                    self.render_historical_placeholder("Binance", chunks[4], frame);
                    self.render_historical_placeholder_bottom("Binance", chunks[5], frame);
                }
                (ExchangeTab::Merval, SubTab::Historical) => {
                    self.render_merval_historical(chunks[4], chunks[5], frame);
                }
                _ => {}
            }
            self.render_input_area(chunks[6], frame);
        } else {
            match (self.active_tab, active_subtab) {
                (ExchangeTab::Binance, SubTab::RealTime) => {
                    self.render_binance_view(chunks[3], frame);
                    self.render_recent_trades(chunks[4], frame);
                }
                (ExchangeTab::Merval, SubTab::RealTime) => {
                    self.render_merval_view(chunks[3], frame);
                    self.render_orders_table(chunks[4], frame);
                }
                _ => {}
            }
            self.render_input_area(chunks[5], frame);
        }
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
        ]);

        frame.render_widget(Paragraph::new(line), area);
    }

    // ─── Historical views ────────────────────────────────────────────────

    fn render_historical_placeholder(&mut self, exchange: &str, area: Rect, frame: &mut Frame) {
        if self.hist_loading {
            let p = Paragraph::new("  Loading from PostgreSQL…")
                .block(Block::default().borders(Borders::ALL).title(format!(" {} — Historical ", exchange)));
            frame.render_widget(p, area);
            return;
        }
        if let Some(ref e) = self.hist_error {
            let p = Paragraph::new(format!("  Error: {e}"))
                .style(Style::default().fg(Color::Red))
                .block(Block::default().borders(Borders::ALL).title(" Error "));
            frame.render_widget(p, area);
            return;
        }

        match exchange {
            "Binance" => self.render_binance_ticks_table(area, frame),
            _         => self.render_merval_ticks_table(area, frame),
        }
    }

    fn render_historical_placeholder_bottom(&mut self, exchange: &str, area: Rect, frame: &mut Frame) {
        if self.hist_loading {
            let p = Paragraph::new("  Loading…")
                .block(Block::default().borders(Borders::ALL).title(" Historical "));
            frame.render_widget(p, area);
            return;
        }
        match exchange {
            "Binance" => self.render_binance_trades_table(area, frame),
            _         => self.render_merval_orders_table_hist(area, frame),
        }
    }

    fn render_binance_ticks_table(&mut self, area: Rect, frame: &mut Frame) {
        let focused = self.hist_focus == HistFocus::Top;
        let header = ratatui::widgets::Row::new(vec!["Timestamp", "Symbol", "Open", "High", "Low", "Close", "Volume"])
            .style(Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD));

        let rows: Vec<ratatui::widgets::Row> = self.hist_binance_ticks.iter().map(|r| {
            ratatui::widgets::Row::new(vec![
                r.timestamp.format("%Y-%m-%d %H:%M:%S").to_string(),
                r.symbol.clone(),
                format!("{:.4}", r.open),
                format!("{:.4}", r.high),
                format!("{:.4}", r.low),
                format!("{:.4}", r.close),
                fmt_volume(r.volume),
            ]).style(Style::default().fg(Color::White))
        }).collect();

        let widths = [
            Constraint::Length(20), Constraint::Length(12),
            Constraint::Length(12), Constraint::Length(12),
            Constraint::Length(12), Constraint::Length(12),
            Constraint::Length(10),
        ];
        let title = if focused { " Binance Ticks [↑↓ scroll] [p panel] " } else { " Binance Ticks [p focus] " };
        let table = Table::new(rows, widths)
            .header(header)
            .highlight_style(Style::default().fg(Color::Black).bg(Color::Cyan).add_modifier(Modifier::BOLD))
            .highlight_symbol(if focused { "▶ " } else { "  " })
            .block(Block::default().borders(Borders::ALL)
                .title(title)
                .border_style(if focused { Style::default().fg(Color::Cyan) } else { Style::default() }));
        frame.render_stateful_widget(table, area, &mut self.hist_binance_ticks_state);
    }

    fn render_binance_trades_table(&mut self, area: Rect, frame: &mut Frame) {
        let focused = self.hist_focus == HistFocus::Bottom;
        let header = ratatui::widgets::Row::new(vec!["Time", "Symbol", "Price", "Qty", "Side"])
            .style(Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD));

        let rows: Vec<ratatui::widgets::Row> = self.hist_binance_trades.iter().map(|r| {
            let color = if r.is_buyer_maker { Color::Red } else { Color::Green };
            let side = if r.is_buyer_maker { "SELL" } else { "BUY" };
            ratatui::widgets::Row::new(vec![
                r.time.format("%H:%M:%S").to_string(),
                r.symbol.clone(),
                format!("{:.4}", r.price),
                format!("{:.6}", r.qty),
                side.to_string(),
            ]).style(Style::default().fg(color))
        }).collect();

        let widths = [
            Constraint::Length(10), Constraint::Length(12),
            Constraint::Length(14), Constraint::Length(12),
            Constraint::Length(6),
        ];
        let title = if focused { " Binance Trades [↑↓ scroll] [p panel] " } else { " Binance Trades [p focus] " };
        let table = Table::new(rows, widths)
            .header(header)
            .highlight_style(Style::default().fg(Color::Black).bg(Color::Yellow).add_modifier(Modifier::BOLD))
            .highlight_symbol(if focused { "▶ " } else { "  " })
            .block(Block::default().borders(Borders::ALL)
                .title(title)
                .border_style(if focused { Style::default().fg(Color::Cyan) } else { Style::default() }));
        frame.render_stateful_widget(table, area, &mut self.hist_binance_trades_state);
    }

    fn render_merval_ticks_table(&mut self, area: Rect, frame: &mut Frame) {
        let focused = self.hist_focus == HistFocus::Top;
        let header = ratatui::widgets::Row::new(vec!["Time", "Instrument", "Bid", "Ask", "Last", "Volume"])
            .style(Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD));

        let rows: Vec<ratatui::widgets::Row> = self.hist_ticks.iter().map(|r| {
            ratatui::widgets::Row::new(vec![
                r.time.format("%Y-%m-%d %H:%M:%S").to_string(),
                r.instrument.clone(),
                format!("{:.2}", r.bid_price),
                format!("{:.2}", r.ask_price),
                format!("{:.2}", r.last_price),
                r.total_volume.to_string(),
            ]).style(Style::default().fg(Color::White))
        }).collect();

        let widths = [
            Constraint::Length(20), Constraint::Min(20),
            Constraint::Length(12), Constraint::Length(12),
            Constraint::Length(12), Constraint::Length(12),
        ];
        let title = if focused { " MERVAL Ticks [↑↓ scroll] [p panel] " } else { " MERVAL Ticks [p focus] " };
        let table = Table::new(rows, widths)
            .header(header)
            .highlight_style(Style::default().fg(Color::Black).bg(Color::LightBlue).add_modifier(Modifier::BOLD))
            .highlight_symbol(if focused { "▶ " } else { "  " })
            .block(Block::default().borders(Borders::ALL)
                .title(title)
                .border_style(if focused { Style::default().fg(Color::Cyan) } else { Style::default() }));
        frame.render_stateful_widget(table, area, &mut self.hist_ticks_state);
    }

    fn render_merval_orders_table_hist(&mut self, area: Rect, frame: &mut Frame) {
        let focused = self.hist_focus == HistFocus::Bottom;
        let header = ratatui::widgets::Row::new(vec!["Time", "Instrument", "Price", "Volume", "Side"])
            .style(Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD));

        let rows: Vec<ratatui::widgets::Row> = self.hist_orders.iter().map(|r| {
            let color = if r.side == "B" { Color::Green } else { Color::Red };
            let side_label = if r.side == "B" { "BUY" } else { "SELL" };
            ratatui::widgets::Row::new(vec![
                r.time.format("%H:%M:%S").to_string(),
                r.instrument.clone(),
                format!("{:.2}", r.price),
                r.volume.to_string(),
                side_label.to_string(),
            ]).style(Style::default().fg(color))
        }).collect();

        let widths = [
            Constraint::Length(10), Constraint::Min(20),
            Constraint::Length(12), Constraint::Length(10),
            Constraint::Length(6),
        ];
        let title = if focused { " MERVAL Orders [↑↓ scroll] [p panel] " } else { " MERVAL Orders [p focus] " };
        let table = Table::new(rows, widths)
            .header(header)
            .highlight_style(Style::default().fg(Color::Black).bg(Color::LightBlue).add_modifier(Modifier::BOLD))
            .highlight_symbol(if focused { "▶ " } else { "  " })
            .block(Block::default().borders(Borders::ALL)
                .title(title)
                .border_style(if focused { Style::default().fg(Color::Cyan) } else { Style::default() }));
        frame.render_stateful_widget(table, area, &mut self.hist_orders_state);
    }

    // ─── MERVAL Historical dispatcher ────────────────────────────────────

    fn render_merval_historical(&mut self, top: Rect, bottom: Rect, frame: &mut Frame) {
        if self.hist_loading {
            let p = Paragraph::new("  Loading from PostgreSQL…")
                .block(Block::default().borders(Borders::ALL).title(" MERVAL — Historical "));
            frame.render_widget(p, top);
            return;
        }
        if let Some(ref e) = self.hist_error.clone() {
            let p = Paragraph::new(format!("  Error: {e}"))
                .style(Style::default().fg(Color::Red))
                .block(Block::default().borders(Borders::ALL).title(" Error "));
            frame.render_widget(p, top);
            return;
        }

        // Category tab bar at top of the top panel
        let (tab_area, content_area) = {
            let v = Layout::default()
                .direction(Direction::Vertical)
                .constraints([Constraint::Length(1), Constraint::Min(0)])
                .split(top);
            (v[0], v[1])
        };
        self.render_merval_hist_tabs(tab_area, frame);

        match self.merval_hist_tab {
            MervalHistTab::Favorites => self.render_favorites_view(content_area, bottom, frame),
            cat => {
                // Filter ticks and orders by category
                let ticks: Vec<HistTick> = self.hist_ticks.iter()
                    .filter(|r| cat.matches(&r.instrument))
                    .cloned().collect();
                let orders: Vec<HistOrder> = self.hist_orders.iter()
                    .filter(|r| cat.matches(&r.instrument))
                    .cloned().collect();
                self.render_category_ticks(content_area, frame, &ticks, cat);
                self.render_category_orders(bottom, frame, &orders, cat);
            }
        }
    }

    fn render_merval_hist_tabs(&self, area: Rect, frame: &mut Frame) {
        let tabs = [MervalHistTab::Stocks, MervalHistTab::Options, MervalHistTab::Bonds, MervalHistTab::Favorites];
        let spans: Vec<Span> = tabs.iter().flat_map(|&t| {
            let style = if t == self.merval_hist_tab {
                Style::default().fg(Color::Black).bg(Color::LightBlue).add_modifier(Modifier::BOLD)
            } else {
                Style::default().fg(Color::DarkGray)
            };
            let key = match t {
                MervalHistTab::Stocks    => "1",
                MervalHistTab::Options   => "2",
                MervalHistTab::Bonds     => "3",
                MervalHistTab::Favorites => "4",
            };
            vec![
                Span::styled(format!(" [{}]{} ", key, t.label()), style),
                Span::raw(" "),
            ]
        }).collect();
        frame.render_widget(Paragraph::new(Line::from(spans)), area);
    }

    fn render_category_ticks(&mut self, area: Rect, frame: &mut Frame, ticks: &[HistTick], cat: MervalHistTab) {
        let focused = self.hist_focus == HistFocus::Top;
        let header = ratatui::widgets::Row::new(vec!["Time", "Instrument", "Bid", "Ask", "Last", "Volume"])
            .style(Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD));
        let rows: Vec<ratatui::widgets::Row> = ticks.iter().map(|r| {
            ratatui::widgets::Row::new(vec![
                r.time.format("%Y-%m-%d %H:%M:%S").to_string(),
                r.instrument.clone(),
                format!("{:.2}", r.bid_price),
                format!("{:.2}", r.ask_price),
                format!("{:.2}", r.last_price),
                r.total_volume.to_string(),
            ]).style(Style::default().fg(Color::White))
        }).collect();
        let title = format!(" {} Ticks ({}) ", cat.label(), ticks.len());
        let table = Table::new(rows, [Constraint::Length(20), Constraint::Min(20), Constraint::Length(12), Constraint::Length(12), Constraint::Length(12), Constraint::Length(12)])
            .header(header)
            .highlight_style(Style::default().fg(Color::Black).bg(Color::LightBlue).add_modifier(Modifier::BOLD))
            .highlight_symbol(if focused { "▶ " } else { "  " })
            .block(Block::default().borders(Borders::ALL).title(title)
                .border_style(if focused { Style::default().fg(Color::Cyan) } else { Style::default() }));
        frame.render_stateful_widget(table, area, &mut self.hist_ticks_state);
    }

    fn render_category_orders(&mut self, area: Rect, frame: &mut Frame, orders: &[HistOrder], cat: MervalHistTab) {
        let focused = self.hist_focus == HistFocus::Bottom;
        let header = ratatui::widgets::Row::new(vec!["Time", "Instrument", "Price", "Volume", "Side"])
            .style(Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD));
        let rows: Vec<ratatui::widgets::Row> = orders.iter().map(|r| {
            let color = if r.side == "B" { Color::Green } else { Color::Red };
            ratatui::widgets::Row::new(vec![
                r.time.format("%H:%M:%S").to_string(),
                r.instrument.clone(),
                format!("{:.2}", r.price),
                r.volume.to_string(),
                if r.side == "B" { "BUY".into() } else { "SELL".into() },
            ]).style(Style::default().fg(color))
        }).collect();
        let title = format!(" {} Orders ({}) ", cat.label(), orders.len());
        let table = Table::new(rows, [Constraint::Length(10), Constraint::Min(20), Constraint::Length(12), Constraint::Length(10), Constraint::Length(6)])
            .header(header)
            .highlight_style(Style::default().fg(Color::Black).bg(Color::LightBlue).add_modifier(Modifier::BOLD))
            .highlight_symbol(if focused { "▶ " } else { "  " })
            .block(Block::default().borders(Borders::ALL).title(title)
                .border_style(if focused { Style::default().fg(Color::Cyan) } else { Style::default() }));
        frame.render_stateful_widget(table, area, &mut self.hist_orders_state);
    }

    // ─── Favorites view ──────────────────────────────────────────────────

    fn render_favorites_view(&mut self, top: Rect, bottom: Rect, frame: &mut Frame) {
        // Split top into: favorites list (left) + sparkline (right)
        let h = Layout::default()
            .direction(Direction::Horizontal)
            .constraints([Constraint::Length(20), Constraint::Min(0)])
            .split(top);

        // Favorites list
        let items: Vec<ListItem> = self.favorites.iter().enumerate().map(|(i, f)| {
            let style = if i == self.fav_selected {
                Style::default().fg(Color::Black).bg(Color::Yellow).add_modifier(Modifier::BOLD)
            } else {
                Style::default().fg(Color::White)
            };
            ListItem::new(Line::from(vec![
                Span::styled(format!(" {} ", f), style),
            ]))
        }).collect();

        let fav_hint = if self.input_mode == InputMode::AddingFavorite {
            format!("> {}_", self.fav_input)
        } else {
            "[a] add  [d] del  [←→] nav".to_string()
        };
        let list = List::new(items)
            .block(Block::default().borders(Borders::ALL).title(format!(" Favorites — {} ", fav_hint)));
        frame.render_widget(list, h[0]);

        // Dropdown overlay for AddingFavorite
        if self.input_mode == InputMode::AddingFavorite && !self.fav_dropdown.is_empty() {
            let max_show = 8usize;
            let show = self.fav_dropdown.len().min(max_show);
            let drop_area = Rect {
                x: h[0].x,
                y: h[0].y + h[0].height,
                width: h[0].width,
                height: show as u16 + 2,
            };
            if drop_area.y + drop_area.height <= frame.size().height {
                let drop_items: Vec<ListItem> = self.fav_dropdown.iter().enumerate()
                    .take(max_show)
                    .map(|(i, s)| {
                        let style = if i == self.fav_dropdown_idx {
                            Style::default().fg(Color::Black).bg(Color::Yellow).add_modifier(Modifier::BOLD)
                        } else {
                            Style::default().fg(Color::White)
                        };
                        ListItem::new(Span::styled(format!(" {} ", s), style))
                    })
                    .collect();
                frame.render_widget(
                    List::new(drop_items).block(Block::default().borders(Borders::ALL).style(Style::default().bg(Color::Black))),
                    drop_area,
                );
            }
        }

        // OHLCV sparkline for selected favorite
        let fav = self.selected_favorite();
        if let Some(ref sym) = fav {
            let sym_up = sym.to_uppercase();
            let prices: Vec<u64> = self.hist_ticks.iter()
                .filter(|r| r.instrument.to_uppercase().contains(&sym_up))
                .map(|r| (r.last_price * 100.0) as u64)
                .collect();

            // Stats
            let last  = prices.last().copied().unwrap_or(0) as f64 / 100.0;
            let high  = prices.iter().copied().max().unwrap_or(0) as f64 / 100.0;
            let low   = prices.iter().copied().min().unwrap_or(0) as f64 / 100.0;
            let open  = prices.first().copied().unwrap_or(0) as f64 / 100.0;
            let chg   = if open > 0.0 { (last - open) / open * 100.0 } else { 0.0 };
            let chg_color = if chg >= 0.0 { Color::Green } else { Color::Red };

            let v = Layout::default()
                .direction(Direction::Vertical)
                .constraints([Constraint::Min(0), Constraint::Length(3)])
                .split(h[1]);

            let spark = Sparkline::default()
                .data(&prices)
                .style(Style::default().fg(if chg >= 0.0 { Color::Green } else { Color::Red }))
                .block(Block::default().borders(Borders::ALL).title(format!(" {} — Price ", sym)));
            frame.render_widget(spark, v[0]);

            let stats = Line::from(vec![
                Span::styled(format!(" O:{:.2}  H:{:.2}  L:{:.2}  Last:{:.2}  ", open, high, low, last), Style::default().fg(Color::Cyan)),
                Span::styled(format!("{:+.2}%", chg), Style::default().fg(chg_color).add_modifier(Modifier::BOLD)),
            ]);
            frame.render_widget(Paragraph::new(stats).block(Block::default().borders(Borders::ALL)), v[1]);

            // Bottom: ticks and orders for this favorite
            let bh = Layout::default()
                .direction(Direction::Horizontal)
                .constraints([Constraint::Percentage(50), Constraint::Percentage(50)])
                .split(bottom);

            // Ticks table
            {
                let focused = self.fav_focus == HistFocus::Top;
                let header = ratatui::widgets::Row::new(vec!["Time", "Bid", "Ask", "Last", "Vol"])
                    .style(Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD));
                let rows: Vec<ratatui::widgets::Row> = self.hist_ticks.iter()
                    .filter(|r| r.instrument.to_uppercase().contains(&sym_up))
                    .map(|r| ratatui::widgets::Row::new(vec![
                        r.time.format("%H:%M:%S").to_string(),
                        format!("{:.2}", r.bid_price),
                        format!("{:.2}", r.ask_price),
                        format!("{:.2}", r.last_price),
                        r.total_volume.to_string(),
                    ]).style(Style::default().fg(Color::White)))
                    .collect();
                let table = Table::new(rows, [Constraint::Length(10), Constraint::Length(10), Constraint::Length(10), Constraint::Length(10), Constraint::Length(10)])
                    .header(header)
                    .highlight_style(Style::default().fg(Color::Black).bg(Color::LightBlue).add_modifier(Modifier::BOLD))
                    .highlight_symbol(if focused { "▶ " } else { "  " })
                    .block(Block::default().borders(Borders::ALL).title(format!(" {} Ticks ", sym))
                        .border_style(if focused { Style::default().fg(Color::Cyan) } else { Style::default() }));
                frame.render_stateful_widget(table, bh[0], &mut self.fav_ticks_state);
            }

            // Orders table
            {
                let focused = self.fav_focus == HistFocus::Bottom;
                let header = ratatui::widgets::Row::new(vec!["Time", "Price", "Vol", "Side"])
                    .style(Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD));
                let rows: Vec<ratatui::widgets::Row> = self.hist_orders.iter()
                    .filter(|r| r.instrument.to_uppercase().contains(&sym_up))
                    .map(|r| {
                        let color = if r.side == "B" { Color::Green } else { Color::Red };
                        ratatui::widgets::Row::new(vec![
                            r.time.format("%H:%M:%S").to_string(),
                            format!("{:.2}", r.price),
                            r.volume.to_string(),
                            if r.side == "B" { "BUY".into() } else { "SELL".into() },
                        ]).style(Style::default().fg(color))
                    })
                    .collect();
                let table = Table::new(rows, [Constraint::Length(10), Constraint::Length(12), Constraint::Length(10), Constraint::Length(6)])
                    .header(header)
                    .highlight_style(Style::default().fg(Color::Black).bg(Color::LightBlue).add_modifier(Modifier::BOLD))
                    .highlight_symbol(if focused { "▶ " } else { "  " })
                    .block(Block::default().borders(Borders::ALL).title(format!(" {} Orders ", sym))
                        .border_style(if focused { Style::default().fg(Color::Cyan) } else { Style::default() }));
                frame.render_stateful_widget(table, bh[1], &mut self.fav_orders_state);
            }
        } else {
            let p = Paragraph::new("  No favorites yet — press [a] to add an instrument")
                .style(Style::default().fg(Color::DarkGray))
                .block(Block::default().borders(Borders::ALL));
            frame.render_widget(p, h[1]);
            let p2 = Paragraph::new("")
                .block(Block::default().borders(Borders::ALL));
            frame.render_widget(p2, bottom);
        }
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

    // ─── Filter bar ─────────────────────────────────────────────────────

    fn render_filter_bar(&self, area: Rect, frame: &mut Frame) {
        let editing = self.input_mode == InputMode::FilterEdit;
        let accent = Color::Cyan;

        let date_style = if editing && self.filter.active_field == FilterField::Date {
            Style::default().fg(Color::Black).bg(accent).add_modifier(Modifier::BOLD)
        } else {
            Style::default().fg(accent)
        };
        let instr_style = if editing && self.filter.active_field == FilterField::Instrument {
            Style::default().fg(Color::Black).bg(accent).add_modifier(Modifier::BOLD)
        } else {
            Style::default().fg(accent)
        };

        let date_val  = if self.filter.date_input.is_empty() { "YYYY-MM-DD".to_string() } else { self.filter.date_input.clone() };
        let instr_val = if self.filter.instrument_input.is_empty() { "all".to_string() } else { self.filter.instrument_input.clone() };

        let line = Line::from(vec![
            Span::raw(" Date: "),
            Span::styled(format!(" {} ", date_val), date_style),
            Span::raw("   Instrument: "),
            Span::styled(format!(" {} ", instr_val), instr_style),
        ]);

        frame.render_widget(
            Paragraph::new(line).block(Block::default().borders(Borders::ALL)
                .title(" Filters ")
                .style(if editing { Style::default().fg(Color::Cyan) } else { Style::default().fg(Color::DarkGray) })),
            area,
        );

        // Dropdown overlay — rendered below the filter bar
        if editing && !self.filter.dropdown.is_empty() {
            let max_show = 8usize;
            let show = self.filter.dropdown.len().min(max_show);
            // Compute x offset based on active field
            let x_off = match self.filter.active_field {
                FilterField::Date       => 8u16,
                FilterField::Instrument => 36u16,
            };
            let drop_area = Rect {
                x: area.x + x_off,
                y: area.y + area.height,
                width: 30,
                height: show as u16 + 2,
            };
            // Clamp to frame
            if drop_area.y + drop_area.height <= frame.size().height {
                let items: Vec<ListItem> = self.filter.dropdown.iter().enumerate()
                    .take(max_show)
                    .map(|(i, s)| {
                        let style = if i == self.filter.dropdown_idx {
                            Style::default().fg(Color::Black).bg(Color::Cyan).add_modifier(Modifier::BOLD)
                        } else {
                            Style::default().fg(Color::White)
                        };
                        ListItem::new(Span::styled(format!(" {} ", s), style))
                    })
                    .collect();
                frame.render_widget(
                    List::new(items).block(Block::default().borders(Borders::ALL).style(Style::default().bg(Color::Black))),
                    drop_area,
                );
            }
        }
    }

    // ─── Input / controls ───────────────────────────────────────────────

    fn render_input_area(&self, area: Rect, frame: &mut Frame) {
        let active_subtab = match self.active_tab {
            ExchangeTab::Binance => self.binance_subtab,
            ExchangeTab::Merval  => self.merval_subtab,
        };

        let (text, style) = match self.input_mode {
            InputMode::EditingOrder => (
                format!("> {}", self.order_input),
                Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD),
            ),
            InputMode::FilterEdit => (
                "[Tab] switch field  [Enter] apply  [Esc] cancel".to_string(),
                Style::default().fg(Color::Cyan),
            ),
            InputMode::AddingFavorite => (
                format!("Add favorite: {}_  [Enter] confirm  [Esc] cancel", self.fav_input),
                Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD),
            ),
            InputMode::Normal => {
                let hint = match (self.active_tab, active_subtab) {
                    (ExchangeTab::Merval, SubTab::Historical) if self.merval_hist_tab == MervalHistTab::Favorites =>
                        "[↑↓] scroll  [←→] nav favorites  [a] add  [d] del  [p] panel  [f] filter  [s] real-time  [Tab] switch tab  [q] quit",
                    (_, SubTab::Historical) =>
                        "[↑↓] scroll  [p] switch panel  [f] filter  [s] real-time  [Tab] switch tab  [q] quit",
                    (ExchangeTab::Merval, SubTab::RealTime) =>
                        "[o] new order  [↑↓] navigate  [s] historical  [Tab] switch tab  [q] quit",
                    (ExchangeTab::Binance, SubTab::RealTime) =>
                        "[↑↓] select symbol  [s] historical  [Tab] switch tab  [q] quit",
                };
                (hint.to_string(), Style::default().fg(Color::DarkGray))
            }
        };

        let paragraph = Paragraph::new(text)
            .block(Block::default().borders(Borders::ALL))
            .style(style);
        frame.render_widget(paragraph, area);
    }
}