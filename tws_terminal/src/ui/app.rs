use std::collections::{HashMap, VecDeque};
use std::sync::Arc;

use ratatui::{
    layout::{Constraint, Direction, Layout, Rect},
    style::{Color, Modifier, Style},
    text::{Line, Span, Text},
    widgets::{canvas::*, Axis, BarChart, Block, Borders, Chart, Dataset, GraphType, List, ListItem, Paragraph, Sparkline, Table, TableState, Tabs},
    symbols,
    Frame,
};

use crate::data::{BinanceSymbolData, ExchangeData, MervalLiveInstrument, Order, RecentTrade};
use crate::db::{FuturesRow, HistBinanceTick, HistBinanceTrade, HistFilter, HistOrder, HistTick, MarketRow, OptionRow};
use crate::network::WebSocketMessage;
use tokio::sync::mpsc::UnboundedSender;

// ─── Tab / mode enums ─────────────────────────────────────────────────────

#[derive(PartialEq, Clone, Copy, Debug)]
pub enum ExchangeTab {
    Binance,
    Merval,
    Options,
    Futures,
    News,
    Markets,
    UsFutures,
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
    FilterEdit,
    AddingFavorite,
    CalcEdit,
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

// ─── News item ────────────────────────────────────────────────────────────

#[derive(Clone, Debug, serde::Serialize, serde::Deserialize)]
pub struct NewsItem {
    pub time:        String,
    pub source:      String,
    pub headline:    String,
    pub url:         String,
    pub description: String,
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
    OptionsChain(Vec<OptionRow>),
    GgalSpot(f64),
    FuturesCurve(Vec<FuturesRow>),
    FuturesTicks(Vec<HistTick>),
    BinancePriceHistory(String, Vec<u64>),
    MervalInstruments(Vec<String>),
    MervalInstrumentOrders(Vec<HistOrder>),
    MervalOhlcv(Vec<crate::db::OhlcvBar>),
    News(Vec<NewsItem>),
    UsFuturesOhlcv(Vec<crate::db::UsFuturesOhlcv>),
    MarketsData(Vec<MarketRow>),
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

// ─── Math helpers ─────────────────────────────────────────────────────────

/// Error function approximation (Abramowitz & Stegun 7.1.26, max error 1.5e-7)
fn libm_erf(x: f64) -> f64 {
    let t = 1.0 / (1.0 + 0.3275911 * x.abs());
    let poly = t * (0.254829592 + t * (-0.284496736 + t * (1.421413741 + t * (-1.453152027 + t * 1.061405429))));
    let sign = if x >= 0.0 { 1.0 } else { -1.0 };
    sign * (1.0 - poly * (-x * x).exp())
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
    /// Per-instrument live state, keyed by full instrument name (e.g. "M:bm_MERV_GGAL_24hs")
    pub merval_live: HashMap<String, MervalLiveInstrument>,
    /// Sorted instrument names for stable table order
    pub merval_live_sorted: Vec<String>,
    /// Scroll / highlight state for the live instruments table
    pub merval_live_state: TableState,

    // ── Order management ──
    pub orders: Vec<Order>,
    pub orders_table_state: TableState,
    pub selected_order_index: usize,

    // ── UI state ──
    pub input_mode: InputMode,
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

    // ── MERVAL historical instrument browser ──
    pub merval_hist_tab: MervalHistTab,  // kept for favorites panel compatibility
    pub merval_instruments:       Vec<String>,
    pub merval_inst_list_state:   ratatui::widgets::ListState,
    pub merval_selected_instr:    Option<String>,
    pub merval_detail_orders:     Vec<HistOrder>,
    pub merval_detail_orders_state: TableState,
    // PPI daily OHLCV
    pub merval_ppi_ohlcv:     Vec<crate::db::OhlcvBar>,
    pub merval_ohlcv_loading: bool,

    // ── Favorites ──
    pub favorites: Vec<String>,
    pub fav_selected: usize,
    pub fav_input: String,
    pub fav_ticks_state:  TableState,
    pub fav_orders_state: TableState,
    pub fav_focus: HistFocus,

    // ── DB channel sender (set by main) ──
    pub db_tx: Option<UnboundedSender<DbMessage>>,
    /// Persistent shared Postgres connection — avoids per-trigger TCP handshake
    pub db_client: Option<Arc<tokio_postgres::Client>>,

    // ── Symbols whose price history has been seeded from DB ──
    pub seeded_symbols: std::collections::HashSet<String>,

    // ── Historical filter ──
    pub filter: FilterState,

    // ── Autocomplete candidates ──
    pub available_instruments:     Vec<String>,
    pub available_dates:           Vec<String>,
    pub available_binance_symbols: Vec<String>,
    /// Dropdown for AddingFavorite mode
    pub fav_dropdown:     Vec<String>,
    pub fav_dropdown_idx: usize,

    // ── Options tab ──
    pub options_underlyings:    Vec<&'static str>,
    pub options_underlying_idx: usize,
    pub options_chain:          Vec<OptionRow>,
    pub options_chain_state:    TableState,
    pub options_puts_state:     TableState,
    pub options_loading:        bool,
    pub ggal_spot:              f64,
    pub options_show_calls:     bool,  // true = calls panel focused, false = puts
    // BS calculator — only IV is entered; S/K/T auto-filled from selected row
    pub calc_open:      bool,
    pub calc_iv:        String,        // manually entered IV override (decimal, e.g. "0.45")
    pub calc_field_idx: usize,
    pub calc_result:    Option<(f64, f64, f64, f64, f64, f64)>, // price,Δ,Γ,Θ,vega,rho

    // ── Futures tab ──
    pub futures_curve:       Vec<FuturesRow>,
    pub futures_selected:    usize,
    pub futures_ticks:       Vec<HistTick>,
    pub futures_ticks_state: TableState,

    // ── US Futures tab ──
    pub us_futures_live:    std::collections::HashMap<String, (f64, f64)>, // symbol → (price, prev_price)
    pub us_futures_history: std::collections::HashMap<String, Vec<(f64, f64)>>, // symbol → price history for live chart
    pub us_futures_subtab:  SubTab,
    pub us_futures_selected: usize,
    pub us_futures_ohlcv:   Vec<crate::db::UsFuturesOhlcv>,
    pub us_futures_symbols: Vec<&'static str>,
    pub news_items:   Vec<NewsItem>,
    pub news_state:   ratatui::widgets::ListState,
    pub news_loading: bool,

    // ── Markets tab ──
    pub markets_data: HashMap<String, MarketRow>,
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
            merval_live: HashMap::new(),
            merval_live_sorted: Vec::new(),
            merval_live_state: TableState::default(),
            orders: Vec::new(),
            orders_table_state: TableState::default(),
            selected_order_index: 0,
            input_mode: InputMode::Normal,
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
            merval_instruments:         Vec::new(),
            merval_inst_list_state:     ratatui::widgets::ListState::default(),
            merval_selected_instr:      None,
            merval_detail_orders:       Vec::new(),
            merval_detail_orders_state: TableState::default(),
            merval_ppi_ohlcv:     Vec::new(),
            merval_ohlcv_loading: false,
            favorites: Vec::new(),
            fav_selected: 0,
            fav_input: String::new(),
            fav_ticks_state:  TableState::default(),
            fav_orders_state: TableState::default(),
            fav_focus: HistFocus::Top,
            db_tx: None,
            db_client: None,
            seeded_symbols: std::collections::HashSet::new(),
            filter: FilterState::new(),
            available_instruments:     Vec::new(),
            available_dates:           Vec::new(),
            available_binance_symbols: Vec::new(),
            fav_dropdown:     Vec::new(),
            fav_dropdown_idx: 0,
            options_underlyings:    vec!["GGAL", "SUPV", "PBRD", "PAMP", "YPFD"],
            options_underlying_idx: 0,
            options_chain:          Vec::new(),
            options_chain_state:    TableState::default(),
            options_puts_state:     TableState::default(),
            options_loading:        false,
            ggal_spot:              0.0,
            options_show_calls:     true,
            calc_open:      false,
            calc_iv:        String::new(),
            calc_field_idx: 0,
            calc_result:    None,
            futures_curve:       Vec::new(),
            futures_selected:    0,
            futures_ticks:       Vec::new(),
            futures_ticks_state: TableState::default(),
            news_items:   Vec::new(),
            news_state:   ratatui::widgets::ListState::default(),
            news_loading: false,
            us_futures_live:     std::collections::HashMap::new(),
            us_futures_history:  std::collections::HashMap::new(),
            us_futures_subtab:   SubTab::RealTime,
            us_futures_selected: 0,
            us_futures_ohlcv:    Vec::new(),
            us_futures_symbols:  vec!["ES=F","NQ=F","YM=F","CL=F","GC=F","SI=F","ZB=F"],
            markets_data:        HashMap::new(),
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
            _ => self.available_instruments.clone(),
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
            (ExchangeTab::Options, _) => {
                let (state, len) = if self.options_show_calls {
                    let l = self.options_chain.iter().filter(|o| o.instrument.to_uppercase().contains("GFGC")).count();
                    (&mut self.options_chain_state, l)
                } else {
                    let l = self.options_chain.iter().filter(|o| o.instrument.to_uppercase().contains("GFGV")).count();
                    (&mut self.options_puts_state, l)
                };
                if len == 0 { return; }
                let cur = state.selected().unwrap_or(0) as i64;
                state.select(Some((cur + delta).clamp(0, len as i64 - 1) as usize));
                return;
            }
            (ExchangeTab::Futures, _) => (&mut self.futures_ticks_state, self.hist_ticks.len()),
            (ExchangeTab::News,    _) => {
                let len = self.news_items.len();
                if len == 0 { return; }
                let cur = self.news_state.selected().unwrap_or(0) as i64;
                self.news_state.select(Some((cur + delta).clamp(0, len as i64 - 1) as usize));
                return;
            }
            (ExchangeTab::Markets,   _) => { return; }
            (ExchangeTab::UsFutures, _) => { return; }
        };
        if len == 0 { return; }
        let cur = state.selected().unwrap_or(0) as i64;
        let next = (cur + delta).clamp(0, len as i64 - 1) as usize;
        state.select(Some(next));
    }

    fn selected_favorite(&self) -> Option<String> {
        self.favorites.get(self.fav_selected).cloned()
    }

    // ─── Black-Scholes math (pure Rust) ─────────────────────────────────

    fn norm_cdf(x: f64) -> f64 {
        0.5 * (1.0 + libm_erf(x / std::f64::consts::SQRT_2))
    }

    fn bs_price(s: f64, k: f64, t: f64, r: f64, sigma: f64, is_call: bool) -> f64 {
        if t <= 0.0 || sigma <= 0.0 { return 0.0; }
        let d1 = ((s / k).ln() + (r + 0.5 * sigma * sigma) * t) / (sigma * t.sqrt());
        let d2 = d1 - sigma * t.sqrt();
        if is_call {
            s * Self::norm_cdf(d1) - k * (-r * t).exp() * Self::norm_cdf(d2)
        } else {
            k * (-r * t).exp() * Self::norm_cdf(-d2) - s * Self::norm_cdf(-d1)
        }
    }

    /// Returns (delta, gamma, vega, theta, rho)
    fn bs_greeks(s: f64, k: f64, t: f64, r: f64, sigma: f64, is_call: bool) -> (f64, f64, f64, f64, f64) {
        if t <= 0.0 || sigma <= 0.0 { return (0.0, 0.0, 0.0, 0.0, 0.0); }
        let sqrt_t = t.sqrt();
        let d1 = ((s / k).ln() + (r + 0.5 * sigma * sigma) * t) / (sigma * sqrt_t);
        let d2 = d1 - sigma * sqrt_t;
        let pdf_d1 = (-0.5 * d1 * d1).exp() / (2.0 * std::f64::consts::PI).sqrt();
        let delta = if is_call { Self::norm_cdf(d1) } else { Self::norm_cdf(d1) - 1.0 };
        let gamma = pdf_d1 / (s * sigma * sqrt_t);
        let vega  = s * pdf_d1 * sqrt_t / 100.0;
        let theta = if is_call {
            (-s * pdf_d1 * sigma / (2.0 * sqrt_t) - r * k * (-r * t).exp() * Self::norm_cdf(d2)) / 365.0
        } else {
            (-s * pdf_d1 * sigma / (2.0 * sqrt_t) + r * k * (-r * t).exp() * Self::norm_cdf(-d2)) / 365.0
        };
        let rho = if is_call {
            k * t * (-r * t).exp() * Self::norm_cdf(d2) / 100.0
        } else {
            -k * t * (-r * t).exp() * Self::norm_cdf(-d2) / 100.0
        };
        (delta, gamma, vega, theta, rho)
    }

    fn implied_vol(market_price: f64, s: f64, k: f64, t: f64, r: f64, is_call: bool) -> f64 {
        if market_price <= 0.0 || t <= 0.0 { return f64::NAN; }
        // Reject prices below discounted intrinsic (stale/impossible)
        let intrinsic = if is_call { (s - k * (-r*t).exp()).max(0.0) } else { (k * (-r*t).exp() - s).max(0.0) };
        if market_price < intrinsic * 0.999 { return f64::NAN; }
        // Bisection — always converges, no divergence risk
        let mut lo = 1e-6_f64;
        let mut hi = 20.0_f64;
        if Self::bs_price(s, k, t, r, hi, is_call) < market_price { return f64::NAN; }
        for _ in 0..60 {
            let mid = (lo + hi) / 2.0;
            if Self::bs_price(s, k, t, r, mid, is_call) > market_price { hi = mid; } else { lo = mid; }
            if hi - lo < 1e-6 { break; }
        }
        (lo + hi) / 2.0
    }

