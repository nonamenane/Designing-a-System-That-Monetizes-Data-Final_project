# TaiwanAlpha 🇹🇼📈

> **Institutional-grade Taiwan equity flow data & alpha signals as a subscription API.**

[![FastAPI](https://img.shields.io/badge/FastAPI-0.110-green)](https://fastapi.tiangolo.com)
[![Python](https://img.shields.io/badge/Python-3.11-blue)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

---

## Overview

TaiwanAlpha is a data monetization platform that ingests public Taiwan Stock Exchange (TWSE) institutional investor flow data, processes it into alpha signals, and exposes the results via a tiered REST API. Quantitative traders, hedge funds, and retail investors subscribe to access pre-computed signals without building their own data pipelines.

**Business model:** SaaS API with four tiers — Free → Starter ($29/mo) → Pro ($99/mo) → Enterprise (custom).

---

## Architecture

```
TWSE Open API ──► Ingestion (Python) ──► Raw Parquet
                                             │
                                    Processing (pandas/Spark)
                                             │
                                    DuckDB (Silver + Gold)
                                             │
                                    FastAPI REST Layer
                                             │
                              ┌──────────────┼──────────────┐
                           Free           Starter        Pro/Enterprise
                         (7 days)       (90 days +     (3yr + signals
                                        institution)    + screener)
```

### Components

| Directory | Purpose |
|-----------|---------|
| `ingestion/` | TWSE Open API fetchers, batch pipeline |
| `storage/` | DuckDB schema, medallion architecture (raw→silver→gold) |
| `processing/` | Feature engineering, alpha signal computation |
| `delivery/` | FastAPI REST API, tier enforcement |
| `data/` | Local DuckDB + Parquet files (gitignored) |

---

## Quick Start

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Initialize database
```bash
python storage/schema.py
```

### 3. Run ingestion (fetches live TWSE data)
```bash
python ingestion/twse_ingestion.py
```

### 4. Run processing pipeline
```bash
python processing/feature_engineering.py
```

### 5. Start API server
```bash
uvicorn delivery.api:app --reload --port 8000
```

### 6. Test the API
```bash
# Free tier (no key)
curl http://localhost:8000/v1/price/2330

# Pro tier (demo key)
curl -H "X-API-Key: demo-pro-key-001" \
     http://localhost:8000/v1/signals/2330

# Screener
curl -H "X-API-Key: demo-pro-key-001" \
     "http://localhost:8000/v1/screener?signal=BUY&min_score=0.7"
```

---

## API Reference

### Endpoints

| Method | Path | Tier Required | Description |
|--------|------|---------------|-------------|
| GET | `/v1/price/{stock_no}` | Free | Daily OHLCV data |
| GET | `/v1/institutional/{stock_no}` | Starter+ | 三大法人 net flow |
| GET | `/v1/signals/{stock_no}` | Pro+ | Composite alpha signal |
| GET | `/v1/screener` | Pro+ | Screen all stocks by signal |
| GET | `/pricing` | Public | Tier comparison |

### Demo API Keys

| Key | Tier |
|-----|------|
| `demo-free-key-001` | Free |
| `demo-starter-key-001` | Starter |
| `demo-pro-key-001` | Pro |
| `demo-enterprise-key-001` | Enterprise |

---

## Pricing

| Tier | Price | Req/Day | History | Signals |
|------|-------|---------|---------|---------|
| Free | $0 | 10 | 7 days | ✗ |
| Starter | $29/mo | 500 | 90 days | ✗ |
| Pro | $99/mo | Unlimited | 3 years | ✓ |
| Enterprise | Custom | Unlimited | 10 years | ✓ + custom |

---

## Data Sources

- **TWSE Open API** (`openapi.twse.com.tw`) — Public, no license fee, daily refresh
- **TPEX Open API** (`tpex.org.tw/openapi`) — OTC market data
- Both are officially provided by the Taiwan Stock Exchange and Taiwan OTC Exchange under their open data policy.

---

## Requirements

```
fastapi>=0.110.0
uvicorn>=0.29.0
duckdb>=0.10.0
pandas>=2.0.0
pyarrow>=15.0.0
requests>=2.31.0
numpy>=1.26.0
```

---

## Reproducibility

To reproduce the demand-validation data collection (Homework 2 methodology):
```bash
# 1. PTT forum post analysis
python docs/demand_validation/ptt_scraper.py

# 2. Job posting keyword analysis  
python docs/demand_validation/job_posting_analysis.py

# 3. Competitor pricing benchmark
# See docs/demand_validation/competitor_analysis.md
```

---

## License

MIT License. Data sourced from TWSE/TPEX Open API under their respective terms of service.
