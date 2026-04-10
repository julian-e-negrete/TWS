# DATA_SPEC.md — Contrato de Datos para Sistemas Consumidores

> **TUI data layer (db/mod.rs functions, Redis channels, trigger→field mapping, MCP tools):**
> see [`Documentation/DATA_SPEC.md`](Documentation/DATA_SPEC.md)

> Fuente de verdad para cualquier agente o sistema que lea datos de este servidor.
> Los datos son producidos por el servidor de ingesta (`github.com/julian-e-negrete/server`).

---

## 1. Infraestructura de Acceso

| Parámetro | Valor |
|-----------|-------|
| Motor | PostgreSQL 12 + TimescaleDB 2.11.2 |
| Host | `100.112.16.115` (scrapper server) |
| Puerto | `5432` |
| Base de datos | `marketdata` |
| Usuario | `postgres` |
| Credenciales | Variable de entorno `PG_PASSWORD` |

```python
import psycopg2, os
conn = psycopg2.connect(
    host="100.112.16.115", port=5432, dbname="marketdata",
    user="postgres", password=os.environ["PG_PASSWORD"], sslmode="disable"
)
```

> Todas las tablas usan `TIMESTAMPTZ` — los timestamps están en UTC. Convertir a ART con `AT TIME ZONE 'America/Argentina/Buenos_Aires'` si se necesita hora local.

---

## 2. Tablas Disponibles

### 2.1 `ticks` — Cotizaciones tick a tick (Matriz / BYMA)

**Tipo:** TimescaleDB hypertable. Particionada por día. Compresión habilitada en chunks > 7 días.

| Columna | Tipo | Descripción |
|---------|------|-------------|
| `time` | `TIMESTAMPTZ NOT NULL` | Timestamp del tick (UTC) |
| `instrument` | `TEXT NOT NULL` | Identificador del instrumento (ver §3) |
| `bid_price` | `NUMERIC(18,6)` | Precio de compra |
| `ask_price` | `NUMERIC(18,6)` | Precio de venta |
| `bid_volume` | `BIGINT` | Volumen oferta compra |
| `ask_volume` | `BIGINT` | Volumen oferta venta |
| `last_price` | `NUMERIC(18,6)` | Último precio operado |
| `total_volume` | `BIGINT` | Volumen acumulado del día |
| `high` | `NUMERIC(18,6)` | Máximo del día |
| `low` | `NUMERIC(18,6)` | Mínimo del día |
| `prev_close` | `NUMERIC(18,6)` | Cierre anterior |

**Cobertura de datos:**

| Instrumento | Filas | Desde | Hasta |
|-------------|-------|-------|-------|
| `M:bm_MERV_AL30_24hs` | ~3.7M | 2025-08-19 | activo |
| `M:bm_MERV_AL30D_24hs` | ~3.5M | 2025-08-19 | activo |
| `M:bm_MERV_PESOS_1D` | ~2.2M | 2025-08-19 | activo |
| `M:bm_MERV_GGALD_24hs` | ~745K | 2025-08-19 | activo |
| `M:bm_MERV_PBRD_24hs` | ~384K | 2025-08-19 | activo |
| `M:bm_MERV_BBDD_24hs` | ~189K | 2025-08-19 | activo |
| `M:rx_DDF_DLR_*` | variable | 2025-08 | por vencimiento |

**Queries de ejemplo:**

```sql
-- Últimos 100 ticks de AL30
SELECT time, last_price, bid_price, ask_price, total_volume
FROM ticks
WHERE instrument = 'M:bm_MERV_AL30_24hs'
ORDER BY time DESC
LIMIT 100;

-- OHLCV por minuto (último día)
SELECT
    time_bucket('1 minute', time) AS bucket,
    instrument,
    FIRST(last_price, time) AS open,
    MAX(high)               AS high,
    MIN(low)                AS low,
    LAST(last_price, time)  AS close,
    MAX(total_volume) - MIN(total_volume) AS volume
FROM ticks
WHERE instrument = 'M:bm_MERV_AL30_24hs'
  AND time > NOW() - INTERVAL '1 day'
GROUP BY bucket, instrument
ORDER BY bucket DESC;

-- Spread promedio por hora
SELECT
    time_bucket('1 hour', time) AS hora,
    AVG(ask_price - bid_price) AS spread_promedio
FROM ticks
WHERE instrument = 'M:bm_MERV_AL30_24hs'
  AND time > NOW() - INTERVAL '7 days'
GROUP BY hora ORDER BY hora DESC;
```