    /// Parse strike price from GGAL option instrument name.
    /// e.g. "bm_MERV_GFGC69029A_24hs" → 6902.9  (digits / 10)
    fn parse_strike(instrument: &str) -> f64 {
        let digits: String = instrument.chars()
            .skip_while(|c| !c.is_ascii_digit())
            .take_while(|c| c.is_ascii_digit())
            .collect();
        let raw: f64 = digits.parse().unwrap_or(0.0);
        // BYMA encodes strike×10 in the ticker normally (e.g. 69029 → 6902.9)
        // Exception: 10000–19999 range is already the strike (ticker character overflow)
        if raw >= 10000.0 && raw < 20000.0 { raw } else { raw / 10.0 }
    }

    fn option_sort_key(instrument: &str) -> (u8, u64) {
        let series = instrument.chars()
            .skip_while(|c| !c.is_ascii_digit())
            .skip_while(|c| c.is_ascii_digit())
            .next().unwrap_or('Z') as u8;
        let strike = (Self::parse_strike(instrument) * 10.0) as u64;
        (series, strike)
    }

    /// Strip BYMA prefix/suffix for display: "M:bm_MERV_GFGC69573O_24hs" → "GFGC69573O"
    fn short_ticker(instrument: &str) -> String {
        instrument
            .trim_start_matches("M:")
            .trim_start_matches("bm_MERV_")
            .trim_end_matches("_24hs")
            .trim_end_matches("_48hs")
            .to_string()
    }

    fn parse_series_letter(instrument: &str) -> char {
        let mut chars = instrument.chars().peekable();
        while chars.peek().map(|c| !c.is_ascii_digit()).unwrap_or(false) { chars.next(); }
        chars.by_ref().take_while(|c| c.is_ascii_digit()).for_each(|_| {});
        chars.next().unwrap_or('?')
    }

    /// Parse expiry month from instrument suffix like "OCT25" → NaiveDate
    fn parse_expiry_days(instrument: &str) -> f64 {
        use chrono::{Datelike, NaiveDate, Utc};
        let months = [("JAN",1),("FEB",2),("MAR",3),("APR",4),("MAY",5),("JUN",6),
                      ("JUL",7),("AUG",8),("SEP",9),("OCT",10),("NOV",11),("DIC",12),("DEC",12)];
        let upper = instrument.to_uppercase();
        for (name, m) in &months {
            if let Some(pos) = upper.find(name) {
                let year_str = &upper[pos + 3..];
                let year_2d: u32 = year_str.chars().take(2).collect::<String>().parse().unwrap_or(25);
                let year = 2000 + year_2d;
                if let Some(expiry) = NaiveDate::from_ymd_opt(year as i32, *m, 1)
                    .and_then(|d| d.with_day(d.with_month(*m + 1).unwrap_or(d.with_month(1).unwrap().with_year(d.year() + 1).unwrap()).pred_opt().unwrap().day()))
                {
                    let today = Utc::now().date_naive();
                    let days = (expiry - today).num_days().max(1) as f64;
                    return days / 365.0;
                }
            }
        }
        30.0 / 365.0
    }

    // ─── Fetch triggers ──────────────────────────────────────────────────

    /// Returns the shared Arc<Client> or creates a fresh connection.
    /// Callers move the result into a `tokio::spawn` — it is `Send + Sync`.
    async fn get_db_client(shared: Option<Arc<tokio_postgres::Client>>) -> Option<Arc<tokio_postgres::Client>> {
        if let Some(c) = shared { return Some(c); }
        crate::db::connect_arc().await.ok()
    }

    fn trigger_merval_instruments_fetch(&mut self) {
        let Some(tx) = self.db_tx.clone() else { return };
        let client = self.db_client.clone();
        tokio::spawn(async move {
            if let Some(c) = Self::get_db_client(client).await {
                if let Ok(list) = crate::db::fetch_distinct_merval_instruments(&c, 90).await {
                    let _ = tx.send(DbMessage::MervalInstruments(list));
                }
            }
        });
    }


    /// Locate the repo root (one level up if running from tws_terminal/).
    fn project_root() -> std::path::PathBuf {
        let cwd = std::env::current_dir().unwrap_or_default();
        if !cwd.join("PPI").exists() && cwd.join("../PPI").exists() {
            cwd.parent().map(|p| p.to_path_buf()).unwrap_or(cwd)
        } else {
            cwd
        }
    }

    /// Fetch OHLCV from PPI via Python subprocess. Uses AUTO type to handle stocks, bonds, CEDEARs.
    fn trigger_ppi_ohlcv(&mut self, ticker: &str) {
        let Some(tx) = self.db_tx.clone() else { return };
        if self.merval_ohlcv_loading { return; }
        self.merval_ohlcv_loading = true;
        self.merval_ppi_ohlcv.clear();
        let ticker = ticker.to_string();
        tokio::spawn(async move {
            let root = Self::project_root();
            let python = root.join(".venv/bin/python3");
            let result = tokio::process::Command::new(&python)
                .args([
                    "-m", "PPI.fetch_ohlcv",
                    "--tickers", &ticker,
                    "--type", "AUTO",
                    "--output", "json"
                ])
                .current_dir(&root)
                .env("PYTHONPATH", &root)
                .stdin(std::process::Stdio::null())
                .output()
                .await;
            match result {
                Ok(out) if out.status.success() => {
                    match serde_json::from_slice::<Vec<crate::db::OhlcvBar>>(&out.stdout) {
                        Ok(bars) => { let _ = tx.send(DbMessage::MervalOhlcv(bars)); }
                        Err(e)   => {
                            eprintln!("[PPI OHLCV] JSON parse error: {e}");
                            let _ = tx.send(DbMessage::MervalOhlcv(vec![]));
                        }
                    }
                }
                Ok(out) => {
                    let err = String::from_utf8_lossy(&out.stderr);
                    eprintln!("[PPI OHLCV] fetch error: {}", err.lines().last().unwrap_or("unknown"));
                    let _ = tx.send(DbMessage::MervalOhlcv(vec![]));
                }
                Err(e) => {
                    eprintln!("[PPI OHLCV] subprocess error: {e}");
                    let _ = tx.send(DbMessage::MervalOhlcv(vec![]));
                }
            }
        });
    }

    fn trigger_options_fetch(&mut self) {
        let Some(tx) = self.db_tx.clone() else { return };
        if self.options_loading { return; }
        self.options_loading = true;
        let client = self.db_client.clone();
        tokio::spawn(async move {
            let Some(c) = Self::get_db_client(client).await else {
                let _ = tx.send(DbMessage::Error("DB connect failed".into()));
                return;
            };
            // Fetch spot price and options chain concurrently on a single connection
            let (spot_result, chain_result) = tokio::join!(
                crate::db::fetch_last_price(&c, "M:bm_MERV_GGAL_24hs"),
                crate::db::fetch_options_chain(&c),
            );
            if let Ok(spot) = spot_result { let _ = tx.send(DbMessage::GgalSpot(spot)); }
            match chain_result {
                Ok(rows) => { let _ = tx.send(DbMessage::OptionsChain(rows)); }
                Err(e)   => { let _ = tx.send(DbMessage::Error(format!("{e}"))); }
            }
        });
    }

    fn fetch_futures_ticks_for(&self, instrument: &str) {
        let Some(tx) = self.db_tx.clone() else { return };
        let instr = instrument.to_string();
        let client = self.db_client.clone();
        tokio::spawn(async move {
            if let Some(c) = Self::get_db_client(client).await {
                match crate::db::fetch_futures_ticks(&c, &instr, 200).await {
                    Ok(rows) => { let _ = tx.send(DbMessage::FuturesTicks(rows)); }
                    Err(e)   => { let _ = tx.send(DbMessage::Error(format!("{e}"))); }
                }
            }
        });
    }

    fn trigger_futures_fetch(&mut self) {
        let Some(tx) = self.db_tx.clone() else { return };
        let client = self.db_client.clone();
        tokio::spawn(async move {
            if let Some(c) = Self::get_db_client(client).await {
                match crate::db::fetch_futures_curve(&c).await {
                    Ok(rows) => { let _ = tx.send(DbMessage::FuturesCurve(rows)); }
                    Err(e)   => { let _ = tx.send(DbMessage::Error(format!("{e}"))); }
                }
            }
        });
    }

