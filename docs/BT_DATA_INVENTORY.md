# Inventario de Datos — AlgoTrading

**Generado:** 2026-03-21

---

## PostgreSQL — tabla `ticks`

| Instrumento | Categoría | Desde | Hasta | Días | Ticks | Spread Avg | Precio Avg |
|---|---|---|---|---|---|---|---|
| M:bm_MERV_AL30_24hs | Bono BYMA | 2025-08-19 | 2026-03-20 | 122 | 3,703,712 | 18.68 ARS | 87,127 ARS |
| M:bm_MERV_AL30D_24hs | Bono BYMA (USD) | 2025-08-19 | 2026-03-20 | 122 | 3,463,119 | 0.015 USD | 59.81 USD |
| M:bm_MERV_PESOS_1D | Pesos | 2025-08-19 | 2026-03-19 | 87 | 2,239,445 | 0.23 | 29.55 |
| M:bm_MERV_GGALD_24hs | Acción BYMA (USD) | 2025-08-19 | 2026-03-20 | 122 | 744,896 | 0.018 USD | 4.40 USD |
| M:bm_MERV_PBRD_24hs | Acción BYMA (USD) | 2025-08-19 | 2026-03-20 | 122 | 383,981 | 0.062 USD | 14.52 USD |
| M:bm_MERV_BBDD_24hs | Acción BYMA (USD) | 2025-08-19 | 2026-03-20 | 121 | 188,809 | 0.031 USD | 3.61 USD |
| M:rx_DDF_DLR_SEP25 | Futuro DLR | 2025-09-03 | 2025-09-30 | 19 | 140,250 | 1.22 ARS | 1,422 ARS |
| M:rx_DDF_DLR_OCT25 | Futuro DLR | 2025-10-01 | 2025-10-31 | 20 | 125,542 | 1.58 ARS | 1,448 ARS |
| M:rx_DDF_DLR_AGO25 | Futuro DLR | 2025-08-05 | 2025-08-29 | 16 | 103,948 | 0.83 ARS | 1,347 ARS |
| M:rx_DDF_DLR_NOV25 | Futuro DLR | 2025-11-03 | 2025-11-28 | 14 | 65,353 | 1.04 ARS | 1,445 ARS |
| M:bm_MERV_GFGC69573O_24hs | Opción GFGC | 2025-08-14 | 2025-09-04 | 11 | 63,859 | 3.38 | 195.79 |
| M:rx_DDF_DLR_DIC25 | Futuro DLR | 2025-12-01 | 2025-12-30 | 13 | 23,448 | 0.78 ARS | 1,462 ARS |
| M:bm_MERV_GFGC75573O_24hs | Opción GFGC | 2025-08-14 | 2025-09-04 | 11 | 35,804 | 2.89 | 113.37 |
| M:bm_MERV_GFGC71785O_24hs | Opción GFGC | 2025-08-14 | 2025-09-04 | 11 | 35,382 | 4.40 | 155.37 |

**Nota sobre spreads:**
- DLR futuros: spread ~1 ARS sobre precio ~1,450 ARS = **0.07% del precio** → viable para estrategias HFT
- BYMA USD (AL30D, GGAL, PBR): spread ~0.015-0.06 USD sobre precio 4-60 USD = **0.1-0.4%** → viable con comisión baja
- BYMA ARS (AL30): spread ~18 ARS sobre precio ~87,000 ARS = **0.02%** → muy líquido

---

## PostgreSQL — tabla `orders`

| Instrumento | Desde | Hasta | Días | Órdenes | Vol Total | Precio Avg |
|---|---|---|---|---|---|---|
| rx_DDF_DLR_OCT25 | 2025-10-02 | 2025-10-31 | 21 | 39,166 | 2,650,702 | 1,446 ARS |
| rx_DDF_DLR_SEP25 | 2025-09-03 | 2025-09-30 | 19 | 24,485 | 2,097,559 | 1,409 ARS |
| rx_DDF_DLR_NOV25 | 2025-11-03 | 2025-11-28 | 14 | 18,610 | 1,500,193 | 1,443 ARS |
| rx_DDF_DLR_AGO25 | 2025-08-12 | 2025-08-29 | 12 | 17,690 | 1,529,290 | 1,337 ARS |
| rx_DDF_DLR_DIC25 | 2025-12-01 | 2025-12-30 | 14 | 7,489 | 1,007,137 | 1,460 ARS |
| bm_MERV_GFGC77573O_24hs | 2025-08-19 | 2025-09-04 | 11 | 6,470 | 69,470 | 66 ARS |
| bm_MERV_GFGC82025O_24hs | 2025-08-12 | 2025-09-04 | 14 | 5,525 | 62,329 | 50 ARS |

**Nota:** BYMA equities (GGAL, PBR, AL30) NO tienen datos en `orders`. Solo hay ticks. Para backtesting de BYMA se necesita usar cambios en bid/ask como proxy de trades.