---

### 2.2 `orders` — Órdenes ejecutadas (Matriz REST)

**Tipo:** TimescaleDB hypertable. Compresión habilitada en chunks > 7 días.

| Columna | Tipo | Descripción |
|---------|------|-------------|
| `time` | `TIMESTAMPTZ NOT NULL` | Timestamp de la operación (UTC) |
| `instrument` | `VARCHAR(50) NOT NULL` | Instrumento (sin prefijo `M:`) |
| `price` | `NUMERIC(18,6)` | Precio de la operación |
| `volume` | `BIGINT` | Cantidad operada |
| `side` | `CHAR(1)` | `'B'` = compra, `'S'` = venta |

**Cobertura de datos:**

| Instrumento | Filas | Desde | Hasta |
|-------------|-------|-------|-------|
| `rx_DDF_DLR_OCT25` | ~39K | 2025-10-02 | 2025-10-31 |
| `rx_DDF_DLR_SEP25` | ~24K | 2025-09-03 | 2025-09-30 |
| `rx_DDF_DLR_NOV25` | ~19K | 2025-11-03 | 2025-11-28 |
| `rx_DDF_DLR_AGO25` | ~18K | 2025-08-12 | 2025-08-29 |

> Nota: el instrumento activo actual se actualiza mensualmente (contrato de dólar futuro).

**Queries de ejemplo:**

```sql
-- Flujo de órdenes últimas 2 horas
SELECT time, instrument, price, volume, side
FROM orders
WHERE time > NOW() - INTERVAL '2 hours'
ORDER BY time DESC;

-- Volumen comprador vs vendedor por instrumento
SELECT
    instrument,
    SUM(CASE WHEN side = 'B' THEN volume ELSE 0 END) AS vol_compra,
    SUM(CASE WHEN side = 'S' THEN volume ELSE 0 END) AS vol_venta
FROM orders
WHERE time > NOW() - INTERVAL '1 day'
GROUP BY instrument;
```

---

### 2.3 `binance_ticks` — Velas OHLCV Binance (1 minuto)

**Tipo:** TimescaleDB hypertable. 3 chunks.

| Columna | Tipo | Descripción |
|---------|------|-------------|
| `symbol` | `VARCHAR(20) NOT NULL` | Par de trading (ej: `USDTARS`, `BTCUSDT`) |
| `timestamp` | `TIMESTAMPTZ NOT NULL` | Apertura de la vela (UTC) |
| `open` | `NUMERIC(18,6)` | Precio apertura |
| `high` | `NUMERIC(18,6)` | Máximo |
| `low` | `NUMERIC(18,6)` | Mínimo |
| `close` | `NUMERIC(18,6)` | Precio cierre |
| `volume` | `NUMERIC(18,6)` | Volumen operado |

**Cobertura de datos:**

| Symbol | Filas | Desde | Hasta |
|--------|-------|-------|-------|
| `USDTARS` | ~6.8K | 2025-08-05 | 2026-03-18 |
| `BTCUSDT` | ~6.8K | 2025-08-05 | 2026-03-18 |

> Ingesta activa vía `binance_monitor.service` (Mon–Fri 10:00–17:00 ART).

**Queries de ejemplo:**

```sql
-- Últimas 60 velas de USDTARS
SELECT timestamp, open, high, low, close, volume
FROM binance_ticks
WHERE symbol = 'USDTARS'
ORDER BY timestamp DESC
LIMIT 60;

-- Precio de cierre por hora
SELECT
    time_bucket('1 hour', timestamp) AS hora,
    LAST(close, timestamp) AS close
FROM binance_ticks
WHERE symbol = 'USDTARS'
  AND timestamp > NOW() - INTERVAL '7 days'
GROUP BY hora ORDER BY hora DESC;
```

---

### 2.4 `binance_trades` — Trades individuales Binance (aggTrade)

**Tipo:** TimescaleDB hypertable.

