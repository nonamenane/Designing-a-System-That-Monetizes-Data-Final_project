"""
TaiwanAlpha - Storage Layer
Uses DuckDB for fast analytical queries + Parquet for raw storage.
Schema mirrors a medallion architecture: raw -> silver -> gold.
"""

import duckdb
import pandas as pd
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "taiwanalpha.duckdb"
DATA_DIR = Path(__file__).parent.parent / "data"


def get_connection():
    """Get persistent DuckDB connection."""
    return duckdb.connect(str(DB_PATH))


def init_schema():
    """Initialize all tables in DuckDB."""
    con = get_connection()
    con.execute("""
        -- Silver: cleaned daily price data
        CREATE TABLE IF NOT EXISTS stock_daily (
            stock_no        VARCHAR NOT NULL,
            trade_date      DATE NOT NULL,
            open_price      DOUBLE,
            high_price      DOUBLE,
            low_price       DOUBLE,
            close_price     DOUBLE,
            volume          BIGINT,
            change_pct      DOUBLE,
            PRIMARY KEY (stock_no, trade_date)
        );

        -- Silver: three-institution (三大法人) net buy/sell
        CREATE TABLE IF NOT EXISTS institutional_flow (
            stock_no        VARCHAR NOT NULL,
            trade_date      DATE NOT NULL,
            foreign_net     BIGINT,   -- 外資淨買賣
            invest_trust_net BIGINT,  -- 投信淨買賣
            dealer_net      BIGINT,   -- 自營商淨買賣
            total_net       BIGINT,
            PRIMARY KEY (stock_no, trade_date)
        );

        -- Silver: margin trading (融資融券)
        CREATE TABLE IF NOT EXISTS margin_trading (
            stock_no        VARCHAR NOT NULL,
            trade_date      DATE NOT NULL,
            margin_balance  BIGINT,   -- 融資餘額
            short_balance   BIGINT,   -- 融券餘額
            margin_change   BIGINT,
            short_change    BIGINT,
            PRIMARY KEY (stock_no, trade_date)
        );

        -- Gold: composite alpha signal (pre-computed)
        CREATE TABLE IF NOT EXISTS alpha_signal (
            stock_no        VARCHAR NOT NULL,
            signal_date     DATE NOT NULL,
            inst_score      DOUBLE,   -- institutional momentum score
            margin_score    DOUBLE,   -- margin sentiment score
            combined_score  DOUBLE,   -- composite
            signal          VARCHAR,  -- 'BUY' / 'NEUTRAL' / 'SELL'
            PRIMARY KEY (stock_no, signal_date)
        );

        -- Metadata: company info
        CREATE TABLE IF NOT EXISTS company_info (
            stock_no        VARCHAR PRIMARY KEY,
            company_name    VARCHAR,
            industry        VARCHAR,
            market          VARCHAR,
            listed_date     DATE
        );

        -- API usage tracking
        CREATE TABLE IF NOT EXISTS api_usage (
            api_key         VARCHAR,
            endpoint        VARCHAR,
            called_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            plan_tier       VARCHAR
        );
    """)
    con.close()
    logger.info("Schema initialized successfully.")


def load_parquet_to_silver(parquet_dir: Path = DATA_DIR):
    """
    Load raw Parquet files from ingestion into silver tables.
    Basic cleaning: type casting, dedup, null handling.
    """
    con = get_connection()

    for pq_file in parquet_dir.glob("*_raw.parquet"):
        stock_no = pq_file.stem.replace("_raw", "")
        df = pd.read_parquet(pq_file)
        if df.empty:
            continue

        # Normalize column names (TWSE returns Chinese column headers)
        df.columns = [c.strip() for c in df.columns]
        df["stock_no"] = stock_no

        # Register and upsert
        con.register("temp_df", df)
        con.execute("""
            INSERT OR REPLACE INTO stock_daily
            SELECT
                stock_no,
                TRY_CAST(REPLACE("日期", '/', '-') AS DATE) AS trade_date,
                TRY_CAST(REPLACE("開盤價", ',', '') AS DOUBLE) AS open_price,
                TRY_CAST(REPLACE("最高價", ',', '') AS DOUBLE) AS high_price,
                TRY_CAST(REPLACE("最低價", ',', '') AS DOUBLE) AS low_price,
                TRY_CAST(REPLACE("收盤價", ',', '') AS DOUBLE) AS close_price,
                TRY_CAST(REPLACE("成交股數", ',', '') AS BIGINT) AS volume,
                TRY_CAST(REPLACE("漲跌價差", ',', '') AS DOUBLE) AS change_pct
            FROM temp_df
            WHERE "日期" IS NOT NULL
        """)

    con.close()
    logger.info("Parquet files loaded into silver layer.")


def compute_alpha_signals(lookback_days: int = 20):
    """
    Gold layer: compute composite alpha signal from institutional + margin data.
    Simple momentum: if foreign investors net-bought > 3 consecutive days → BUY
    """
    con = get_connection()
    con.execute(f"""
        INSERT OR REPLACE INTO alpha_signal
        WITH inst_momentum AS (
            SELECT
                stock_no,
                signal_date,
                AVG(foreign_net) OVER w AS avg_foreign_net,
                SUM(CASE WHEN foreign_net > 0 THEN 1 ELSE 0 END) OVER w AS buy_days,
                STDDEV(foreign_net) OVER w AS std_flow
            FROM institutional_flow
            WINDOW w AS (
                PARTITION BY stock_no
                ORDER BY signal_date
                ROWS BETWEEN {lookback_days} PRECEDING AND CURRENT ROW
            )
        ),
        scored AS (
            SELECT
                stock_no,
                signal_date,
                COALESCE(buy_days / {lookback_days}.0, 0) AS inst_score,
                0.5 AS margin_score,  -- placeholder until margin table is populated
                (COALESCE(buy_days / {lookback_days}.0, 0) * 0.7 + 0.5 * 0.3) AS combined_score
            FROM inst_momentum
        )
        SELECT
            stock_no,
            signal_date,
            inst_score,
            margin_score,
            combined_score,
            CASE
                WHEN combined_score >= 0.65 THEN 'BUY'
                WHEN combined_score <= 0.35 THEN 'SELL'
                ELSE 'NEUTRAL'
            END AS signal
        FROM scored
    """)
    con.close()
    logger.info("Alpha signals computed and stored.")


def query_signals(stock_no: str = None, days: int = 30) -> pd.DataFrame:
    """Query alpha signals for a stock or all stocks."""
    con = get_connection()
    where = f"WHERE stock_no = '{stock_no}'" if stock_no else ""
    df = con.execute(f"""
        SELECT * FROM alpha_signal
        {where}
        ORDER BY signal_date DESC
        LIMIT {days * (1 if stock_no else 50)}
    """).df()
    con.close()
    return df


if __name__ == "__main__":
    init_schema()
    print("Storage layer ready. Tables created in:", DB_PATH)