---

## PostgreSQL — tabla `binance_ticks`

| Símbolo | Desde | Hasta | Barras (1min) | Precio Avg | Vol Avg |
|---|---|---|---|---|---|
| BTCUSDT | 2025-08-05 | 2026-03-18 | 6,807 | 83,159 USD | 0.60 BTC |
| USDTARS | 2025-08-05 | 2026-03-18 | 6,780 | 1,444 ARS | 95.82 USDT |

**Nota:** USDTARS en Binance tiene precio promedio casi idéntico al DLR futuro (~1,444 ARS). Correlación esperada alta.

---

## PostgreSQL — tabla `ppi_ohlcv` (nueva — ingesta BT-08)

| Tipo | Tickers | Filas | Desde | Hasta |
|---|---|---|---|---|
| ACCIONES | 15 (GGAL, YPFD, BMA, PAMP, TXAR, ALUA, BBAR, CRES, SUPV, TECO2, TGNO4, TGSU2, VALO, MIRG, LOMA) | 900 | 2025-12-22 | 2026-03-20 |
| BONOS | 11 (AL30, AL30D, GD30, GD30D, AL35, GD35, AE38, GD41, GD46, AL29, GD29) | 660 | 2025-12-22 | 2026-03-20 |
| CEDEARS | 10 (AAPL, MSFT, GOOGL, AMZN, TSLA, NVDA, META, PBR, MELI, GLOB) | 600 | 2025-12-22 | 2026-03-20 |

**Columnas:** `ticker`, `type`, `date`, `open`, `high`, `low`, `close`, `volume`
**Actualizar:** `PYTHONPATH=. python3 -m finance.HFT.backtest.ppi_historical_ingest --days 90`

---

**Estado:** No accesible remotamente desde este host (error 1130). Requiere acceso desde servidor MySQL o túnel.

---

## Análisis de Viabilidad por Instrumento

| Instrumento | Liquidez | Spread/Precio | Datos Orders | Recomendación |
|---|---|---|---|---|
| rx_DDF_DLR_OCT25 | Alta (39K orders) | 0.11% | ✅ | **Prioridad 1** — mejor dataset |
| rx_DDF_DLR_SEP25 | Alta (24K orders) | 0.09% | ✅ | **Prioridad 1** |
| rx_DDF_DLR_NOV25 | Media (18K orders) | 0.07% | ✅ | **Prioridad 2** |
| rx_DDF_DLR_AGO25 | Media (17K orders) | 0.06% | ✅ | **Prioridad 2** |
| BTCUSDT | Alta | ~0.01% | Solo OHLCV | **Prioridad 3** — adaptar loader |
| USDTARS | Media | ~0.01% | Solo OHLCV | **Prioridad 3** |
| bm_MERV_GGALD_24hs | Media (744K ticks) | 0.41% | ❌ | **Prioridad 4** — sin orders |
| bm_MERV_GFGC* | Baja | 1-4% | Parcial | **Prioridad 5** — spread muy alto |

---

## Días Disponibles con Datos Completos (ticks + orders)

### OCT25 (21 días)
2025-10-02, 03, 06, 07, 08, 09, 13, 14, 16, 17, 20, 21, 22, 23, 24, 27, 28, 29, 30, 31

### SEP25 (19 días)
2025-09-03, 04, 05, 08, 09, 10, 11, 12, 15, 16, 17, 18, 19, 22, 23, 24, 25, 26, 29, 30

### NOV25 (14 días)
2025-11-03, 04, 05, 06, 07, 10, 11, 12, 13, 14, 17, 18, 19, 20, 21, 24, 25, 26, 27, 28

### AGO25 (12 días)
2025-08-12, 13, 14, 15, 18, 19, 20, 21, 22, 25, 26, 27, 28, 29

---

## PostgreSQL — tabla `ppi_options_chain` (nueva — ingesta BT-09)

**Subyacente:** GGAL | **Tickers totales en cadena:** 368 (192 calls GFGC*, 176 puts GFGV*)

| Vencimiento | Tipo | Tickers con datos | Filas | Strike min | Strike max |
|---|---|---|---|---|---|
| 2026-04-17 | C (call) | 27 | 971 | 10,126 ARS | 96,801 ARS |
| 2026-04-17 | P (put) | 22 | 581 | 43,747 ARS | 96,801 ARS |
| 2026-06-19 | C (call) | 18 | 293 | 6,000 ARS | 91,501 ARS |
| 2026-06-19 | P (put) | 14 | 169 | 4,600 ARS | 85,501 ARS |

**Total:** 81 opciones con datos históricos, 2,014 filas
**Columnas:** `underlying`, `ticker`, `option_type` (C/P), `strike`, `expiry`, `date`, `open/high/low/close/volume`
**Actualizar:** `PYTHONPATH=. python3 -m finance.HFT.backtest.ppi_options_ingest --days 90`
