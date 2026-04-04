# CHECKLIST DE IMPLEMENTACIÓN - AlgoTrading Refactoring

**Fecha de Inicio:** 2026-03-13  
**Objetivo:** Implementar mejoras identificadas en la auditoría de arquitectura

---

## 🔥 FASE 1: ESTABILIZACIÓN (Semanas 1-8)

### Semana 1: Seguridad y Configuración

- [x] **Tarea 1.1: Crear sistema de configuración centralizado**
  - [x] Instalar `pydantic-settings`: `pip install pydantic-settings`
  - [x] Crear `finance/config/settings.py` con clase `Settings`
  - [x] Crear `.env` desde `.env.example`
  - [x] Agregar `.env` a `.gitignore` (ya hecho ✅)
  - [x] Verificar que `.env` NO está en git: `git status`

- [x] **Tarea 1.2: Migrar credenciales hardcodeadas**
  - [x] `PPI/account_ppi.py` líneas 30-31 → `settings.PPI_PUBLIC_KEY`
  - [x] `dashboard_project/dashboard/views.py` líneas 6-9 → `settings.DB_*`
  - [x] `BINANCE/db_config.py` → `settings.DB_*`
  - [x] `db/config.py` → `settings.DB_*`
  - [x] `web_scraping/matriz/config.py` → `settings.DB_*`
  - [x] `HFT/backtest/db/config.py` → `settings.DB_*`
  - [x] Verificar que NO quedan credenciales: `grep -r "password.*=" --include="*.py"`

- [x] **Tarea 1.3: Testing de configuración**
  - [x] Ejecutar `python finance/HFT/backtest/main.py` → Verificar carga de config
  - [x] Ejecutar `python finance/BINANCE/monitor/main.py` → Verificar carga de config
  - [x] Ejecutar `python finance/dashboard/main.py` → Verificar carga de config

**Tiempo Estimado:** 8-12 horas  
**Responsable:** [Asignar]  
**Fecha Límite:** [Fecha]

---

### Semana 2: Eliminar Duplicación de Código

- [x] **Tarea 2.1: Centralizar clases PPI**
  - [x] Mantener solo `finance/PPI/classes/` como fuente de verdad
  - [x] Crear `finance/PPI/classes/__init__.py` con exports
  - [x] Eliminar `finance/dashboard/classes/` (backup primero)
  - [x] Eliminar `finance/HFT/backtest/PPI/classes/` (backup primero)

- [x] **Tarea 2.2: Actualizar imports**
  - [x] Buscar todos los imports: `grep -r "from classes" --include="*.py"`
  - [x] Reemplazar: `from classes.market_ppi` → `from finance.PPI.classes.market_ppi`
  - [x] Reemplazar: `from .classes` → `from finance.PPI.classes`
  - [x] Archivos a modificar:
    - [x] `dashboard/main.py`
    - [x] `HFT/backtest/main.py`
    - [x] `HFT/backtest/formatData/fetch.py`
    - [x] `HFT/backtest/livedata/order_book.py`
    - [x] Otros (buscar con grep)

- [x] **Tarea 2.3: Testing de imports**
  - [x] Ejecutar cada módulo principal
  - [x] Verificar que no hay `ImportError`
  - [x] Verificar funcionalidad básica

**Tiempo Estimado:** 6-8 horas  
**Responsable:** [Asignar]  
**Fecha Límite:** [Fecha]

---

### Semana 3-4: Logging Estructurado

- [x] **Tarea 3.1: Setup de loguru**
  - [x] Instalar: `pip install loguru`
  - [x] Crear `finance/utils/logger.py`
  - [x] Configurar rotación de logs (500 MB, 10 días)
  - [x] Crear directorio `logs/`

- [x] **Tarea 3.2: Reemplazar prints por logger**
  - [x] Módulos prioritarios:
    - [x] `HFT/backtest/main.py`
    - [x] `BINANCE/monitor/data_stream.py`
    - [x] `PPI/account_ppi.py`
    - [x] `PPI/classes/market_ppi.py`
    - [x] `web_scraping/A3/dolar.py`
  - [x] Patrón: `print("mensaje")` → `logger.info("mensaje")`
  - [x] Patrón: `print(f"Error: {e}")` → `logger.error(f"Error: {e}")`

- [x] **Tarea 3.3: Agregar context logging**
  - [x] Agregar `logger.bind(module=__name__)` en cada módulo
  - [x] Agregar timestamps automáticos
  - [x] Configurar niveles por módulo

**Tiempo Estimado:** 10-12 horas  
**Responsable:** [Asignar]  
**Fecha Límite:** [Fecha]

---

### Semana 5-6: Tests Unitarios (Cobertura 30%)

- [x] **Tarea 4.1: Setup de pytest**
  - [x] Instalar: `pip install pytest pytest-cov pytest-asyncio`
  - [x] Crear `tests/` directory
  - [x] Crear `tests/conftest.py` con fixtures
  - [x] Crear `pytest.ini` con configuración

