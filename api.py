"""
TaiwanAlpha - Delivery Layer (FastAPI)
Monetized REST API with tiered access control.

Tiers:
  free    → 10 req/day, last 7 days of price data only
  starter → 500 req/day, 90 days, institutional flow included   ($29/mo)
  pro     → unlimited, 3 years, alpha signals + alerts          ($99/mo)
  enterprise → custom SLA, raw data export, webhooks            (custom)
"""

from fastapi import FastAPI, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import duckdb
import pandas as pd
from pathlib import Path
from datetime import datetime, date
from typing import Optional
import hashlib
import json

# ── App Setup ────────────────────────────────────────────────
app = FastAPI(
    title="TaiwanAlpha API",
    description="Institutional investor flow & alpha signals for Taiwan equities",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

DB_PATH = Path(__file__).parent.parent / "data" / "taiwanalpha.duckdb"

# ── Tier Definitions ─────────────────────────────────────────
TIER_LIMITS = {
    "free":       {"daily_req": 10,   "history_days": 7,   "signals": False, "price_usd": 0},
    "starter":    {"daily_req": 500,  "history_days": 90,  "signals": False, "price_usd": 29},
    "pro":        {"daily_req": 9999, "history_days": 1095,"signals": True,  "price_usd": 99},
    "enterprise": {"daily_req": 99999,"history_days": 3650,"signals": True,  "price_usd": -1},
}

# Mock API key store (in production: Redis or Postgres)
MOCK_KEYS = {
    "demo-free-key-001":       "free",
    "demo-starter-key-001":    "starter",
    "demo-pro-key-001":        "pro",
    "demo-enterprise-key-001": "enterprise",
}


def get_db():
    if not DB_PATH.exists():
        raise HTTPException(503, "Database not initialized. Run storage/schema.py first.")
    return duckdb.connect(str(DB_PATH), read_only=True)


def resolve_tier(api_key: Optional[str]) -> str:
    if not api_key:
        return "free"
    return MOCK_KEYS.get(api_key, "free")


def tier_guard(tier: str, feature: str):
    limits = TIER_LIMITS[tier]
    if feature == "signals" and not limits["signals"]:
        raise HTTPException(403, detail={
            "error": "upgrade_required",
            "message": "Alpha signals require Pro tier or above ($99/mo). "
                       "See /pricing for details.",
            "upgrade_url": "https://taiwanalpha.io/pricing"
        })


# ── Endpoints ────────────────────────────────────────────────

@app.get("/", tags=["Meta"])
def root():
    return {
        "product": "TaiwanAlpha API",
        "tagline": "Institutional-grade Taiwan equity data for quant traders",
        "version": "1.0.0",
        "endpoints": ["/v1/price", "/v1/institutional", "/v1/signals", "/v1/screener"],
        "docs": "/docs",
        "pricing": "/pricing",
    }


@app.get("/pricing", tags=["Meta"])
def pricing():
    return {
        "tiers": [
            {"name": "Free",       "price": "$0/mo",     "req_day": 10,   "history": "7 days"},
            {"name": "Starter",    "price": "$29/mo",    "req_day": 500,  "history": "90 days"},
            {"name": "Pro",        "price": "$99/mo",    "req_day": "∞",  "history": "3 years",
             "includes": ["alpha signals", "margin data", "sector screener"]},
            {"name": "Enterprise", "price": "Contact us","req_day": "∞",  "history": "10 years",
             "includes": ["raw parquet export", "webhooks", "SLA", "custom models"]},
        ]
    }


@app.get("/v1/price/{stock_no}", tags=["Market Data"])
def get_price(
    stock_no: str,
    days: int = Query(30, ge=1, le=1095),
    x_api_key: Optional[str] = Header(None),
):
    """
    Daily OHLCV price data for a Taiwan listed stock.
    - **Free**: last 7 days
    - **Starter+**: up to 90 days
    - **Pro+**: up to 3 years
    """
    tier = resolve_tier(x_api_key)
    max_days = TIER_LIMITS[tier]["history_days"]
    actual_days = min(days, max_days)

    try:
        con = get_db()
        df = con.execute("""
            SELECT stock_no, trade_date, open_price, high_price,
                   low_price, close_price, volume, change_pct
            FROM stock_daily
            WHERE stock_no = ?
            ORDER BY trade_date DESC
            LIMIT ?
        """, [stock_no, actual_days]).df()
        con.close()
    except Exception as e:
        raise HTTPException(500, str(e))

    if df.empty:
        raise HTTPException(404, f"No data found for stock {stock_no}")

    return {
        "stock_no": stock_no,
        "tier": tier,
        "returned_days": len(df),
        "max_days_for_tier": max_days,
        "data": df.to_dict(orient="records"),
    }


@app.get("/v1/institutional/{stock_no}", tags=["Institutional Flow"])
def get_institutional(
    stock_no: str,
    days: int = Query(20, ge=1, le=365),
    x_api_key: Optional[str] = Header(None),
):
    """
    Three-institution (三大法人) net buy/sell flow.
    Requires **Starter** tier or above.
    """
    tier = resolve_tier(x_api_key)
    if tier == "free":
        raise HTTPException(403, detail={
            "error": "upgrade_required",
            "message": "Institutional flow data requires Starter plan ($29/mo).",
            "upgrade_url": "https://taiwanalpha.io/pricing"
        })

    max_days = TIER_LIMITS[tier]["history_days"]
    actual_days = min(days, max_days)

    try:
        con = get_db()
        df = con.execute("""
            SELECT * FROM institutional_flow
            WHERE stock_no = ?
            ORDER BY trade_date DESC
            LIMIT ?
        """, [stock_no, actual_days]).df()
        con.close()
    except Exception as e:
        raise HTTPException(500, str(e))

    return {
        "stock_no": stock_no,
        "tier": tier,
        "data": df.to_dict(orient="records"),
    }


@app.get("/v1/signals/{stock_no}", tags=["Alpha Signals"])
def get_signals(
    stock_no: str,
    days: int = Query(10, ge=1, le=90),
    x_api_key: Optional[str] = Header(None),
):
    """
    Composite alpha signal combining institutional flow + margin sentiment.
    Returns BUY / NEUTRAL / SELL with confidence scores.
    Requires **Pro** tier or above.
    """
    tier = resolve_tier(x_api_key)
    tier_guard(tier, "signals")

    try:
        con = get_db()
        df = con.execute("""
            SELECT * FROM alpha_signal
            WHERE stock_no = ?
            ORDER BY signal_date DESC
            LIMIT ?
        """, [stock_no, days]).df()
        con.close()
    except Exception as e:
        raise HTTPException(500, str(e))

    return {
        "stock_no": stock_no,
        "tier": tier,
        "signal_model": "institutional_momentum_v1",
        "data": df.to_dict(orient="records"),
    }


@app.get("/v1/screener", tags=["Alpha Signals"])
def screener(
    signal: str = Query("BUY", regex="^(BUY|SELL|NEUTRAL)$"),
    min_score: float = Query(0.6, ge=0.0, le=1.0),
    limit: int = Query(20, ge=1, le=100),
    x_api_key: Optional[str] = Header(None),
):
    """
    Screen all stocks by signal type and minimum combined score.
    Requires **Pro** tier or above.
    """
    tier = resolve_tier(x_api_key)
    tier_guard(tier, "signals")

    try:
        con = get_db()
        df = con.execute("""
            SELECT a.stock_no, a.signal_date, a.combined_score, a.signal,
                   c.company_name, c.industry
            FROM alpha_signal a
            LEFT JOIN company_info c USING (stock_no)
            WHERE a.signal = ?
              AND a.combined_score >= ?
              AND a.signal_date = (
                  SELECT MAX(signal_date) FROM alpha_signal WHERE stock_no = a.stock_no
              )
            ORDER BY a.combined_score DESC
            LIMIT ?
        """, [signal, min_score, limit]).df()
        con.close()
    except Exception as e:
        raise HTTPException(500, str(e))

    return {
        "filter": {"signal": signal, "min_score": min_score},
        "tier": tier,
        "results": len(df),
        "data": df.to_dict(orient="records"),
    }


@app.get("/health", tags=["Meta"])
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
