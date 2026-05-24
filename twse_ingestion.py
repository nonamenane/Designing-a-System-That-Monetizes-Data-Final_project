"""
TaiwanAlpha - Data Ingestion Module
Fetches institutional investor (法人籌碼) data from TWSE Open API
"""

import requests
import pandas as pd
import json
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# TWSE Open Data API (public, no key required)
TWSE_BASE = "https://openapi.twse.com.tw/v1"
TPEX_BASE = "https://www.tpex.org.tw/openapi/v1"

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)


def fetch_twse_institutional(date: str = None) -> pd.DataFrame:
    """
    Fetch Three-Institution (三大法人) buy/sell data from TWSE.
    date format: 'YYYYMMDD', defaults to today
    """
    url = f"{TWSE_BASE}/exchangeReport/BFIAUU"
    params = {}
    if date:
        params["response"] = "json"
        params["date"] = date

    logger.info(f"Fetching TWSE institutional data for date={date or 'latest'}")
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        df = pd.DataFrame(data)
        df["fetch_date"] = date or datetime.today().strftime("%Y%m%d")
        df["source"] = "TWSE"
        return df
    except Exception as e:
        logger.error(f"TWSE fetch failed: {e}")
        return pd.DataFrame()


def fetch_twse_margin_trading(date: str = None) -> pd.DataFrame:
    """
    Fetch margin trading (融資融券) data from TWSE.
    """
    url = f"{TWSE_BASE}/exchangeReport/MI_MARGN"
    logger.info(f"Fetching TWSE margin trading data")
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        df = pd.DataFrame(data)
        df["fetch_date"] = date or datetime.today().strftime("%Y%m%d")
        df["source"] = "TWSE_MARGIN"
        return df
    except Exception as e:
        logger.error(f"Margin fetch failed: {e}")
        return pd.DataFrame()


def fetch_twse_stock_day(stock_no: str, date: str = None) -> pd.DataFrame:
    """
    Fetch daily trading summary for a specific stock.
    stock_no: e.g., '2330' for TSMC
    """
    url = f"{TWSE_BASE}/exchangeReport/STOCK_DAY"
    params = {"stockNo": stock_no}
    if date:
        params["date"] = date

    logger.info(f"Fetching daily data for stock {stock_no}")
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        df = pd.DataFrame(data)
        df["stock_no"] = stock_no
        return df
    except Exception as e:
        logger.error(f"Stock day fetch failed for {stock_no}: {e}")
        return pd.DataFrame()


def fetch_twse_listed_companies() -> pd.DataFrame:
    """
    Fetch full list of TWSE listed companies with sector info.
    """
    url = f"{TWSE_BASE}/exchangeReport/TWTB4U"
    logger.info("Fetching TWSE listed companies")
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return pd.DataFrame(data)
    except Exception as e:
        logger.error(f"Listed companies fetch failed: {e}")
        return pd.DataFrame()


def batch_ingest(stock_list: list, days_back: int = 30) -> dict:
    """
    Batch ingest pipeline: fetch data for multiple stocks over N days.
    Saves raw JSON to data/ directory.
    Returns summary dict.
    """
    results = {"success": [], "failed": [], "total_rows": 0}
    end_date = datetime.today()

    for stock in stock_list:
        dfs = []
        for i in range(days_back):
            d = (end_date - timedelta(days=i)).strftime("%Y%m%d")
            df = fetch_twse_stock_day(stock, d)
            if not df.empty:
                dfs.append(df)
            time.sleep(0.3)  # polite rate limiting

        if dfs:
            combined = pd.concat(dfs, ignore_index=True)
            out_path = DATA_DIR / f"{stock}_raw.parquet"
            combined.to_parquet(out_path, index=False)
            results["success"].append(stock)
            results["total_rows"] += len(combined)
            logger.info(f"  Saved {len(combined)} rows for {stock}")
        else:
            results["failed"].append(stock)

    # Also fetch institutional data
    inst_df = fetch_twse_institutional()
    if not inst_df.empty:
        inst_df.to_parquet(DATA_DIR / "institutional_latest.parquet", index=False)
        results["institutional_rows"] = len(inst_df)

    logger.info(f"Batch ingest complete: {results}")
    return results


if __name__ == "__main__":
    # Demo: fetch top 5 Taiwan stocks
    stocks = ["2330", "2317", "2454", "2881", "2412"]
    summary = batch_ingest(stocks, days_back=5)
    print(json.dumps(summary, indent=2))