- [x] **Tarea 4.2: Tests para módulos críticos**
  - [x] `tests/test_ppi_classes.py`
    - [x] Test `Market_data.get_instruments()`
    - [x] Test `Account.login_to_api()`
    - [x] Test `Opciones.black_scholes_model()`
  - [x] `tests/test_backtesting.py`
    - [x] Test `MarketDataBacktester.load_market_data()`
    - [x] Test `MarketDataBacktester.calculate_metrics()`
  - [x] `tests/test_indicators.py`
    - [x] Test `compute_rsi()`
  - [x] `tests/test_config.py`
    - [x] Test carga de `.env`
    - [x] Test validación de settings

- [x] **Tarea 4.3: Ejecutar tests**
  - [x] `pytest --cov=finance --cov-report=html`
  - [x] Verificar cobertura ≥ 30% (actual: 30% ✅ — 82 tests)
  - [x] Revisar reporte HTML en `htmlcov/index.html`

**Tiempo Estimado:** 16-20 horas  
**Responsable:** [Asignar]  
**Fecha Límite:** [Fecha]

---

### Semana 7-8: Refactoring de MarketDataBacktester

- [x] **Tarea 5.1: Extraer clases**
  - [x] Crear `HFT/backtest/engine/backtester.py`
  - [x] Crear `HFT/backtest/engine/position_manager.py`
  - [x] Crear `HFT/backtest/engine/order_executor.py`
  - [x] Crear `HFT/backtest/metrics/calculator.py`
  - [x] Crear `HFT/backtest/metrics/reporter.py`

- [x] **Tarea 5.2: Migrar lógica**
  - [x] Mover gestión de posiciones a `PositionManager`
  - [x] Mover ejecución de órdenes a `OrderExecutor`
  - [x] Mover cálculo de métricas a `MetricsCalculator`
  - [x] Mover generación de reportes a `Reporter`
  - [x] Mantener `MarketDataBacktester` como orquestador

- [x] **Tarea 5.3: Testing**
  - [x] Tests unitarios para cada clase nueva
  - [x] Test de integración end-to-end
  - [x] Verificar que resultados son idénticos

**Tiempo Estimado:** 12-16 horas  
**Responsable:** [Asignar]  
**Fecha Límite:** [Fecha]

---

## ⚡ FASE 2: OPTIMIZACIÓN (Semanas 9-16)

### Semana 9-10: Implementar Redis

- [x] **Tarea 6.1: Setup de Redis**
  - [x] Instalar Redis: `sudo apt install redis-server` (Linux)
  - [x] Instalar cliente Python: `pip install redis`
  - [x] Configurar Redis en `settings.py`
  - [x] Crear `finance/utils/cache.py` con wrapper

- [x] **Tarea 6.2: Implementar caché**
  - [x] Cachear datos de mercado (TTL: 5 segundos)
  - [x] Cachear datos históricos (TTL: 1 hora)
  - [x] Cachear resultados de backtesting (TTL: 24 horas)
  - [x] Implementar invalidación de caché

- [x] **Tarea 6.3: Testing de performance**
  - [x] Benchmark sin caché
  - [x] Benchmark con caché
  - [x] Verificar mejora ≥ 3x (actual: 41x market data, 283x historical)

**Tiempo Estimado:** 8-10 horas  
**Responsable:** [Asignar]  
**Fecha Límite:** [Fecha]

---

### Semana 11-12: Migrar a asyncio

- [x] **Tarea 7.1: Migrar WebSocket de Binance**
  - [x] Reemplazar `ThreadedWebsocketManager` por `asyncio`
  - [x] Usar `python-binance` async API
  - [x] Implementar múltiples streams concurrentes

- [x] **Tarea 7.2: Migrar web scraping**
  - [x] Ya usa `aiohttp` ✅
  - [x] Optimizar concurrencia
  - [x] Agregar rate limiting

- [x] **Tarea 7.3: Testing**
  - [x] Tests con `pytest-asyncio`
  - [x] Verificar throughput mejorado

**Tiempo Estimado:** 12-16 horas  
**Responsable:** [Asignar]  
**Fecha Límite:** [Fecha]

---

### Semana 13-14: Optimizar Base de Datos

- [x] **Tarea 8.1: Agregar índices**
  - [x] Índice en `market_data.timestamp`
  - [x] Índice en `market_data.instrument`
  - [x] Índice compuesto en `(instrument, timestamp)`
  - [x] Índice en `trades.timestamp`

- [x] **Tarea 8.2: Implementar connection pooling**
  - [x] Configurar SQLAlchemy pool
  - [x] Pool size: 10-20 conexiones
  - [x] Max overflow: 5

