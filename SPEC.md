# TWS (Trader Workstation) Project Specification

## 1. Project Overview
A high-performance terminal inspired by Interactive Brokers' Trader Workstation (TWS), focusing on advanced research, data visualization, and modular financial tools.

## 2. Core Components

### 2.1. Perception Layer (ByMA Ingestion)
- **Source**: `https://open.bymadata.com.ar/`
- **Strategy**: 
    - Automated API-based ingestion (REST JSON).
    - Token-based authentication (session-based).
    - Polling for real-time updates (Options, Futures, Prices).
    - Document pipeline for "Hechos Relevantes" (Relevant Facts) using `descarga` IDs.
- **Data Models**:
    - `Security`: Ticker, Name, Type (Stock, Bond, Option, Future).
    - `MarketData`: Bid, Ask, Last, Volume, Open Interest.
    - `RelevantFact`: Date, Issuer, Description, Document Link.

### 2.2. Derivatives Suite
- **Option Pricing Engine**:
    - Models: Black-Scholes, Binomial (for American options).
    - Greeks: Delta, Gamma, Theta, Vega, Rho (Real-time calculation).
    - Implied Volatility (IV) solver.
- **Option Matrix (Grid)**:
    - Strike prices vs. Expiration dates.
    - Cell-level Greeks and IV visualization.
- **Futures Analysis**:
    - Term structure (Curve) visualization.
    - Basis calculation and monitoring.

### 2.3. Market Depth & Liquidity
- **DOM (Depth of Market)**:
    - Level 2 bid/ask spread visualization.
    - Visual indicators for order book imbalance.
- **Pool Liquidity**:
    - TVL (Total Value Locked) and Volume monitoring.
    - Liquidity concentration heatmaps.

### 2.4. Modular UI (Dashboard)
- **Framework**: Vite/Next.js (as per user request style, but core is HTML/JS/CSS).
- **Architecture**: Registry of "Micro-Components" (Pricing, News, Charting, DOM).
- **Layout**: Snap-and-dock system for customizable research workstations.

## 3. Technical Architecture
- **Backend**: Python (FastAPI or simple script-based MCP server).
- **Frontend**: Vite (React) with Vanilla CSS for premium aesthetics.
- **Database/Cache**: PostgreSQL (Historical), Redis (Real-time).
- **Agentic Integration**: Modular agents for specific tasks (Scraping, Analytics, UI Generation).

## 4. Task Roadmap (Phase 3)
- [x] **Task 1**: Create SPEC.md (This file).
- [x] **Task 2**: Audit ByMA Data Structure (Completed via Browser Subagent).
- [ ] **Task 3**: Implement/Enhance Core Option Pricing Engine.
- [ ] **Task 4**: Scaffold Visualization Frontend (Multi-Agent approach).
- [ ] **Task 5**: Execute Unit Testing and Validation.