| Columna | Tipo | Descripción |
|---------|------|-------------|
| `time` | `TIMESTAMPTZ NOT NULL` | Timestamp del trade (UTC) |
| `symbol` | `TEXT NOT NULL` | Par de trading (ej: `SOLUSDT`, `BTCUSDT`) |
| `price` | `NUMERIC(18,6)` | Precio del trade |
| `qty` | `NUMERIC(18,6)` | Cantidad operada |
| `is_buyer_maker` | `BOOLEAN` | `true` si el comprador es el maker (venta agresiva) |
| `trade_id` | `BIGINT` | ID de trade Binance (aggTrade ID) |

**Fuente:** Binance WebSocket aggTrade stream — `scrapers/binance/run.py`.

**Queries de ejemplo:**

```sql
-- Últimos 100 trades de SOLUSDT
SELECT time, price, qty, is_buyer_maker
FROM binance_trades
WHERE symbol = 'SOLUSDT'
ORDER BY time DESC LIMIT 100;

-- Volumen comprador vs vendedor (última hora)
SELECT
    symbol,
    SUM(CASE WHEN NOT is_buyer_maker THEN qty ELSE 0 END) AS vol_buy,
    SUM(CASE WHEN is_buyer_maker THEN qty ELSE 0 END)     AS vol_sell
FROM binance_trades
WHERE time > NOW() - INTERVAL '1 hour'
GROUP BY symbol;
```

---

### 2.5 `solana_dex_trades` — Snapshots de precio Solana DEX (P10)

**Tipo:** TimescaleDB hypertable. Particionada por tiempo. Un registro por pool por minuto.

| Columna | Tipo | Descripción |
|---------|------|-------------|
| `time` | `TIMESTAMPTZ NOT NULL` | Timestamp del snapshot (UTC) |
| `symbol` | `TEXT NOT NULL` | Par de trading (ej: `SOL/USDC`, `SOL/USDT`) |
| `price` | `NUMERIC(18,6)` | Precio en USD del pool en ese momento |
| `qty` | `NUMERIC(18,6)` | Volumen operado en los últimos 5 minutos (USD) |
| `is_buyer_maker` | `BOOLEAN` | Siempre `NULL` — no disponible en API de snapshots |
| `source_dex` | `TEXT NOT NULL` | DEX de origen (ej: `orca`, `raydium`, `meteora`) |
| `trade_id` | `BIGINT NOT NULL` | ID sintético: epoch-ms + índice de fila |
| `pair_address` | `TEXT NOT NULL` | Dirección del pool en Solana |
| UNIQUE | `(time, pair_address)` | |

**Fuente:** DexScreener REST API — `https://api.dexscreener.com/latest/dex/tokens/So11111111111111111111111111111111111111112`. Sin autenticación. Devuelve todos los pools SOL/USDC y SOL/USDT en Solana (~25 pools). Scraper: `scrapers/solana_dex/run.py`, ejecutado cada minuto vía crontab.

**Nota importante:** Esta tabla contiene snapshots periódicos de precio/volumen, **no trades individuales**. No existe API pública sin autenticación que provea trades individuales de DEXes de Solana. `is_buyer_maker` es siempre `NULL`. Para trades individuales se requeriría una API key de Birdeye u otro proveedor.

**Pools cubiertos (principales por volumen):**

| Pool | DEX | Par | Vol 24h típico |
|------|-----|-----|----------------|
| `Czfq3xZZ...` | orca | SOL/USDC | ~$170M |
| `3nMFwZXw...` | raydium | SOL/USDC | ~$37M |
| `8Pm2kZpn...` | meteora | SOL/USDC | ~$1.5M |
| `3fkdUeRv...` | raydium | SOL/USDT | ~$37M |

**Queries de ejemplo:**

```sql
-- Precio promedio de SOL/USDC por minuto (última hora), ponderado por volumen
SELECT
    time_bucket('1 minute', time) AS bucket,
    SUM(price * qty) / NULLIF(SUM(qty), 0) AS vwap
FROM solana_dex_trades
WHERE symbol = 'SOL/USDC'
  AND time > NOW() - INTERVAL '1 hour'
GROUP BY bucket ORDER BY bucket DESC;

-- Precio por DEX en el último snapshot
SELECT DISTINCT ON (source_dex, symbol)
    source_dex, symbol, price, qty, time
FROM solana_dex_trades
WHERE symbol IN ('SOL/USDC', 'SOL/USDT')
ORDER BY source_dex, symbol, time DESC;

-- Volumen total por DEX (últimas 24h)
SELECT source_dex, symbol, SUM(qty) AS vol_usd
FROM solana_dex_trades
WHERE time > NOW() - INTERVAL '24 hours'
GROUP BY source_dex, symbol
ORDER BY vol_usd DESC;
```