- [x] **Tarea 8.3: Optimizar queries**
  - [x] Identificar queries lentos (EXPLAIN ANALYZE)
  - [x] Agregar LIMIT a queries sin paginación
  - [x] Usar bulk inserts

**Tiempo Estimado:** 6-8 horas  
**Responsable:** [Asignar]  
**Fecha Límite:** [Fecha]

---

### Semana 15-16: Aumentar Cobertura de Tests

- [x] **Tarea 9.1: Tests adicionales**
  - [x] Tests para web scraping
  - [x] Tests para dashboards
  - [x] Tests para VaR y Monte Carlo
  - [x] Tests de integración

- [x] **Tarea 9.2: Alcanzar 60% cobertura**
  - [x] Ejecutar `pytest --cov=finance --cov-report=html`
  - [x] Identificar módulos sin cobertura
  - [x] Agregar tests faltantes

**Tiempo Estimado:** 12-16 horas  
**Responsable:** [Asignar]  
**Fecha Límite:** [Fecha]

---

## 📋 FASE 3: ESCALABILIDAD (Semanas 17-24)

### Semana 17-19: Extraer Data Ingestion Service

- [x] **Tarea 10.1: Crear microservicio**
  - [x] Crear `services/data_ingestion/`
  - [x] Implementar FastAPI endpoints
  - [x] Migrar lógica de web scraping
  - [x] Migrar lógica de Binance monitor

- [x] **Tarea 10.2: Implementar RabbitMQ**
  - [x] Instalar RabbitMQ
  - [x] Instalar `pika`: `pip install pika`
  - [x] Crear producer en data ingestion
  - [x] Crear consumer en backtesting

- [x] **Tarea 10.3: Dockerizar**
  - [x] Crear `Dockerfile`
  - [x] Crear `docker-compose.yml`
  - [x] Testing en containers

**Tiempo Estimado:** 20-24 horas  
**Responsable:** [Asignar]  
**Fecha Límite:** [Fecha]

---

### Semana 20-22: Migrar Dashboard

- [x] **Tarea 11.1: Estandarizar en Dash**
  - [x] Migrar funcionalidad de Django a Dash
  - [x] Deprecar Streamlit
  - [x] Crear API backend con FastAPI

- [x] **Tarea 11.2: Implementar WebSocket**
  - [x] WebSocket para datos en tiempo real
  - [x] Actualización automática de gráficos

- [x] **Tarea 11.3: Autenticación**
  - [x] Implementar JWT
  - [x] Sistema de roles (admin, user)

**Tiempo Estimado:** 16-20 horas  
**Responsable:** [Asignar]  
**Fecha Límite:** [Fecha]

---

### Semana 23-24: Monitoring y CI/CD

- [x] **Tarea 12.1: Setup Prometheus + Grafana**
  - [x] Instalar Prometheus
  - [x] Instalar Grafana
  - [x] Crear dashboards de métricas

- [x] **Tarea 12.2: CI/CD con GitHub Actions**
  - [x] Crear `.github/workflows/test.yml`
  - [x] Ejecutar tests en cada push
  - [x] Verificar cobertura mínima

- [x] **Tarea 12.3: Deployment**
  - [x] Setup en servidor de staging
  - [x] Deployment automatizado
  - [x] Rollback plan

**Tiempo Estimado:** 12-16 horas  
**Responsable:** [Asignar]  
**Fecha Límite:** [Fecha]

---

## 📊 MÉTRICAS DE PROGRESO

### Fase 1: Estabilización
- [x] 0 credenciales hardcodeadas
- [x] 0 código duplicado
- [x] 30% cobertura de tests
- [x] 100% módulos con logging

### Fase 2: Optimización
- [ ] Latencia <200ms (con caché)
- [x] Throughput 3-5x mayor
- [x] 60% cobertura de tests

### Fase 3: Escalabilidad
- [ ] 50+ instrumentos monitoreados
- [ ] 20+ usuarios concurrentes
- [ ] 99.5% disponibilidad
- [x] CI/CD funcional

---

## 🚨 RIESGOS Y CONTINGENCIAS

### Riesgo 1: Regresiones durante refactoring
**Mitigación:** Implementar tests ANTES de refactorizar  
**Plan B:** Rollback a versión anterior (usar git tags)

### Riesgo 2: Pérdida de datos en migración
**Mitigación:** Backups automáticos antes de cada cambio  
**Plan B:** Restore desde backup

### Riesgo 3: Downtime en producción
**Mitigación:** Blue-green deployment  
**Plan B:** Rollback inmediato

---

## 📝 NOTAS

- Hacer commit después de cada tarea completada
- Crear branch por feature: `git checkout -b feature/task-X.X`
- Pull request con revisión antes de merge
- Documentar cambios en CHANGELOG.md

---

**Última actualización:** 2026-03-15  
**Próxima revisión:** [Fecha después de Fase 1]