    fn trigger_news_fetch(&mut self) {
        let Some(tx) = self.db_tx.clone() else { return };
        if self.news_loading { return; }
        self.news_loading = true;
        let newsapi_key = std::env::var("NEWSAPI_KEY").unwrap_or_default();
        tokio::spawn(async move {
            use redis::AsyncCommands;
            const REDIS_URL: &str = "redis://100.112.16.115:6379";
            const CACHE_KEY: &str = "news:cache";

            // Check Redis cache first — avoids all external API calls when fresh
            if let Ok(rclient) = redis::Client::open(REDIS_URL) {
                if let Ok(mut conn) = rclient.get_async_connection().await {
                    let cached: redis::RedisResult<String> = conn.get(CACHE_KEY).await;
                    if let Ok(json_str) = cached {
                        if let Ok(items) = serde_json::from_str::<Vec<NewsItem>>(&json_str) {
                            if !items.is_empty() {
                                let _ = tx.send(DbMessage::News(items));
                                return;
                            }
                        }
                    }
                }
            }

            let mut items: Vec<NewsItem> = Vec::new();

            // ByMA relevant facts
            let byma_result = async {
                use chrono::{Duration, Utc};
                let now = Utc::now();
                let from = (now - Duration::days(7)).format("%Y-%m-%dT03:00:00.000Z").to_string();
                let to   = now.format("%Y-%m-%dT03:00:00.000Z").to_string();
                let body = serde_json::json!({
                    "filter": true,
                    "publishDateFrom": from,
                    "publishDateTo": to,
                    "texto": ""
                });
                let resp = reqwest::Client::builder()
                    .timeout(std::time::Duration::from_secs(10))
                    .danger_accept_invalid_certs(true)  // ByMA has cert issues
                    .build()?
                    .post("https://open.bymadata.com.ar/vanoms-be-core/rest/api/bymadata/free/bnown/relevant-facts")
                    .header("token", "dc826d4c2dde7519e882a250359a23a0")
                    .header("Content-Type", "application/json")
                    .json(&body)
                    .send().await?;
                let json: serde_json::Value = resp.json().await?;
                anyhow::Ok(json)
            }.await;

            if let Ok(json) = byma_result {
                let arr = json["data"].as_array()
                    .or_else(|| json.as_array());
                if let Some(arr) = arr {
                    for item in arr.iter().take(20) {
                        let time = item["fecha"].as_str()
                            .or_else(|| item["publishDate"].as_str())
                            .unwrap_or("").chars().take(16).collect();
                        let issuer = item["emisor"].as_str()
                            .or_else(|| item["issuerName"].as_str())
                            .unwrap_or("");
                        let desc = item["referencia"].as_str()
                            .or_else(|| item["description"].as_str())
                            .unwrap_or("").chars().take(80).collect::<String>();
                        // ByMA download link — open the public ByMA relevant facts search page
                        // (direct PDF download requires authenticated session, not possible from browser)
                        let issuer_encoded = item["emisor"].as_str().unwrap_or("")
                            .replace(' ', "+");
                        let url = if !issuer_encoded.is_empty() {
                            format!("https://open.bymadata.com.ar/#/hechos-relevantes?emisor={}", issuer_encoded)
                        } else {
                            "https://open.bymadata.com.ar/#/hechos-relevantes".to_string()
                        };
                        items.push(NewsItem {
                            time,
                            source:      "ByMA".to_string(),
                            headline:    format!("{} — {}", issuer, desc),
                            url,
                            description: String::new(), // ByMA has no body text
                        });
                    }
                }
            }

            // NewsAPI — top financial outlets, sorted by date
            if !newsapi_key.is_empty() {
                let url = format!(
                    "https://newsapi.org/v2/everything?domains=reuters.com,bloomberg.com,ft.com,wsj.com,marketwatch.com&language=en&sortBy=publishedAt&pageSize=20&apiKey={}",
                    newsapi_key
                );
                let result = reqwest::Client::builder()
                    .timeout(std::time::Duration::from_secs(10))
                    .user_agent("TWS-Terminal/1.0")
                    .build()
                    .ok()
                    .map(|c| c.get(&url).send());
                if let Some(fut) = result {
                    if let Ok(resp) = fut.await {
                        if let Ok(json) = resp.json::<serde_json::Value>().await {
                            if let Some(articles) = json["articles"].as_array() {
                                for a in articles {
                                    let source = a["source"]["name"].as_str().unwrap_or("News");
                                    items.push(NewsItem {
                                        time:        a["publishedAt"].as_str().unwrap_or("").chars().take(16).collect(),
                                        source:      source.to_string(),
                                        headline:    a["title"].as_str().unwrap_or("").chars().take(100).collect(),
                                        url:         a["url"].as_str().unwrap_or("").to_string(),
                                        description: a["description"].as_str().unwrap_or("").chars().take(400).collect(),
                                    });
                                }
                            }
                        }
                    }
                }
            }

            // Yahoo Finance RSS — 3 feeds in parallel
            let yf_client = reqwest::Client::builder()
                .timeout(std::time::Duration::from_secs(10))
                .user_agent("Mozilla/5.0")
                .build().unwrap();

            let feeds: &[(&str, &str)] = &[
                ("https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5EGSPC,%5EIXIC,%5EDJI&region=US&lang=en-US",
                 "Yahoo Global"),
                ("https://feeds.finance.yahoo.com/rss/2.0/headline?s=GGAL,YPF,SUPV,PAMP,BBAR&region=US&lang=en-US",
                 "Yahoo Argentina"),
                ("https://feeds.finance.yahoo.com/rss/2.0/headline?s=GGAL,YPF,SUPV,PAMP,BBAR,^MERV&region=US&lang=en-US",
                 "Yahoo Stocks"),
            ];

            let futures_vec: Vec<_> = feeds.iter().map(|(url, label)| {
                let client = yf_client.clone();
                let url = url.to_string();
                let label = label.to_string();
                async move {
                    let mut feed_items = Vec::new();
                    if let Ok(resp) = client.get(&url).send().await {
                        if let Ok(xml) = resp.text().await {
                            for chunk in xml.split("<item>").skip(1) {
                                let title = extract_xml_tag(chunk, "title");
                                let link  = extract_xml_tag(chunk, "link");
                                let date  = extract_xml_tag(chunk, "pubDate");
                                if !title.is_empty() {
                                    feed_items.push(NewsItem {
                                        time:        date.chars().take(25).collect(),
                                        source:      label.clone(),
                                        headline:    title.chars().take(100).collect(),
                                        url:         link,
                                        description: extract_xml_tag(chunk, "description").chars().take(400).collect(),
                                    });
                                }
                            }
                        }
                    }
                    feed_items
                }
            }).collect();

            let yf_results = futures_util::future::join_all(futures_vec).await;
            for feed_items in yf_results {
                items.extend(feed_items);
            }

            // Deduplicate by headline
            let mut seen = std::collections::HashSet::new();
            items.retain(|n| seen.insert(n.headline.clone()));

            items.sort_by(|a, b| b.time.cmp(&a.time));

            // Persist to Redis with 30-minute TTL so the next open is instant
            if !items.is_empty() {
                if let Ok(rclient) = redis::Client::open(REDIS_URL) {
                    if let Ok(mut conn) = rclient.get_async_connection().await {
                        if let Ok(json_str) = serde_json::to_string(&items) {
                            let _: redis::RedisResult<()> = conn.set_ex(CACHE_KEY, json_str, 1800).await;
                        }
                    }
                }
            }

            let _ = tx.send(DbMessage::News(items));
        });
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
            DbMessage::OptionsChain(rows)   => { self.options_chain = rows; self.options_loading = false; }
            DbMessage::GgalSpot(price)      => { self.ggal_spot = price; }
            DbMessage::FuturesCurve(rows)   => {
                self.futures_curve = rows;
                // Auto-fetch ticks for first contract
                if !self.futures_curve.is_empty() {
                    let instr = self.futures_curve[0].instrument.clone();
                    self.fetch_futures_ticks_for(&instr);
                }
            }
            DbMessage::FuturesTicks(rows)   => { self.futures_ticks = rows; self.futures_ticks_state = TableState::default(); }
            DbMessage::BinancePriceHistory(symbol, points) => {
                if let Some(data) = self.symbol_map.get_mut(&symbol) {
                    data.seed_history(points);
                }
            }
            DbMessage::MervalInstruments(list) => {
                self.merval_instruments = list;
                if self.merval_inst_list_state.selected().is_none() && !self.merval_instruments.is_empty() {
                    self.merval_inst_list_state.select(Some(0));
                }
            }
            DbMessage::MervalInstrumentOrders(_) => {}
            DbMessage::MervalOhlcv(bars) => {
                self.merval_ppi_ohlcv = bars;
                self.merval_ohlcv_loading = false;
            }
            DbMessage::News(items)          => { self.news_items = items; self.news_loading = false; }
            DbMessage::UsFuturesOhlcv(rows) => { self.us_futures_ohlcv = rows; }
            DbMessage::MarketsData(rows) => {
                self.markets_data.clear();
                for row in rows {
                    self.markets_data.insert(row.symbol.clone(), row);
                }
            }
            DbMessage::Error(e)             => self.hist_error = Some(e),
        }
    }

    /// Spawn a background task that queries all 4 tables concurrently and sends results back.
    fn trigger_historical_fetch(&mut self) {
        let Some(tx) = self.db_tx.clone() else { return };
        if self.hist_loading { return; }
        self.hist_loading = true;
        self.hist_error = None;

        let f = self.filter.filter.clone();
        let need_autocomplete = self.available_instruments.is_empty();
        let client = self.db_client.clone();

        tokio::spawn(async move {
            let Some(c) = Self::get_db_client(client).await else {
                let _ = tx.send(DbMessage::Error("DB connect failed".into()));
                return;
            };

            // Run all 4 data queries concurrently — tokio_postgres pipelines them
            let f2 = f.clone(); let f3 = f.clone(); let f4 = f.clone();
            let (r_ticks, r_orders, r_bticks, r_btrades) = tokio::join!(
                crate::db::fetch_ticks(&c, 200, &f),
                crate::db::fetch_orders(&c, 200, &f2),
                crate::db::fetch_binance_ticks(&c, 200, &f3),
                crate::db::fetch_binance_trades(&c, 200, &f4),
            );
            macro_rules! fwd { ($r:expr, $v:ident) => {
                match $r {
                    Ok(rows) => { let _ = tx.send(DbMessage::$v(rows)); }
                    Err(e)   => { let _ = tx.send(DbMessage::Error(format!("{e}"))); }
                }
            }}
            fwd!(r_ticks,   Ticks);
            fwd!(r_orders,  Orders);
            fwd!(r_bticks,  BinanceTicks);
            fwd!(r_btrades, BinanceTrades);

            if need_autocomplete {
                let (ri, rd, rb) = tokio::join!(
                    crate::db::fetch_distinct_instruments(&c),
                    crate::db::fetch_distinct_dates(&c),
                    crate::db::fetch_distinct_binance_symbols(&c),
                );
                fwd!(ri, Instruments);
                fwd!(rd, Dates);
                fwd!(rb, BinanceSymbols);
            }
        });
    }

    // ─── Message routing ────────────────────────────────────────────────

    pub fn handle_websocket_message(&mut self, msg: WebSocketMessage) {
        match msg {
            WebSocketMessage::TickUpdate(tick) => {
                let is_new = !self.symbol_map.contains_key(&tick.symbol);
                let data = self
                    .symbol_map
                    .entry(tick.symbol.clone())
                    .or_insert_with(|| BinanceSymbolData::new(&tick.symbol));
                data.update(tick.open, tick.high, tick.low, tick.close, tick.volume);

                // Seed historical price data on first tick for this symbol (reuses shared client)
                if is_new && !self.seeded_symbols.contains(&tick.symbol) {
                    self.seeded_symbols.insert(tick.symbol.clone());
                    if let Some(tx) = self.db_tx.clone() {
                        let symbol = tick.symbol.clone();
                        let client = self.db_client.clone();
                        tokio::spawn(async move {
                            if let Some(c) = Self::get_db_client(client).await {
                                if let Ok(points) = crate::db::fetch_binance_price_history(&c, &symbol, 3).await {
                                    let _ = tx.send(DbMessage::BinancePriceHistory(symbol, points));
                                }
                            }
                        });
                    }
                }

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
            WebSocketMessage::UsFuturesTick(tick) => {
                let entry = self.us_futures_live.entry(tick.symbol.clone()).or_insert((0.0, 0.0));
                entry.1 = entry.0;
                entry.0 = tick.last_price;
                // Append to live price history (capped at 500)
                let hist = self.us_futures_history.entry(tick.symbol.clone()).or_default();
                let i = hist.len() as f64;
                hist.push((i, tick.last_price));
                if hist.len() > 500 { hist.remove(0); }
            }
            WebSocketMessage::MatrizTick(tick) => {
                let entry = self.merval_live
                    .entry(tick.instrument.clone())
                    .or_insert_with(MervalLiveInstrument::new);
                entry.update(tick.last_price, tick.bid_price, tick.ask_price, tick.high, tick.low, tick.prev_close);

                if !self.merval_live_sorted.contains(&tick.instrument) {
                    self.merval_live_sorted.push(tick.instrument.clone());
                    self.merval_live_sorted.sort();
                    // Auto-select first row
                    if self.merval_live_state.selected().is_none() {
                        self.merval_live_state.select(Some(0));
                    }
                }
            }
            WebSocketMessage::MatrizOrder(order) => {
                // Push to live orders panel
                let side = if order.side == "B" { "BUY".to_string() } else { "SELL".to_string() };
                self.orders.push(Order::new(side, order.price, order.volume as u32, order.instrument));
                if self.orders.len() > 500 { self.orders.remove(0); }
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
                                if self.merval_instruments.is_empty() {
                                    self.trigger_merval_instruments_fetch();
                                }
                            }
                        }
                        ExchangeTab::UsFutures => {
                            self.us_futures_subtab = self.us_futures_subtab.toggle();
                            if self.us_futures_subtab == SubTab::Historical && self.us_futures_ohlcv.is_empty() {
                                self.trigger_us_futures_ohlcv();
                            }
                        }
                        _ => {}
                    }
                }

                crossterm::event::KeyCode::Char('t') => {}

                // [r] refresh on Options/Futures/News tabs
                crossterm::event::KeyCode::Char('r') => {                    match self.active_tab {
                        ExchangeTab::Options => { self.options_loading = false; self.trigger_options_fetch(); }
                        ExchangeTab::Futures => self.trigger_futures_fetch(),
                        ExchangeTab::News    => { self.news_loading = false; self.trigger_news_fetch(); }
                        _ => {}
                    }
                }

                // [c] toggle BS calculator on Options tab
                crossterm::event::KeyCode::Char('c') => {
                    if self.active_tab == ExchangeTab::Options {
                        self.calc_open = !self.calc_open;
                        if self.calc_open {
                            self.calc_iv.clear();
                            self.calc_result = None;
                            self.input_mode = InputMode::CalcEdit;
                        } else {
                            self.input_mode = InputMode::Normal;
                        }
                    }
                }

                // [Enter] on Options tab: load chain for selected underlying
                crossterm::event::KeyCode::Enter => {
                    if self.active_tab == ExchangeTab::Options {
                        self.options_loading = false;
                        self.trigger_options_fetch();
                    } else if self.active_tab == ExchangeTab::Merval && self.merval_subtab == SubTab::Historical {
                        if let Some(idx) = self.merval_inst_list_state.selected() {
                            if let Some(instr) = self.merval_instruments.get(idx).cloned() {
                                self.merval_ppi_ohlcv.clear();
                                self.merval_ohlcv_loading = false;
                                self.merval_selected_instr = Some(instr.clone());
                                let ticker = instr
                                    .trim_start_matches("M:bm_MERV_")
                                    .trim_end_matches("_24hs")
                                    .trim_end_matches("_48hs")
                                    .to_string();
                                self.trigger_ppi_ohlcv(&ticker);
                            }
                        }
                    } else if self.active_tab == ExchangeTab::News {
                        if let Some(idx) = self.news_state.selected() {
                            if let Some(item) = self.news_items.get(idx) {
                                if !item.url.is_empty() {
                                    let url = item.url.clone();
                                    tokio::spawn(async move {
                                        let _ = std::process::Command::new("xdg-open").arg(&url).spawn();
                                    });
                                }
                            }
                        }
                    }
                }

                // Number shortcuts: [1-5] switch main tabs; [1-4] switch MERVAL hist sub-tabs
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
                crossterm::event::KeyCode::Char('3') => {
                    if self.active_tab == ExchangeTab::Merval && self.merval_subtab == SubTab::Historical {
                        self.merval_hist_tab = MervalHistTab::Bonds;
                    } else {
                        self.active_tab = ExchangeTab::Options;
                        if self.options_chain.is_empty() { self.trigger_options_fetch(); }
                    }
                }
                crossterm::event::KeyCode::Char('4') => {
                    if self.active_tab == ExchangeTab::Merval && self.merval_subtab == SubTab::Historical {
                        self.merval_hist_tab = MervalHistTab::Favorites;
                    } else {
                        self.active_tab = ExchangeTab::Futures;
                        if self.futures_curve.is_empty() { self.trigger_futures_fetch(); }
                    }
                }
                crossterm::event::KeyCode::Char('5') => {
                    if self.active_tab != ExchangeTab::Merval || self.merval_subtab != SubTab::Historical {
                        self.active_tab = ExchangeTab::News;
                        if self.news_items.is_empty() { self.trigger_news_fetch(); }
                    }
                }
                crossterm::event::KeyCode::Char('6') => {
                    self.active_tab = ExchangeTab::Markets;
                    if self.markets_data.is_empty() { self.trigger_markets_fetch(); }
                }
                crossterm::event::KeyCode::Char('7') => {
                    self.active_tab = ExchangeTab::UsFutures;
                    self.trigger_us_futures_ohlcv();
                }

                crossterm::event::KeyCode::Right | crossterm::event::KeyCode::Tab => {
                    if self.active_tab == ExchangeTab::Options {
                        // Tab on Options: toggle calls/puts focus
                        self.options_show_calls = !self.options_show_calls;
                    } else if self.active_tab == ExchangeTab::Merval
                        && self.merval_subtab == SubTab::Historical
                        && self.merval_hist_tab == MervalHistTab::Favorites
                        && self.fav_selected + 1 < self.favorites.len()
                    {
                        self.fav_selected += 1;
                        self.fav_ticks_state  = TableState::default();
                        self.fav_orders_state = TableState::default();
                    } else if self.active_tab == ExchangeTab::Futures {
                        if self.futures_selected + 1 < self.futures_curve.len() {
                            self.futures_selected += 1;
                            self.futures_ticks_state = TableState::default();
                            let instr = self.futures_curve[self.futures_selected].instrument.clone();
                            self.fetch_futures_ticks_for(&instr);
                        }
                    } else if self.active_tab == ExchangeTab::UsFutures {
                        // handled by ↑↓
                    } else {
                        self.active_tab = match self.active_tab {
                            ExchangeTab::Binance   => ExchangeTab::Merval,
                            ExchangeTab::Merval    => ExchangeTab::Options,
                            ExchangeTab::Options   => ExchangeTab::Futures,
                            ExchangeTab::Futures   => ExchangeTab::News,
                            ExchangeTab::News      => ExchangeTab::Markets,
                            ExchangeTab::Markets   => ExchangeTab::UsFutures,
                            ExchangeTab::UsFutures => ExchangeTab::Binance,
                        };
                        self.on_tab_switch();
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
                    } else if self.active_tab == ExchangeTab::Futures && self.futures_selected > 0 {
                        self.futures_selected -= 1;
                        self.futures_ticks_state = TableState::default();
                        let instr = self.futures_curve[self.futures_selected].instrument.clone();
                        self.fetch_futures_ticks_for(&instr);
                    } else if self.active_tab == ExchangeTab::UsFutures && self.us_futures_selected > 0 {
                        // handled by ↑↓
                    } else {
                        self.active_tab = match self.active_tab {
                            ExchangeTab::Binance   => ExchangeTab::UsFutures,
                            ExchangeTab::Merval    => ExchangeTab::Binance,
                            ExchangeTab::Options   => ExchangeTab::Merval,
                            ExchangeTab::Futures   => ExchangeTab::Options,
                            ExchangeTab::News      => ExchangeTab::Futures,
                            ExchangeTab::Markets   => ExchangeTab::News,
                            ExchangeTab::UsFutures => ExchangeTab::Markets,
                        };
                        self.on_tab_switch();
                    }
                }

                // ↑↓ navigate
                crossterm::event::KeyCode::Up => {
                    match self.active_tab {
                        ExchangeTab::Options => {
                            let state = if self.options_show_calls { &mut self.options_chain_state } else { &mut self.options_puts_state };
                            let cur = state.selected().unwrap_or(0);
                            if cur > 0 { state.select(Some(cur - 1)); }
                        }
                        ExchangeTab::UsFutures => {
                            if self.us_futures_selected > 0 {
                                self.us_futures_selected -= 1;
                                self.us_futures_ohlcv.clear();
                                self.trigger_us_futures_ohlcv();
                            }
                        }
                        ExchangeTab::News | ExchangeTab::Futures => self.hist_scroll(-1),
                        _ => {
                            let subtab = match self.active_tab {
                                ExchangeTab::Binance => self.binance_subtab,
                                ExchangeTab::Merval  => self.merval_subtab,
                                _ => SubTab::RealTime,
                            };
                            if subtab == SubTab::Historical {
                                if self.active_tab == ExchangeTab::Merval {
                                    // Navigate instrument list
                                    let cur = self.merval_inst_list_state.selected().unwrap_or(0);
                                    if cur > 0 {
                                        self.merval_inst_list_state.select(Some(cur - 1));
                                    }
                                } else {
                                    self.hist_scroll(-1);
                                }
                            } else {
                                match self.active_tab {
                                    ExchangeTab::Binance => {
                                        let idx = self.selected_idx();
                                        if idx > 0 { self.selected_symbol = Some(self.symbols_by_volume[idx - 1].clone()); }
                                    }
                                    ExchangeTab::Merval => {
                                        let cur = self.merval_live_state.selected().unwrap_or(0);
                                        if cur > 0 {
                                            self.merval_live_state.select(Some(cur - 1));
                                        }
                                    }
                                    _ => {}
                                }
                            }
                        }
                    }
                }
                crossterm::event::KeyCode::Down => {
                    match self.active_tab {
                        ExchangeTab::Options => {
                            let (state, len) = if self.options_show_calls {
                                let l = self.options_chain.iter().filter(|o| o.instrument.to_uppercase().contains("GFGC")).count();
                                (&mut self.options_chain_state, l)
                            } else {
                                let l = self.options_chain.iter().filter(|o| o.instrument.to_uppercase().contains("GFGV")).count();
                                (&mut self.options_puts_state, l)
                            };
                            let cur = state.selected().unwrap_or(0);
                            if cur + 1 < len { state.select(Some(cur + 1)); }
                        }
                        ExchangeTab::UsFutures => {
                            if self.us_futures_selected + 1 < self.us_futures_symbols.len() {
                                self.us_futures_selected += 1;
                                self.us_futures_ohlcv.clear();
                                self.trigger_us_futures_ohlcv();
                            }
                        }
                        ExchangeTab::News | ExchangeTab::Futures => self.hist_scroll(1),
                        _ => {
                            let subtab = match self.active_tab {
                                ExchangeTab::Binance => self.binance_subtab,
                                ExchangeTab::Merval  => self.merval_subtab,
                                _ => SubTab::RealTime,
                            };
                            if subtab == SubTab::Historical {
                                if self.active_tab == ExchangeTab::Merval {
                                    let cur = self.merval_inst_list_state.selected().unwrap_or(0);
                                    if cur + 1 < self.merval_instruments.len() {
                                        self.merval_inst_list_state.select(Some(cur + 1));
                                    }
                                } else {
                                    self.hist_scroll(1);
                                }
                            } else {
                                match self.active_tab {
                                    ExchangeTab::Binance => {
                                        let idx = self.selected_idx();
                                        if idx < self.symbols_by_volume.len().saturating_sub(1) {
                                            self.selected_symbol = Some(self.symbols_by_volume[idx + 1].clone());
                                        }
                                    }
                                    ExchangeTab::Merval => {
                                        let cur = self.merval_live_state.selected().unwrap_or(0);
                                        if cur + 1 < self.merval_live_sorted.len() {
                                            self.merval_live_state.select(Some(cur + 1));
                                        }
                                    }
                                    _ => {}
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
                        _ => SubTab::RealTime,
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

                // Favorites: [a] add, [d] delete
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

            InputMode::CalcEdit => match event.code {
                crossterm::event::KeyCode::Enter => {
                    let iv = self.calc_iv.parse::<f64>().unwrap_or(0.0);
                    if iv > 0.0 {
                        let sel_opt = if self.options_show_calls {
                            let mut calls: Vec<&OptionRow> = self.options_chain.iter()
                                .filter(|o| o.instrument.to_uppercase().contains("GFGC")).collect();
                            calls.sort_by_key(|o| Self::option_sort_key(&o.instrument));
                            calls.get(self.options_chain_state.selected().unwrap_or(0)).map(|o| (*o).clone())
                        } else {
                            let mut puts: Vec<&OptionRow> = self.options_chain.iter()
                                .filter(|o| o.instrument.to_uppercase().contains("GFGV")).collect();
                            puts.sort_by_key(|o| Self::option_sort_key(&o.instrument));
                            puts.get(self.options_puts_state.selected().unwrap_or(0)).map(|o| (*o).clone())
                        };
                        if let Some(opt) = sel_opt {
                            let s = self.ggal_spot;
                            let k = Self::parse_strike(&opt.instrument);
                            let t = Self::parse_expiry_days(&opt.instrument);
                            let r = 0.05;
                            let is_call = opt.instrument.to_uppercase().contains("GFGC");
                            let price = Self::bs_price(s, k, t, r, iv, is_call);
                            let (delta, gamma, vega, theta, rho) = Self::bs_greeks(s, k, t, r, iv, is_call);
                            self.calc_result = Some((price, delta, gamma, vega, theta, rho));
                        }
                    }
                }
                crossterm::event::KeyCode::Char(c) => { self.calc_iv.push(c); }
                crossterm::event::KeyCode::Backspace => { self.calc_iv.pop(); }
                crossterm::event::KeyCode::Esc => {
                    self.input_mode = InputMode::Normal;
                    self.calc_open = false;
                }
                _ => {}
            },
        }
        true
    }

    fn on_tab_switch(&mut self) {
        match self.active_tab {
            ExchangeTab::Options   => { if self.options_chain.is_empty() { self.trigger_options_fetch(); } }
            ExchangeTab::Futures   => { if self.futures_curve.is_empty() { self.trigger_futures_fetch(); } }
            ExchangeTab::News      => { if self.news_items.is_empty() { self.trigger_news_fetch(); } }
            ExchangeTab::UsFutures => { self.trigger_us_futures_ohlcv(); }
            ExchangeTab::Markets   => { self.trigger_markets_fetch(); }
            _ => {}
        }
    }

    fn trigger_us_futures_ohlcv(&self) {
        let Some(tx) = self.db_tx.clone() else { return };
        let sym = self.us_futures_symbols[self.us_futures_selected].to_string();
        let client = self.db_client.clone();
        tokio::spawn(async move {
            if let Some(c) = Self::get_db_client(client).await {
                if let Ok(rows) = crate::db::fetch_us_futures_ohlcv(&c, &sym, 200).await {
                    let _ = tx.send(DbMessage::UsFuturesOhlcv(rows));
                }
            }
        });
    }

    fn trigger_markets_fetch(&self) {
        let Some(tx) = self.db_tx.clone() else { return };
        let client = self.db_client.clone();
        tokio::spawn(async move {
            if let Some(c) = Self::get_db_client(client).await {
                if let Ok(rows) = crate::db::fetch_markets_live(&c).await {
                    let _ = tx.send(DbMessage::MarketsData(rows));
                }
            }
        });
    }

    // ─── Top-level render ───────────────────────────────────────────────

    pub fn render(&mut self, frame: &mut Frame) {
        let active_subtab = match self.active_tab {
            ExchangeTab::Binance => self.binance_subtab,
            ExchangeTab::Merval  => self.merval_subtab,
            _                    => SubTab::RealTime,
        };
        let show_filter_bar = matches!(self.active_tab, ExchangeTab::Binance | ExchangeTab::Merval)
            && active_subtab == SubTab::Historical;

        // New tabs use a simple 3-chunk layout (tabs + main + controls)
        if matches!(self.active_tab, ExchangeTab::Options | ExchangeTab::Futures | ExchangeTab::News | ExchangeTab::Markets | ExchangeTab::UsFutures) {
            let chunks = Layout::default()
                .direction(Direction::Vertical)
                .constraints([Constraint::Length(3), Constraint::Min(0), Constraint::Length(3)])
                .split(frame.size());
            self.render_tabs(chunks[0], frame);
            match self.active_tab {
                ExchangeTab::Options   => self.render_options_tab(chunks[1], frame),
                ExchangeTab::Futures   => self.render_futures_tab(chunks[1], frame),
                ExchangeTab::News      => self.render_news_tab(chunks[1], frame),
                ExchangeTab::Markets   => self.render_markets_tab(chunks[1], frame),
                ExchangeTab::UsFutures => self.render_us_futures_tab(chunks[1], frame),
                _ => {}
            }
            self.render_input_area(chunks[2], frame);
            return;
        }

        let constraints = if show_filter_bar {
            vec![
                Constraint::Length(3),
                Constraint::Length(1),
                Constraint::Length(3),
                Constraint::Length(3),
                Constraint::Min(12),
                Constraint::Length(8),
                Constraint::Length(3),
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
            ExchangeTab::Merval  => self.merval_subtab,
            _                    => SubTab::RealTime,
        };
        let accent = match self.active_tab {
            ExchangeTab::Binance => Color::Yellow,
            _                    => Color::LightBlue,
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
        // Don't block on hist_loading — instrument list and chart have their own state
        // Combine top+bottom into one full rect for the right panel
        let full = Rect {
            x: top.x,
            y: top.y,
            width: top.width,
            height: top.height + bottom.height,
        };

        // Left: instrument list | Right: full height
        let h = Layout::default()
            .direction(Direction::Horizontal)
            .constraints([Constraint::Length(28), Constraint::Min(0)])
            .split(full);

        // ── Instrument list ──
        let items: Vec<ListItem> = self.merval_instruments.iter().map(|instr| {
            let short = instr.trim_start_matches("M:bm_MERV_").trim_end_matches("_24hs").trim_end_matches("_48hs");
            let selected = self.merval_selected_instr.as_deref() == Some(instr.as_str());
            let style = if selected {
                Style::default().fg(Color::Black).bg(Color::LightBlue).add_modifier(Modifier::BOLD)
            } else {
                Style::default().fg(Color::White)
            };
            ListItem::new(Span::styled(format!(" {} ", short), style))
        }).collect();
        let count = items.len();
        frame.render_stateful_widget(
            List::new(items)
                .highlight_style(Style::default().fg(Color::Black).bg(Color::Cyan).add_modifier(Modifier::BOLD))
                .highlight_symbol("▶ ")
                .block(Block::default().borders(Borders::ALL)
                    .title(format!(" Instruments ({}) [↑↓][Enter] ", count))),
            h[0],
            &mut self.merval_inst_list_state,
        );

        if let Some(ref instr) = self.merval_selected_instr.clone() {
            let short = instr.trim_start_matches("M:bm_MERV_").trim_end_matches("_24hs").trim_end_matches("_48hs");
            self.render_ppi_ohlcv_chart(h[1], frame, short);
        } else {
            frame.render_widget(
                Paragraph::new("  Select an instrument and press [Enter] to load chart")
                    .style(Style::default().fg(Color::DarkGray))
                    .block(Block::default().borders(Borders::ALL).title(" Chart ")),
                h[1],
            );
        }

    }

    /// Render PPI daily OHLCV chart (high/low band + close line + volume bars).
    fn render_ppi_ohlcv_chart(&self, area: Rect, frame: &mut Frame, short: &str) {
        if self.merval_ohlcv_loading && self.merval_ppi_ohlcv.is_empty() {
            frame.render_widget(
                Paragraph::new(format!("  Fetching PPI daily OHLCV for {}…", short))
                    .style(Style::default().fg(Color::Yellow))
                    .block(Block::default().borders(Borders::ALL)
                        .title(format!(" {} — PPI Daily OHLCV  ", short))),
                area,
            );
            return;
        }
        if self.merval_ppi_ohlcv.is_empty() {
            frame.render_widget(
                Paragraph::new("  No PPI OHLCV data — press [p] again or check credentials")
                    .style(Style::default().fg(Color::DarkGray))
                    .block(Block::default().borders(Borders::ALL)
                        .title(format!(" {} — PPI Daily OHLCV  ", short))),
                area,
            );
            return;
        }

        let bars = &self.merval_ppi_ohlcv;
        let n = bars.len();

        // Collect price series (indexed floats for Chart widget)
        let closes: Vec<(f64, f64)> = bars.iter().enumerate()
            .filter_map(|(i, b)| b.close.map(|c| (i as f64, c)))
            .collect();
        let highs: Vec<(f64, f64)> = bars.iter().enumerate()
            .filter_map(|(i, b)| b.high.map(|h| (i as f64, h)))
            .collect();
        let lows: Vec<(f64, f64)> = bars.iter().enumerate()
            .filter_map(|(i, b)| b.low.map(|l| (i as f64, l)))
            .collect();

        // Determine stats
        let all_prices: Vec<f64> = highs.iter().map(|p| p.1)
            .chain(lows.iter().map(|p| p.1)).collect();
        let p_min = all_prices.iter().cloned().fold(f64::MAX, f64::min);
        let p_max = all_prices.iter().cloned().fold(f64::MIN, f64::max);
        let pad = (p_max - p_min) * 0.06 + 0.01;

        let last_close = closes.last().map(|p| p.1).unwrap_or(0.0);
        let first_close = closes.first().map(|p| p.1).unwrap_or(last_close);
        let pct_chg = if first_close > 0.0 { (last_close - first_close) / first_close * 100.0 } else { 0.0 };
        let color = if last_close >= first_close { Color::Green } else { Color::Red };

        // Split: chart (top 80%) / volume (bottom 20%)
        let chunks = Layout::default()
            .direction(Direction::Vertical)
            .constraints([Constraint::Min(0), Constraint::Length(4)])
            .split(area);

        // ── Price chart (close line + high/low band) ──
        let dataset_close = Dataset::default()
            .name("close")
            .marker(symbols::Marker::Braille)
            .graph_type(GraphType::Line)
            .style(Style::default().fg(color))
            .data(&closes);
        let dataset_high = Dataset::default()
            .name("high")
            .marker(symbols::Marker::Dot)
            .graph_type(GraphType::Line)
            .style(Style::default().fg(Color::DarkGray))
            .data(&highs);
        let dataset_low = Dataset::default()
            .name("low")
            .marker(symbols::Marker::Dot)
            .graph_type(GraphType::Line)
            .style(Style::default().fg(Color::DarkGray))
            .data(&lows);

        // X-axis labels: first, middle, last date (trimmed to MM-DD to save space)
        let trim_date = |d: &str| d.get(5..).unwrap_or(d).to_string();
        let x_labels: Vec<Span> = {
            let mut v = vec![
                Span::styled(trim_date(&bars[0].date), Style::default().fg(Color::DarkGray)),
            ];
            if n > 2 {
                v.push(Span::styled(trim_date(&bars[n / 2].date), Style::default().fg(Color::DarkGray)));
            }
            v.push(Span::styled(trim_date(&bars[n - 1].date), Style::default().fg(Color::DarkGray)));
            v
        };

        let sign = if pct_chg >= 0.0 { "+" } else { "" };
        let chart = Chart::new(vec![dataset_close, dataset_high, dataset_low])
            .block(Block::default().borders(Borders::ALL).title(format!(
                " {} — PPI Daily ({} bars)  close {:.2}  {}{:.2}%  ",
                short, n, last_close, sign, pct_chg
            )))
            .x_axis(Axis::default().bounds([0.0, (n - 1) as f64]).labels(x_labels))
            .y_axis(Axis::default().bounds([p_min - pad, p_max + pad])
                .labels(vec![
                    Span::styled(format!("{:.2}", p_min), Style::default().fg(Color::DarkGray)),
                    Span::styled(format!("{:.2}", p_max), Style::default().fg(Color::DarkGray)),
                ]));
        frame.render_widget(chart, chunks[0]);

        // ── Volume sparkline ──
        let vols: Vec<u64> = bars.iter()
            .map(|b| b.volume.unwrap_or(0.0) as u64)
            .collect();
        let max_vol = vols.iter().cloned().max().unwrap_or(1);
        let vol_label = if max_vol >= 1_000_000 {
            format!("max {:.1}M", max_vol as f64 / 1_000_000.0)
        } else if max_vol >= 1_000 {
            format!("max {:.0}K", max_vol as f64 / 1_000.0)
        } else {
            format!("max {max_vol}")
        };
        frame.render_widget(
            Sparkline::default()
                .block(Block::default().borders(Borders::ALL)
                    .title(format!(" Volume ({vol_label}) ")))
                .data(&vols)
                .max(max_vol)
                .style(Style::default().fg(Color::Blue)),
            chunks[1],
        );
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

    // ─── Options tab ────────────────────────────────────────────────────

    fn render_options_tab(&mut self, area: Rect, frame: &mut Frame) {
        let constraints = if self.calc_open {
            vec![Constraint::Percentage(45), Constraint::Percentage(45), Constraint::Length(32)]
        } else {
            vec![Constraint::Percentage(50), Constraint::Percentage(50)]
        };
        let h = Layout::default()
            .direction(Direction::Horizontal)
            .constraints(constraints)
            .split(area);

        let spot = self.ggal_spot;
        let r_rate = 0.05_f64;
        let spot_label = if spot > 0.0 { format!("GGAL {:.2}", spot) } else { "GGAL loading…".to_string() };

        if self.options_loading {
            let p = Paragraph::new("  Loading GGAL options (GFGC/GFGV)…  [r] refresh")
                .block(Block::default().borders(Borders::ALL).title(" Options "));
            frame.render_widget(p, h[0]);
            return;
        }
        if self.options_chain.is_empty() {
            let p = Paragraph::new("  No data — press [Enter] or [r] to load")
                .style(Style::default().fg(Color::DarkGray))
                .block(Block::default().borders(Borders::ALL).title(" GGAL Options "));
            frame.render_widget(p, h[0]);
            return;
        }

        // Sort helper closure
        let compute_row = |opt: &OptionRow, is_call: bool| -> ratatui::widgets::Row<'static> {
            let k = Self::parse_strike(&opt.instrument);
            let t = 30.0 / 365.0; // fixed 30-day assumption (expiry not parseable from ticker)
            let s = if spot > 0.0 { spot } else { k };
            // Use bid/ask midpoint as market price — current live quote, not stale last trade
            let mid = (opt.bid + opt.ask) / 2.0;
            let intrinsic = if is_call { (s - k * (-r_rate * t).exp()).max(0.0) }
                            else       { (k * (-r_rate * t).exp() - s).max(0.0) };
            // If midpoint is below intrinsic (stale/crossed LOB), use ask; if still below, use intrinsic floor
            let market_price = if mid >= intrinsic { mid }
                               else if opt.ask >= intrinsic { opt.ask }
                               else { intrinsic * 1.001 };
            let iv = if market_price > 0.0 && k > 0.0 && s > 0.0 {
                Self::implied_vol(market_price, s, k, t, r_rate, is_call)
            } else { f64::NAN };
            let (delta, _gamma, vega_v, theta, _) = if iv.is_finite() {
                Self::bs_greeks(s, k, t, r_rate, iv, is_call)
            } else { (f64::NAN, f64::NAN, f64::NAN, f64::NAN, f64::NAN) };
            let fmt = |v: f64| if v.is_finite() { format!("{:.3}", v) } else { "—".to_string() };
            let ticker = Self::short_ticker(&opt.instrument);
            ratatui::widgets::Row::new(vec![
                ticker,
                if k > 0.0 { format!("{:.0}", k) } else { "—".to_string() },
                format!("{:.2}", opt.last_price),
                format!("{:.2}", opt.bid),
                format!("{:.2}", opt.ask),
                if iv.is_finite() { format!("{:.1}", iv * 100.0) } else { "—".to_string() },
                fmt(delta), fmt(theta), fmt(vega_v),
            ])
        };

        let header = ratatui::widgets::Row::new(vec!["Ticker","Strike","Last","Bid","Ask","IV%","Δ","Θ","Vega"])
            .style(Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD));
        let col_w = [
            Constraint::Length(14), Constraint::Length(8),
            Constraint::Length(8), Constraint::Length(8), Constraint::Length(8),
            Constraint::Length(6), Constraint::Length(7), Constraint::Length(7), Constraint::Length(7),
        ];

        // Calls (GFGC) — sorted by month then strike
        let mut calls: Vec<&OptionRow> = self.options_chain.iter()
            .filter(|o| o.instrument.to_uppercase().contains("GFGC"))
            .collect();
        calls.sort_by_key(|o| Self::option_sort_key(&o.instrument));
        let call_rows: Vec<ratatui::widgets::Row> = calls.iter()
            .map(|o| compute_row(o, true).style(Style::default().fg(Color::Green)))
            .collect();
        let calls_focused = self.options_show_calls;
        let calls_table = Table::new(call_rows, col_w)
            .header(header.clone())
            .highlight_style(Style::default().fg(Color::Black).bg(Color::Green).add_modifier(Modifier::BOLD))
            .highlight_symbol(if calls_focused { "▶ " } else { "  " })
            .block(Block::default().borders(Borders::ALL)
                .title(format!(" Calls GFGC ({}) — {} ", calls.len(), spot_label))
                .border_style(if calls_focused { Style::default().fg(Color::Green) } else { Style::default() }));
        frame.render_stateful_widget(calls_table, h[0], &mut self.options_chain_state);

        // Puts (GFGV) — sorted by month then strike
        let mut puts: Vec<&OptionRow> = self.options_chain.iter()
            .filter(|o| o.instrument.to_uppercase().contains("GFGV"))
            .collect();
        puts.sort_by_key(|o| Self::option_sort_key(&o.instrument));
        let put_rows: Vec<ratatui::widgets::Row> = puts.iter()
            .map(|o| compute_row(o, false).style(Style::default().fg(Color::Red)))
            .collect();
        let puts_focused = !self.options_show_calls;
        let puts_table = Table::new(put_rows, col_w)
            .header(header)
            .highlight_style(Style::default().fg(Color::Black).bg(Color::Red).add_modifier(Modifier::BOLD))
            .highlight_symbol(if puts_focused { "▶ " } else { "  " })
            .block(Block::default().borders(Borders::ALL)
                .title(format!(" Puts GFGV ({}) ", puts.len()))
                .border_style(if puts_focused { Style::default().fg(Color::Red) } else { Style::default() }));
        frame.render_stateful_widget(puts_table, h[1], &mut self.options_puts_state);

        // Right: BS calculator — enter IV, get Greeks for selected row
        if self.calc_open && h.len() > 2 {
            // Get selected option from the focused panel
            let sel_opt = if self.options_show_calls {
                let mut calls: Vec<&OptionRow> = self.options_chain.iter()
                    .filter(|o| o.instrument.to_uppercase().contains("GFGC")).collect();
                calls.sort_by_key(|o| Self::option_sort_key(&o.instrument));
                calls.get(self.options_chain_state.selected().unwrap_or(0)).map(|o| (*o).clone())
            } else {
                let mut puts: Vec<&OptionRow> = self.options_chain.iter()
                    .filter(|o| o.instrument.to_uppercase().contains("GFGV")).collect();
                puts.sort_by_key(|o| Self::option_sort_key(&o.instrument));
                puts.get(self.options_puts_state.selected().unwrap_or(0)).map(|o| (*o).clone())
            };
            let mut lines: Vec<Line> = Vec::new();

            if let Some(ref opt) = sel_opt {
                let k = Self::parse_strike(&opt.instrument);
                let t_days = Self::parse_expiry_days(&opt.instrument) * 365.0;
                lines.push(Line::from(vec![
                    Span::styled("Instrument: ", Style::default().fg(Color::DarkGray)),
                    Span::styled(opt.instrument.clone(), Style::default().fg(Color::White)),
                ]));
                lines.push(Line::from(vec![
                    Span::styled("Spot (S):   ", Style::default().fg(Color::DarkGray)),
                    Span::styled(format!("{:.2}", self.ggal_spot), Style::default().fg(Color::Cyan)),
                ]));
                lines.push(Line::from(vec![
                    Span::styled("Strike (K): ", Style::default().fg(Color::DarkGray)),
                    Span::styled(format!("{:.0}", k), Style::default().fg(Color::White)),
                ]));
                lines.push(Line::from(vec![
                    Span::styled("T (days):   ", Style::default().fg(Color::DarkGray)),
                    Span::styled(format!("{:.0}", t_days), Style::default().fg(Color::White)),
                ]));
                lines.push(Line::from(vec![
                    Span::styled("Last price: ", Style::default().fg(Color::DarkGray)),
                    Span::styled(format!("{:.2}", opt.last_price), Style::default().fg(Color::White)),
                ]));
            }

            lines.push(Line::from(""));
            let iv_style = if self.input_mode == InputMode::CalcEdit {
                Style::default().fg(Color::Black).bg(Color::Green).add_modifier(Modifier::BOLD)
            } else {
                Style::default().fg(Color::Yellow)
            };
            lines.push(Line::from(vec![
                Span::styled("IV (σ):     ", Style::default().fg(Color::DarkGray)),
                Span::styled(
                    format!("{}_", self.calc_iv),
                    iv_style,
                ),
            ]));
            lines.push(Line::from(Span::styled(
                "e.g. 0.45 = 45%",
                Style::default().fg(Color::DarkGray),
            )));

            if let Some((price, delta, gamma, vega, theta, rho)) = self.calc_result {
                lines.push(Line::from(""));
                lines.push(Line::from(Span::styled(format!("Price : {:.4}", price), Style::default().fg(Color::Cyan).add_modifier(Modifier::BOLD))));
                lines.push(Line::from(format!("Δ     : {:.4}", delta)));
                lines.push(Line::from(format!("Γ     : {:.6}", gamma)));
                lines.push(Line::from(format!("Θ     : {:.4}", theta)));
                lines.push(Line::from(format!("Vega  : {:.4}", vega)));
                lines.push(Line::from(format!("Rho   : {:.4}", rho)));
            }

            frame.render_widget(
                Paragraph::new(lines).block(Block::default().borders(Borders::ALL)
                    .title(" Greeks Calculator — enter IV [Enter] compute [Esc] close ")
                    .border_style(Style::default().fg(Color::Green))),
                h[2],
            );
        }
    }

    // ─── Futures tab ─────────────────────────────────────────────────────

    fn render_futures_tab(&mut self, area: Rect, frame: &mut Frame) {
        let v = Layout::default()
            .direction(Direction::Vertical)
            .constraints([Constraint::Length(10), Constraint::Min(0)])
            .split(area);

        // Term structure chart
        if self.futures_curve.is_empty() {
            frame.render_widget(
                Paragraph::new("  Loading futures curve… [r] refresh")
                    .block(Block::default().borders(Borders::ALL).title(" DLR Futures Curve ")),
                v[0],
            );
        } else {
            let curve = &self.futures_curve;
            let sel = self.futures_selected.min(curve.len() - 1);

            // Build (x, price) points — x = contract index
            let points: Vec<(f64, f64)> = curve.iter().enumerate()
                .map(|(i, r)| (i as f64, r.last_price))
                .collect();

            let prices: Vec<f64> = curve.iter().map(|r| r.last_price).collect();
            let min = prices.iter().cloned().fold(f64::MAX, f64::min);
            let max = prices.iter().cloned().fold(f64::MIN, f64::max);
            let padding = (max - min) * 0.1 + 1.0;

            // X-axis labels = contract month names
            let x_labels: Vec<Span> = curve.iter().map(|r| {
                let label = r.instrument.split('_').last().unwrap_or(&r.instrument);
                Span::raw(label.to_string())
            }).collect();

            // Highlight selected contract with a dot dataset
            let selected_point = vec![(sel as f64, curve[sel].last_price)];

            let datasets = vec![
                Dataset::default()
                    .name("DLR Futures")
                    .marker(symbols::Marker::Braille)
                    .graph_type(GraphType::Line)
                    .style(Style::default().fg(Color::Magenta))
                    .data(&points),
                Dataset::default()
                    .marker(symbols::Marker::Block)
                    .style(Style::default().fg(Color::Yellow))
                    .data(&selected_point),
            ];

            let chart = Chart::new(datasets)
                .block(Block::default().borders(Borders::ALL)
                    .title(format!(" DLR Term Structure — {} selected  [←→] switch ", curve[sel].instrument)))
                .x_axis(Axis::default()
                    .bounds([0.0, (curve.len() - 1) as f64])
                    .labels(x_labels))
                .y_axis(Axis::default()
                    .bounds([min - padding, max + padding])
                    .labels(vec![
                        Span::styled(format!("{:.0}", min - padding), Style::default().fg(Color::DarkGray)),
                        Span::styled(format!("{:.0}", (min + max) / 2.0), Style::default().fg(Color::DarkGray)),
                        Span::styled(format!("{:.0}", max + padding), Style::default().fg(Color::DarkGray)),
                    ]));

            frame.render_widget(chart, v[0]);
        }

        // Tick table for selected contract
        if !self.futures_curve.is_empty() {
            let sel = self.futures_selected.min(self.futures_curve.len() - 1);
            let instr = self.futures_curve[sel].instrument.clone();
            let header = ratatui::widgets::Row::new(vec!["Time","Bid","Ask","Last","Volume"])
                .style(Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD));
            let rows: Vec<ratatui::widgets::Row> = self.futures_ticks.iter()
                .map(|r| ratatui::widgets::Row::new(vec![
                    r.time.format("%H:%M:%S").to_string(),
                    format!("{:.2}", r.bid_price),
                    format!("{:.2}", r.ask_price),
                    format!("{:.2}", r.last_price),
                    r.total_volume.to_string(),
                ]).style(Style::default().fg(Color::White)))
                .collect();
            let table = Table::new(rows, [
                Constraint::Length(10), Constraint::Length(10),
                Constraint::Length(10), Constraint::Length(10), Constraint::Length(12),
            ])
            .header(header)
            .highlight_style(Style::default().fg(Color::Black).bg(Color::Magenta).add_modifier(Modifier::BOLD))
            .block(Block::default().borders(Borders::ALL).title(format!(" {} Ticks [↑↓] scroll ", instr)));
            frame.render_stateful_widget(table, v[1], &mut self.futures_ticks_state);
        }
    }

    // ─── News tab ────────────────────────────────────────────────────────

    fn render_news_tab(&mut self, area: Rect, frame: &mut Frame) {
        if self.news_loading {
            frame.render_widget(
                Paragraph::new("  Fetching news from ByMA, NewsAPI and Yahoo Finance…")
                    .block(Block::default().borders(Borders::ALL).title(" News ")),
                area,
            );
            return;
        }
        if self.news_items.is_empty() {
            frame.render_widget(
                Paragraph::new("  No news loaded — press [r] to fetch")
                    .style(Style::default().fg(Color::DarkGray))
                    .block(Block::default().borders(Borders::ALL).title(" News ")),
                area,
            );
            return;
        }

        // Split: list on top, detail panel on bottom
        let v = Layout::default()
            .direction(Direction::Vertical)
            .constraints([Constraint::Min(5), Constraint::Length(8)])
            .split(area);

        // List
        let items: Vec<ListItem> = self.news_items.iter().map(|n| {
            let (badge, color) = if n.source == "ByMA" {
                ("[ByMA]          ", Color::Cyan)
            } else if n.source == "Yahoo Global" {
                ("[Yahoo Global]  ", Color::Yellow)
            } else if n.source == "Yahoo Argentina" {
                ("[Yahoo Argentina]", Color::LightBlue)
            } else if n.source == "Yahoo Stocks" {
                ("[Yahoo Stocks]  ", Color::Magenta)
            } else {
                // Reuters, Bloomberg, FT, WSJ, MarketWatch
                ("[Financial News]", Color::Green)
            };
            let has_url = !n.url.is_empty();
            ListItem::new(Line::from(vec![
                Span::styled(badge, Style::default().fg(color).add_modifier(Modifier::BOLD)),
                Span::styled(format!(" {} ", n.time), Style::default().fg(Color::DarkGray)),
                Span::styled(n.headline.clone(), Style::default().fg(Color::White)),
                if has_url { Span::styled(" [↵]", Style::default().fg(Color::DarkGray)) }
                else       { Span::raw("") },
            ]))
        }).collect();
        let count = items.len();
        frame.render_stateful_widget(
            List::new(items)
                .highlight_style(Style::default().fg(Color::Black).bg(Color::Cyan).add_modifier(Modifier::BOLD))
                .block(Block::default().borders(Borders::ALL)
                    .title(format!(" News ({}) [↑↓] scroll  [Enter] open  [r] refresh ", count))),
            v[0],
            &mut self.news_state,
        );

        // Detail panel — show description of selected item
        let detail = if let Some(idx) = self.news_state.selected() {
            self.news_items.get(idx).map(|n| {
                let body = if n.description.is_empty() {
                    format!("  {}\n\n  URL: {}", n.headline, n.url)
                } else {
                    format!("  {}\n\n  {}", n.headline, n.description)
                };
                (body, n.source.clone())
            })
        } else {
            None
        };

        if let Some((body, source)) = detail {
            let color = if source == "ByMA" { Color::Cyan }
                        else if source == "Yahoo Global" { Color::Yellow }
                        else if source == "Yahoo Argentina" { Color::LightBlue }
                        else if source == "Yahoo Stocks" { Color::Magenta }
                        else { Color::White };
            frame.render_widget(
                Paragraph::new(body)
                    .wrap(ratatui::widgets::Wrap { trim: true })
                    .style(Style::default().fg(Color::White))
                    .block(Block::default().borders(Borders::ALL)
                        .title(format!(" {} — Article Summary ", source))
                        .border_style(Style::default().fg(color))),
                v[1],
            );
        } else {
            frame.render_widget(
                Paragraph::new("  Select an item to see summary")
                    .style(Style::default().fg(Color::DarkGray))
                    .block(Block::default().borders(Borders::ALL).title(" Article Summary ")),
                v[1],
            );
        }
    }

    // ─── US Futures tab ──────────────────────────────────────────────────

    fn us_futures_name(sym: &str) -> &'static str {
        match sym {
            "ES=F" => "S&P 500",
            "NQ=F" => "Nasdaq 100",
            "YM=F" => "Dow Jones",
            "CL=F" => "Crude Oil WTI",
            "GC=F" => "Gold",
            "SI=F" => "Silver",
            "ZB=F" => "US 30Y Bond",
            _      => "",
        }
    }

    fn render_us_futures_tab(&mut self, area: Rect, frame: &mut Frame) {
        // Sub-tab bar
        let v = Layout::default()
            .direction(Direction::Vertical)
            .constraints([Constraint::Length(1), Constraint::Min(0)])
            .split(area);

        // Render sub-tab indicator
        let rt_style = if self.us_futures_subtab == SubTab::RealTime {
            Style::default().fg(Color::Black).bg(Color::LightRed).add_modifier(Modifier::BOLD)
        } else { Style::default().fg(Color::DarkGray) };
        let hist_style = if self.us_futures_subtab == SubTab::Historical {
            Style::default().fg(Color::Black).bg(Color::LightRed).add_modifier(Modifier::BOLD)
        } else { Style::default().fg(Color::DarkGray) };
        frame.render_widget(Paragraph::new(Line::from(vec![
            Span::raw(" "),
            Span::styled(" Real-Time ", rt_style),
            Span::raw(" "),
            Span::styled(" Historical ", hist_style),
        ])), v[0]);

        match self.us_futures_subtab {
            SubTab::RealTime   => self.render_us_futures_realtime(v[1], frame),
            SubTab::Historical => self.render_us_futures_historical(v[1], frame),
        }
    }

    fn render_us_futures_symbol_list(&self, area: Rect, frame: &mut Frame) {
        let items: Vec<ListItem> = self.us_futures_symbols.iter().enumerate().map(|(i, &sym)| {
            let (price, prev) = self.us_futures_live.get(sym).copied().unwrap_or((0.0, 0.0));
            let selected = i == self.us_futures_selected;
            let chg_color = if price >= prev { Color::Green } else { Color::Red };
            let base = if selected {
                Style::default().fg(Color::Black).bg(Color::LightRed).add_modifier(Modifier::BOLD)
            } else { Style::default() };
            let name = Self::us_futures_name(sym);
            ListItem::new(Line::from(vec![
                Span::styled(format!(" {:<7}", sym), base),
                Span::styled(
                    if price > 0.0 { format!("{:>10.2}", price) } else { "      --".to_string() },
                    if selected { base } else { Style::default().fg(chg_color) },
                ),
                Span::styled(format!(" {}", name), if selected { base } else { Style::default().fg(Color::DarkGray) }),
            ]))
        }).collect();
        frame.render_widget(
            List::new(items)
                .highlight_style(Style::default().fg(Color::Black).bg(Color::LightRed).add_modifier(Modifier::BOLD))
                .block(Block::default().borders(Borders::ALL).title(" US Futures [↑↓] [s] toggle ")),
            area,
        );
    }

    fn render_us_futures_realtime(&mut self, area: Rect, frame: &mut Frame) {
        let h = Layout::default()
            .direction(Direction::Horizontal)
            .constraints([Constraint::Length(30), Constraint::Min(0)])
            .split(area);

        self.render_us_futures_symbol_list(h[0], frame);

        let sym = self.us_futures_symbols[self.us_futures_selected];
        let (live_price, prev_price) = self.us_futures_live.get(sym).copied().unwrap_or((0.0, 0.0));

        if let Some(hist) = self.us_futures_history.get(sym) {
            if !hist.is_empty() {
                let prices: Vec<f64> = hist.iter().map(|p| p.1).collect();
                let min = prices.iter().cloned().fold(f64::MAX, f64::min);
                let max = prices.iter().cloned().fold(f64::MIN, f64::max);
                let pad = (max - min) * 0.05 + 0.01;
                let n = hist.len() as f64;
                let color = if live_price >= prev_price { Color::Green } else { Color::Red };
                let chg = if prev_price > 0.0 { (live_price - prev_price) / prev_price * 100.0 } else { 0.0 };

                let dataset = Dataset::default()
                    .marker(symbols::Marker::Braille)
                    .graph_type(GraphType::Line)
                    .style(Style::default().fg(color))
                    .data(hist);

                let chart = Chart::new(vec![dataset])
                    .block(Block::default().borders(Borders::ALL)
                        .title(format!(" {} — {} — {:.2}  {:+.3}% ", sym, Self::us_futures_name(sym), live_price, chg)))
                    .x_axis(Axis::default().bounds([0.0, n])
                        .labels(vec![Span::raw("oldest"), Span::raw("latest")]))
                    .y_axis(Axis::default().bounds([min - pad, max + pad])
                        .labels(vec![
                            Span::styled(format!("{:.2}", min), Style::default().fg(Color::DarkGray)),
                            Span::styled(format!("{:.2}", max), Style::default().fg(Color::DarkGray)),
                        ]));
                frame.render_widget(chart, h[1]);
                return;
            }
        }
        frame.render_widget(
            Paragraph::new(format!("  Waiting for live {} data…", sym))
                .style(Style::default().fg(Color::DarkGray))
                .block(Block::default().borders(Borders::ALL).title(format!(" {} Real-Time ", sym))),
            h[1],
        );
    }

    fn render_us_futures_historical(&mut self, area: Rect, frame: &mut Frame) {
        let h = Layout::default()
            .direction(Direction::Horizontal)
            .constraints([Constraint::Length(30), Constraint::Min(0)])
            .split(area);

        self.render_us_futures_symbol_list(h[0], frame);

        let sym = self.us_futures_symbols[self.us_futures_selected];
        let (live_price, _) = self.us_futures_live.get(sym).copied().unwrap_or((0.0, 0.0));

        if self.us_futures_ohlcv.is_empty() {
            frame.render_widget(
                Paragraph::new(format!("  Loading {} OHLCV… [r] refresh", sym))
                    .block(Block::default().borders(Borders::ALL).title(format!(" {} Historical ", sym))),
                h[1],
            );
            return;
        }

        let ohlcv = &self.us_futures_ohlcv;
        let points: Vec<(f64, f64)> = ohlcv.iter().enumerate().map(|(i, r)| (i as f64, r.close)).collect();
        let prices: Vec<f64> = ohlcv.iter().map(|r| r.close).collect();
        let min = prices.iter().cloned().fold(f64::MAX, f64::min);
        let max = prices.iter().cloned().fold(f64::MIN, f64::max);
        let pad = (max - min) * 0.05 + 0.01;
        let n = points.len() as f64;
        let color = if prices.last().unwrap_or(&0.0) >= prices.first().unwrap_or(&0.0) { Color::Green } else { Color::Red };
        let live_str = if live_price > 0.0 { format!("  Live: {:.2}", live_price) } else { String::new() };

        let tz = chrono::FixedOffset::west_opt(5 * 3600).unwrap();
        let x_labels: Vec<Span> = if ohlcv.len() >= 2 {
            let mid = ohlcv.len() / 2;
            vec![
                Span::styled(ohlcv[0].time.with_timezone(&tz).format("%m/%d %H:%M").to_string(), Style::default().fg(Color::DarkGray)),
                Span::styled(ohlcv[mid].time.with_timezone(&tz).format("%m/%d %H:%M").to_string(), Style::default().fg(Color::DarkGray)),
                Span::styled(ohlcv.last().unwrap().time.with_timezone(&tz).format("%m/%d %H:%M").to_string(), Style::default().fg(Color::DarkGray)),
            ]
        } else { vec![] };

        let dataset = Dataset::default()
            .marker(symbols::Marker::Braille)
            .graph_type(GraphType::Line)
            .style(Style::default().fg(color))
            .data(&points);

        let chart = Chart::new(vec![dataset])
            .block(Block::default().borders(Borders::ALL)
                .title(format!(" {} — {} — {} candles (ET){} ", sym, Self::us_futures_name(sym), ohlcv.len(), live_str)))
            .x_axis(Axis::default().bounds([0.0, n]).labels(x_labels))
            .y_axis(Axis::default().bounds([min - pad, max + pad])
                .labels(vec![
                    Span::styled(format!("{:.2}", min), Style::default().fg(Color::DarkGray)),
                    Span::styled(format!("{:.2}", max), Style::default().fg(Color::DarkGray)),
                ]));
        frame.render_widget(chart, h[1]);
    }

    // ─── Markets tab ─────────────────────────────────────────────────────

    fn render_markets_tab(&self, area: Rect, frame: &mut Frame) {
        use chrono::{Timelike, Utc, Weekday, Datelike};

        let now = Utc::now();
        let weekday = now.weekday();
        let is_weekend = weekday == Weekday::Sat || weekday == Weekday::Sun;

        // (name, lon, lat, open_h_local, close_h_local, tz_offset_hours)
        let markets: &[(&str, f64, f64, u32, u32, i32)] = &[
            ("NYSE/NASDAQ",  -74.0,  40.7,  9,  16, -5),
            ("Argentina",    -58.4, -34.6, 11,  17, -3),
            ("Brazil",       -43.2, -22.9, 10,  17, -3),
            ("London",        -0.1,  51.5,  8,  16,  0),
            ("Frankfurt",      8.7,  50.1,  9,  17,  1),
            ("Paris",          2.3,  48.9,  9,  17,  1),
            ("Madrid",        -3.7,  40.4,  9,  17,  1),
            ("Milan",          9.2,  45.5,  9,  17,  1),
            ("Tokyo",        139.7,  35.7,  9,  15,  9),
            ("Shanghai",     121.5,  31.2,  9,  15,  8),
            ("Hong Kong",    114.2,  22.3,  9,  16,  8),
        ];

        // Friendly name map for known symbols
        let friendly_name = |sym: &str| -> String {
            match sym {
                "^GSPC"     => "S&P 500".into(),
                "^NDX"      => "Nasdaq 100".into(),
                "^DJI"      => "Dow Jones".into(),
                "ES=F"      => "S&P Fut".into(),
                "NQ=F"      => "NQ Fut".into(),
                "YM=F"      => "DJ Fut".into(),
                "RTY=F"     => "Russell Fut".into(),
                "CL=F"      => "Crude Oil".into(),
                "GC=F"      => "Gold".into(),
                "SI=F"      => "Silver".into(),
                "NG=F"      => "Nat Gas".into(),
                "ZB=F"      => "30Y T-Bond".into(),
                "ZN=F"      => "10Y T-Note".into(),
                "EURUSD=X"  => "EUR/USD".into(),
                "USDJPY=X"  => "USD/JPY".into(),
                "GBPUSD=X"  => "GBP/USD".into(),
                "EURGBP=X"  => "EUR/GBP".into(),
                "EURJPY=X"  => "EUR/JPY".into(),
                "USDCNH=X"  => "USD/CNH".into(),
                "ARS=X"     => "USD/ARS".into(),
                "BRL=X"     => "USD/BRL".into(),
                "^STOXX50E" => "Euro Stoxx 50".into(),
                "^FTSE"     => "FTSE 100".into(),
                "^GDAXI"    => "DAX".into(),
                "^N225"     => "Nikkei 225".into(),
                "^HSI"      => "Hang Seng".into(),
                "000001.SS" => "Shanghai Comp".into(),
                "^MERV"     => "MERVAL".into(),
                "^BVSP"     => "Bovespa".into(),
                _           => sym.to_string(),
            }
        };

        // Region ordering and symbols
        let regions: &[(&str, &[&str])] = &[
            ("USA",       &["^GSPC","^NDX","^DJI","ES=F","NQ=F","YM=F","CL=F","GC=F","SI=F","ZB=F","EURUSD=X","USDJPY=X","GBPUSD=X"]),
            ("Europe",    &["^STOXX50E","^FTSE","^GDAXI","EURUSD=X","EURGBP=X","EURJPY=X"]),
            ("Asia",      &["^N225","^HSI","000001.SS","USDJPY=X","USDCNH=X"]),
            ("Argentina", &["^MERV","ARS=X"]),
            ("Brazil",    &["^BVSP","BRL=X"]),
        ];

        // Horizontal split: left = map+hours, right = live prices
        let h = Layout::default()
            .direction(Direction::Horizontal)
            .constraints([Constraint::Percentage(55), Constraint::Percentage(45)])
            .split(area);

        // ── Left side: map on top, hours legend on bottom ──
        let v_left = Layout::default()
            .direction(Direction::Vertical)
            .constraints([Constraint::Min(0), Constraint::Length(14)])
            .split(h[0]);

        let canvas = Canvas::default()
            .block(Block::default().borders(Borders::ALL)
                .title(format!(" Global Markets — {} UTC  [6] ", now.format("%H:%M"))))
            .marker(symbols::Marker::Braille)
            .x_bounds([-180.0, 180.0])
            .y_bounds([-90.0, 90.0])
            .paint(move |ctx| {
                ctx.draw(&Map {
                    color: Color::DarkGray,
                    resolution: MapResolution::High,
                });
                for &(name, lon, lat, open_h, close_h, tz_offset) in markets {
                    let local_h = (now.hour() as i32 + tz_offset).rem_euclid(24) as u32;
                    let local_m = now.minute();
                    let local_time = local_h * 60 + local_m;
                    let is_open = !is_weekend && local_time >= open_h * 60 && local_time < close_h * 60;
                    let (color, status) = if is_open { (Color::Green, "●") } else { (Color::Red, "○") };
                    ctx.print(lon, lat, Span::styled(
                        format!("{} {}", status, name),
                        Style::default().fg(color).add_modifier(Modifier::BOLD),
                    ));
                }
            });
        frame.render_widget(canvas, v_left[0]);

        // Hours legend
        let hours_header = ratatui::widgets::Row::new(vec!["Market", "Local", "Hours", "Status"])
            .style(Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD));
        let hours_rows: Vec<ratatui::widgets::Row> = markets.iter().map(|&(name, _, _, open_h, close_h, tz_offset)| {
            let local_h = (now.hour() as i32 + tz_offset).rem_euclid(24) as u32;
            let local_m = now.minute();
            let local_time = local_h * 60 + local_m;
            let is_open = !is_weekend && local_time >= open_h * 60 && local_time < close_h * 60;
            let (status, color) = if is_open { ("OPEN", Color::Green) } else { ("CLOSED", Color::Red) };
            ratatui::widgets::Row::new(vec![
                name.to_string(),
                format!("{:02}:{:02}", local_h, local_m),
                format!("{:02}:00–{:02}:00", open_h, close_h),
                status.to_string(),
            ]).style(Style::default().fg(color))
        }).collect();
        let hours_table = Table::new(hours_rows, [
            Constraint::Length(14), Constraint::Length(8),
            Constraint::Length(14), Constraint::Length(7),
        ])
        .header(hours_header)
        .block(Block::default().borders(Borders::ALL).title(" Market Hours "));
        frame.render_widget(hours_table, v_left[1]);

        // ── Right side: live prices table grouped by region ──
        let loading_msg = if self.markets_data.is_empty() {
            " (loading…)"
        } else {
            ""
        };
        let price_header = ratatui::widgets::Row::new(vec!["Symbol", "Name", "Last", "Chg%", "Type"])
            .style(Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD));

        let mut price_rows: Vec<ratatui::widgets::Row> = Vec::new();
        for &(region, symbols) in regions {
            // Region separator row
            price_rows.push(
                ratatui::widgets::Row::new(vec![
                    format!("── {} ──", region),
                    String::new(), String::new(), String::new(), String::new(),
                ]).style(Style::default().fg(Color::Cyan).add_modifier(Modifier::BOLD))
            );
            for sym in symbols.iter().copied() {
                if let Some(row) = self.markets_data.get(sym) {
                    let chg_color = if row.change_pct > 0.0 { Color::Green }
                                    else if row.change_pct < 0.0 { Color::Red }
                                    else { Color::Gray };
                    let chg_str = if row.change_pct == 0.0 {
                        "  –".to_string()
                    } else {
                        format!("{:+.2}%", row.change_pct)
                    };
                    let last_str = if row.last_price == 0.0 {
                        "  –".to_string()
                    } else if row.last_price >= 1000.0 {
                        format!("{:>10.2}", row.last_price)
                    } else {
                        format!("{:>10.4}", row.last_price)
                    };
                    price_rows.push(
                        ratatui::widgets::Row::new(vec![
                            sym.to_string(),
                            friendly_name(sym),
                            last_str,
                            chg_str.clone(),
                            row.asset_class.clone(),
                        ]).style(Style::default().fg(chg_color))
                    );
                } else {
                    // No data yet
                    price_rows.push(
                        ratatui::widgets::Row::new(vec![
                            sym.to_string(),
                            friendly_name(sym),
                            "  –".to_string(),
                            "  –".to_string(),
                            String::new(),
                        ]).style(Style::default().fg(Color::DarkGray))
                    );
                }
            }
        }

        let price_table = Table::new(price_rows, [
            Constraint::Length(12), Constraint::Length(14),
            Constraint::Length(12), Constraint::Length(8),
            Constraint::Min(6),
        ])
        .header(price_header)
        .block(Block::default().borders(Borders::ALL)
            .title(format!(" Live Prices{} ", loading_msg)));
        frame.render_widget(price_table, h[1]);
    }

    // ─── Tabs ───────────────────────────────────────────────────────────

    fn render_tabs(&self, area: Rect, frame: &mut Frame) {
        let tab_defs: &[(&str, ExchangeTab, Color)] = &[
            (" [1]Binance ",   ExchangeTab::Binance,   Color::Yellow),
            (" [2]MERVAL ",    ExchangeTab::Merval,    Color::LightBlue),
            (" [3]Options ",   ExchangeTab::Options,   Color::Green),
            (" [4]Futures ",   ExchangeTab::Futures,   Color::Magenta),
            (" [5]News ",      ExchangeTab::News,      Color::Cyan),
            (" [6]Markets ",   ExchangeTab::Markets,   Color::White),
            (" [7]US Futures", ExchangeTab::UsFutures, Color::LightRed),
        ];
        let titles: Vec<Line> = tab_defs.iter().map(|(label, tab, color)| {
            Line::from(Span::styled(
                *label,
                if self.active_tab == *tab {
                    Style::default().fg(Color::Black).bg(*color).add_modifier(Modifier::BOLD)
                } else {
                    Style::default().fg(*color)
                },
            ))
        }).collect();
        let sel = tab_defs.iter().position(|(_, t, _)| *t == self.active_tab).unwrap_or(0);
        let tabs = Tabs::new(titles)
            .block(Block::default().borders(Borders::ALL).title(" TWS Terminal "))
            .highlight_style(Style::default().add_modifier(Modifier::BOLD))
            .select(sel);
        frame.render_widget(tabs, area);
    }

    // ─── Status bar ─────────────────────────────────────────────────────

    fn render_status_bar(&self, area: Rect, frame: &mut Frame) {
        let info = match self.active_tab {
            ExchangeTab::Merval => {
                Line::from(vec![
                    Span::styled("MERVAL", Style::default().fg(Color::LightBlue).add_modifier(Modifier::BOLD)),
                    Span::styled(
                        format!("  ARS {:.0}  Chg: {:.2}%  Vol: {:.0}  Status: {}",
                            self.merval_data.current_price,
                            self.merval_data.daily_change,
                            self.merval_data.volume_24h,
                            self.merval_data.market_status),
                        Style::default().fg(Color::Cyan),
                    ),
                ])
            }
            ExchangeTab::Options => {
                let spot_str = if self.ggal_spot > 0.0 { format!("GGAL spot: {:.2} ARS", self.ggal_spot) }
                               else { "GGAL spot: loading…".to_string() };
                Line::from(Span::styled(spot_str, Style::default().fg(Color::Green)))
            }
            ExchangeTab::Futures => {
                if self.futures_curve.is_empty() {
                    Line::from(Span::styled("DLR Futures — loading…", Style::default().fg(Color::Magenta)))
                } else {
                    let parts: Vec<String> = self.futures_curve.iter()
                        .map(|r| {
                            let label = r.instrument.split('_').last().unwrap_or(&r.instrument);
                            format!("{}: {:.0}", label, r.last_price)
                        }).collect();
                    Line::from(Span::styled(parts.join("   "), Style::default().fg(Color::Magenta)))
                }
            }
            ExchangeTab::News => {
                Line::from(Span::styled(
                    format!("News — {} items", self.news_items.len()),
                    Style::default().fg(Color::Cyan),
                ))
            }
            ExchangeTab::Markets => {
                Line::from(Span::styled(
                    "Global Markets — ● open  ○ closed",
                    Style::default().fg(Color::White),
                ))
            }
            ExchangeTab::UsFutures => {
                let sym = self.us_futures_symbols[self.us_futures_selected];
                let (price, prev) = self.us_futures_live.get(sym).copied().unwrap_or((0.0, 0.0));
                let chg_color = if price >= prev { Color::Green } else { Color::Red };
                Line::from(vec![
                    Span::styled(format!(" {} ", sym), Style::default().fg(Color::LightRed).add_modifier(Modifier::BOLD)),
                    Span::styled(format!("{:.2}", price), Style::default().fg(chg_color).add_modifier(Modifier::BOLD)),
                ])
            }
            ExchangeTab::Binance => {
                let dot = if self.binance_connected {
                    Span::styled("● LIVE", Style::default().fg(Color::Green).add_modifier(Modifier::BOLD))
                } else {
                    Span::styled("○ CONNECTING", Style::default().fg(Color::Red))
                };
                if let Some(sym) = self.selected_sym() {
                    if let Some(d) = self.symbol_map.get(sym) {
                        let chg_color = if d.daily_change_pct >= 0.0 { Color::Green } else { Color::Red };
                        Line::from(vec![
                            Span::raw("Binance "), dot,
                            Span::styled(
                                format!("  {} | Close: {:.4}  O:{:.4}  H:{:.4}  L:{:.4}  Vol:{}  Chg: ",
                                    sym, d.close, d.open, d.high, d.low, fmt_volume(d.volume)),
                                Style::default().fg(Color::Cyan),
                            ),
                            Span::styled(format!("{:+.4}%", d.daily_change_pct),
                                Style::default().fg(chg_color).add_modifier(Modifier::BOLD)),
                        ])
                    } else {
                        Line::from(vec![Span::raw("Binance "), dot, Span::raw("  Waiting for data...")])
                    }
                } else {
                    Line::from(vec![Span::raw("Binance "), dot,
                        if let Some(e) = &self.error_message {
                            Span::styled(format!("  {e}"), Style::default().fg(Color::DarkGray))
                        } else { Span::raw("  Waiting for Redis data...") }
                    ])
                }
            }
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
        let Some(sym) = self.selected_sym() else {
            frame.render_widget(Paragraph::new("No data").block(Block::default().borders(Borders::ALL)), area);
            return;
        };
        let Some(d) = self.symbol_map.get(sym) else {
            frame.render_widget(Paragraph::new("Waiting…").block(Block::default().borders(Borders::ALL)), area);
            return;
        };
        if d.price_history.is_empty() {
            frame.render_widget(
                Paragraph::new("  Waiting for data…").block(Block::default().borders(Borders::ALL).title(format!(" {} ", sym))),
                area,
            );
            return;
        }

        // Convert u64 scaled history back to f64 prices
        let points: Vec<(f64, f64)> = d.price_history.iter().enumerate()
            .map(|(i, &v)| (i as f64, v as f64 / 100.0))
            .collect();

        let min = points.iter().map(|p| p.1).fold(f64::MAX, f64::min);
        let max = points.iter().map(|p| p.1).fold(f64::MIN, f64::max);
        let padding = (max - min) * 0.05 + 0.0001;
        let color = if d.daily_change_pct >= 0.0 { Color::Green } else { Color::Red };
        let n = points.len() as f64;

        let dataset = Dataset::default()
            .marker(symbols::Marker::Braille)
            .graph_type(GraphType::Line)
            .style(Style::default().fg(color))
            .data(&points);

        let chart = Chart::new(vec![dataset])
            .block(Block::default().borders(Borders::ALL)
                .title(format!(" {} Price  {:.4}  {:+.2}% ", sym, d.close, d.daily_change_pct)))
            .x_axis(Axis::default()
                .bounds([0.0, n])
                .labels(vec![
                    Span::raw("oldest"),
                    Span::raw("latest"),
                ]))
            .y_axis(Axis::default()
                .bounds([min - padding, max + padding])
                .labels(vec![
                    Span::styled(format!("{:.4}", min), Style::default().fg(Color::DarkGray)),
                    Span::styled(format!("{:.4}", max), Style::default().fg(Color::DarkGray)),
                ]));

        frame.render_widget(chart, area);
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

    fn render_merval_view(&mut self, area: Rect, frame: &mut Frame) {
        if self.merval_live_sorted.is_empty() {
            frame.render_widget(
                Paragraph::new("  Waiting for live data from Matriz Redis channel…")
                    .style(Style::default().fg(Color::DarkGray))
                    .block(Block::default().borders(Borders::ALL).title(" MERVAL Live ")),
                area,
            );
            return;
        }

        let chunks = Layout::default()
            .direction(Direction::Horizontal)
            .constraints([Constraint::Min(0), Constraint::Length(30)])
            .split(area);

        // ── Left: scrollable instruments table ──
        let selected_row = self.merval_live_state.selected().unwrap_or(0);
        let header = ratatui::widgets::Row::new(vec!["Instrument", "Last", "Chg%", "Bid", "Ask", "High", "Low"])
            .style(Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD));

        let rows: Vec<ratatui::widgets::Row> = self.merval_live_sorted.iter().map(|instr| {
            let short = instr
                .trim_start_matches("M:bm_MERV_")
                .trim_start_matches("M:rx_DDF_")
                .trim_end_matches("_24hs")
                .trim_end_matches("_48hs");
            let d = self.merval_live.get(instr);
            let (last, chg, bid, ask, high, low) = d.map(|d| (
                d.last_price, d.change_pct, d.bid_price, d.ask_price, d.high, d.low
            )).unwrap_or_default();

            let chg_style = if chg >= 0.0 {
                Style::default().fg(Color::Green)
            } else {
                Style::default().fg(Color::Red)
            };

            ratatui::widgets::Row::new(vec![
                ratatui::text::Span::raw(short.to_string()),
                ratatui::text::Span::raw(if last > 0.0 { format!("{:.2}", last) } else { "--".into() }),
                ratatui::text::Span::styled(
                    if d.map(|d| d.prev_close > 0.0).unwrap_or(false) {
                        format!("{:+.2}%", chg)
                    } else { "--".into() },
                    chg_style,
                ),
                ratatui::text::Span::raw(if bid > 0.0 { format!("{:.2}", bid) } else { "--".into() }),
                ratatui::text::Span::raw(if ask > 0.0 { format!("{:.2}", ask) } else { "--".into() }),
                ratatui::text::Span::raw(if high > 0.0 { format!("{:.2}", high) } else { "--".into() }),
                ratatui::text::Span::raw(if low > 0.0 { format!("{:.2}", low) } else { "--".into() }),
            ])
        }).collect();

        let widths = [
            Constraint::Length(18),
            Constraint::Length(12),
            Constraint::Length(8),
            Constraint::Length(12),
            Constraint::Length(12),
            Constraint::Length(12),
            Constraint::Length(12),
        ];
        let table = Table::new(rows, widths)
            .header(header)
            .block(Block::default().borders(Borders::ALL)
                .title(format!(" MERVAL Live ({}) [↑↓] ", self.merval_live_sorted.len())))
            .highlight_style(Style::default().fg(Color::Black).bg(Color::LightBlue).add_modifier(Modifier::BOLD))
            .highlight_symbol("▶ ");
        frame.render_stateful_widget(table, chunks[0], &mut self.merval_live_state);

        // ── Right: sparkline + detail for selected instrument ──
        let sel_instr = self.merval_live_sorted.get(selected_row).cloned();
        let right_chunks = Layout::default()
            .direction(Direction::Vertical)
            .constraints([Constraint::Length(8), Constraint::Min(0)])
            .split(chunks[1]);

        if let Some(ref instr) = sel_instr {
            if let Some(d) = self.merval_live.get(instr) {
                let short = instr
                    .trim_start_matches("M:bm_MERV_")
                    .trim_start_matches("M:rx_DDF_")
                    .trim_end_matches("_24hs")
                    .trim_end_matches("_48hs");
                let chg_color = if d.change_pct >= 0.0 { Color::Green } else { Color::Red };
                let info = vec![
                    Line::from(vec![
                        ratatui::text::Span::raw("Last:  "),
                        ratatui::text::Span::styled(format!("{:.2}", d.last_price), Style::default().fg(Color::White).add_modifier(Modifier::BOLD)),
                    ]),
                    Line::from(vec![
                        ratatui::text::Span::raw("Chg:   "),
                        ratatui::text::Span::styled(format!("{:+.2}%", d.change_pct), Style::default().fg(chg_color)),
                    ]),
                    Line::from(format!("Bid:   {:.2}", d.bid_price)),
                    Line::from(format!("Ask:   {:.2}", d.ask_price)),
                    Line::from(format!("High:  {:.2}", d.high)),
                    Line::from(format!("Low:   {:.2}", d.low)),
                ];
                frame.render_widget(
                    Paragraph::new(info).block(Block::default().borders(Borders::ALL).title(format!(" {} ", short))),
                    right_chunks[0],
                );
                frame.render_widget(
                    Sparkline::default()
                        .block(Block::default().borders(Borders::ALL).title(" Price "))
                        .data(&d.sparkline)
                        .style(Style::default().fg(chg_color)),
                    right_chunks[1],
                );
            }
        } else {
            frame.render_widget(
                Paragraph::new("").block(Block::default().borders(Borders::ALL).title(" Detail ")),
                right_chunks[0],
            );
        }
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
            _                    => SubTab::RealTime,
        };

        let (text, style) = match self.input_mode {
            InputMode::FilterEdit => (
                "[Tab] switch field  [Enter] apply  [Esc] cancel".to_string(),
                Style::default().fg(Color::Cyan),
            ),
            InputMode::AddingFavorite => (
                format!("Add favorite: {}_  [Enter] confirm  [Esc] cancel", self.fav_input),
                Style::default().fg(Color::Yellow).add_modifier(Modifier::BOLD),
            ),
            InputMode::CalcEdit => (
                "[type IV as decimal e.g. 0.45]  [Enter] compute Greeks  [Esc] close".to_string(),
                Style::default().fg(Color::Green),
            ),
            InputMode::Normal => {
                let hint = match self.active_tab {
                    ExchangeTab::Options => "[↑↓] scroll  [Tab] calls/puts  [c] calculator  [r] refresh  [←→] prev/next tab  [q] quit",
                    ExchangeTab::Futures   => "[←→] switch contract  [↑↓] scroll ticks  [r] refresh  [1-5] switch tab  [q] quit",
                    ExchangeTab::UsFutures => "[↑↓] select symbol  [s] real-time/historical  [r] refresh  [Tab] next tab  [q] quit",
                    ExchangeTab::News    => "[↑↓] scroll  [Enter] open article  [r] refresh  [1-5] switch tab  [q] quit",
                    _ => match (self.active_tab, active_subtab) {
                        (ExchangeTab::Merval, SubTab::Historical) =>
                            "[↑↓] select instrument  [Enter] load chart  [t] time range  [f] filter  [s] real-time  [1-5] tab  [q] quit",
                        (ExchangeTab::Binance, SubTab::Historical) =>
                            "[↑↓] scroll  [p] panel  [f] filter  [s] real-time  [1-5] tab  [q] quit",
                        (ExchangeTab::Merval, SubTab::RealTime) =>
                            "[↑↓] navigate  [s] historical  [1-5] tab  [q] quit",
                        _ =>
                            "[↑↓] select symbol  [s] historical  [1-5] tab  [q] quit",
                    },
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

fn extract_xml_tag(xml: &str, tag: &str) -> String {
    let open  = format!("<{}>", tag);
    let close = format!("</{}>", tag);
    if let Some(start) = xml.find(&open) {
        let content = &xml[start + open.len()..];
        if let Some(end) = content.find(&close) {
            return content[..end]
                .trim_start_matches("<![CDATA[")
                .trim_end_matches("]]>")
                .trim()
                .to_string();
        }
    }
    String::new()
}