---

### 2.6 `cookies` — Sesiones de autenticación Matriz

> Tabla interna del servidor de ingesta. No relevante para sistemas consumidores.

---

## 4. Nomenclatura de Instrumentos

### Prefijo `M:bm_MERV_` — Acciones y bonos BYMA (mercado continuo)

| Instrumento | Descripción |
|-------------|-------------|
| `M:bm_MERV_AL30_24hs` | AL30 — Bono soberano USD ley arg, liquidación 24hs |
| `M:bm_MERV_AL30D_24hs` | AL30D — AL30 en dólares cable, liquidación 24hs |
| `M:bm_MERV_PESOS_1D` | Índice pesos, liquidación 1 día |
| `M:bm_MERV_GGALD_24hs` | GGAL — Grupo Financiero Galicia ADR, 24hs |
| `M:bm_MERV_PBRD_24hs` | PBR — Petrobras ADR, 24hs |
| `M:bm_MERV_BBDD_24hs` | BBD — Banco Bradesco ADR, 24hs |
| `M:bm_MERV_SUPV_24hs` | SUPV — Supervielle, 24hs |

### Prefijo `M:rx_DDF_DLR_` — Futuros de dólar (MatbaRofex)

Formato: `M:rx_DDF_DLR_<MES><AÑO>` — contrato mensual de dólar futuro.

| Ejemplo | Descripción |
|---------|-------------|
| `M:rx_DDF_DLR_MAR26` | Futuro dólar vencimiento marzo 2026 |
| `M:rx_DDF_DLR_MAR26A` | Variante A del mismo vencimiento |

> El instrumento activo cambia cada mes. Consultar `SELECT DISTINCT instrument FROM ticks WHERE time > NOW() - INTERVAL '3 days'` para obtener los activos vigentes.

### Binance

| Symbol | Descripción |
|--------|-------------|
| `USDTARS` | Dólar crypto (USDT) en pesos argentinos |
| `BTCUSDT` | Bitcoin en dólares |

---

## 5. Horarios de Ingesta

| Fuente | Horario (ART) | Días | Mecanismo |
|--------|--------------|------|-----------|
| Matriz ticks (`ticks`) | 10:00–17:00 | Lun–Vie | `wsclient.service` (WebSocket) |
| Matriz órdenes (`orders`) | 10:00–16:59 | Lun–Vie | crontab cada 2 min |
| Binance (`binance_ticks`, `binance_trades`) | 10:00–17:00 | Lun–Vie | `binance_monitor.service` (WebSocket) |
| Solana DEX (`solana_dex_trades`) | 24/7 | Todos | crontab cada 1 min |

> Fuera de horario, las tablas no reciben nuevos datos pero son consultables normalmente.

---

## 6. Consideraciones para el Agente Consumidor

1. **Timestamps en UTC** — todos los `time`/`timestamp` están en UTC. Para filtrar por horario de mercado argentino: `WHERE time AT TIME ZONE 'America/Argentina/Buenos_Aires' BETWEEN '10:00' AND '17:00'`.

2. **Datos comprimidos** — chunks históricos (> 7 días) están comprimidos por TimescaleDB. Las queries funcionan normalmente; la descompresión es transparente. Para mejor performance en rangos históricos, usar `time_bucket()`.

3. **Gaps esperados** — no hay datos los fines de semana ni feriados bursátiles argentinos.

4. **Instrumento activo de futuros** — el contrato vigente cambia mensualmente. No hardcodear el nombre; consultarlo dinámicamente.

5. **Volumen en `ticks`** — `total_volume` es acumulado del día, no incremental. Para volumen por período: `MAX(total_volume) - MIN(total_volume)`.

6. **`orders` vs `ticks`** — `ticks` es el feed de mercado completo (bid/ask/last en tiempo real). `orders` son las operaciones ejecutadas individuales (trade-by-trade) del futuro de dólar.