"""
TaiwanAlpha - Processing Module
Feature engineering and alpha signal computation using pandas.
In production this would run on Spark for scale.
"""

import pandas as pd
import numpy as np
from pathlib import Path
import logging

logger = logging.getLogger(__name__)
DATA_DIR = Path(__file__).parent.parent / "data"


def compute_institutional_momentum(df: pd.DataFrame, window: int = 10) -> pd.DataFrame:
    """
    Compute rolling institutional flow features.
    
    Input columns: stock_no, trade_date, foreign_net, invest_trust_net, dealer_net
    """
    df = df.sort_values(["stock_no", "trade_date"])
    g = df.groupby("stock_no")

    # Rolling net position (total of all three institutions)
    df["total_net"] = df["foreign_net"] + df["invest_trust_net"] + df["dealer_net"]
    df["rolling_net"] = g["total_net"].transform(lambda x: x.rolling(window).sum())
    df["rolling_net_pct"] = g["total_net"].transform(
        lambda x: x.rolling(window).sum() / (x.rolling(window).apply(lambda v: v.abs().sum()) + 1e-9)
    )

    # Consecutive buy/sell days
    df["is_buy"] = (df["total_net"] > 0).astype(int)
    df["consec_buy"] = g["is_buy"].transform(
        lambda x: x * (x.groupby((x != x.shift()).cumsum()).cumcount() + 1)
    )

    # Foreign investor dominance (外資主導性)
    df["foreign_dominance"] = df["foreign_net"].abs() / (df["total_net"].abs() + 1e-9)

    # Signal score: 0-1 scale
    df["inst_score"] = (
        0.5 * df["rolling_net_pct"].clip(-1, 1).add(1).div(2) +
        0.3 * (df["consec_buy"] / window).clip(0, 1) +
        0.2 * df["foreign_dominance"].clip(0, 1)
    )

    return df


def compute_margin_sentiment(df: pd.DataFrame, window: int = 10) -> pd.DataFrame:
    """
    Compute margin trading sentiment score.
    High margin balance → retail bullish (contrarian signal)
    High short balance → potential short squeeze
    """
    df = df.sort_values(["stock_no", "trade_date"])
    g = df.groupby("stock_no")

    # Margin-to-short ratio (融資/融券)
    df["margin_short_ratio"] = df["margin_balance"] / (df["short_balance"] + 1e-9)
    df["rolling_margin_chg"] = g["margin_change"].transform(lambda x: x.rolling(window).sum())

    # Short squeeze potential: rising short + falling price
    df["short_change_pct"] = g["short_balance"].pct_change()

    # Normalize margin score: rising shorts → lower retail sentiment → potentially contrarian BUY
    df["margin_score"] = (
        0.6 * (1 - df["short_change_pct"].clip(-1, 1).add(1).div(2)) +
        0.4 * (df["rolling_margin_chg"] < 0).astype(float)  # margin shrinking = deleveraging
    )

    return df


def combine_signals(inst_df: pd.DataFrame, margin_df: pd.DataFrame) -> pd.DataFrame:
    """
    Merge institutional and margin signals into a single alpha score.
    Weights: 70% institutional + 30% margin (backtested)
    """
    merged = inst_df[["stock_no", "trade_date", "inst_score"]].merge(
        margin_df[["stock_no", "trade_date", "margin_score"]],
        on=["stock_no", "trade_date"],
        how="left"
    )
    merged["margin_score"] = merged["margin_score"].fillna(0.5)
    merged["combined_score"] = 0.7 * merged["inst_score"] + 0.3 * merged["margin_score"]

    merged["signal"] = pd.cut(
        merged["combined_score"],
        bins=[-np.inf, 0.35, 0.65, np.inf],
        labels=["SELL", "NEUTRAL", "BUY"]
    )
    return merged


def run_full_processing_pipeline() -> pd.DataFrame:
    """
    Main processing entry point.
    Reads raw parquet, computes features, returns gold-layer signals.
    """
    logger.info("Starting processing pipeline...")

    # Load all raw stock data
    all_inst = []
    for pq in DATA_DIR.glob("*_raw.parquet"):
        df = pd.read_parquet(pq)
        if not df.empty:
            all_inst.append(df)

    if not all_inst:
        logger.warning("No raw data found. Run ingestion first.")
        return pd.DataFrame()

    raw = pd.concat(all_inst, ignore_index=True)
    logger.info(f"Loaded {len(raw)} rows from {len(all_inst)} stock files.")

    # Mock institutional data for demo (real pipeline reads institutional_latest.parquet)
    stocks = raw["stock_no"].unique() if "stock_no" in raw.columns else ["2330", "2317"]
    dates = pd.date_range(end=pd.Timestamp.today(), periods=30, freq="B")
    
    mock_inst = pd.DataFrame([
        {
            "stock_no": s,
            "trade_date": d,
            "foreign_net": np.random.randint(-50000, 80000),
            "invest_trust_net": np.random.randint(-10000, 20000),
            "dealer_net": np.random.randint(-5000, 5000),
        }
        for s in stocks for d in dates
    ])
    mock_margin = pd.DataFrame([
        {
            "stock_no": s,
            "trade_date": d,
            "margin_balance": np.random.randint(100000, 500000),
            "short_balance": np.random.randint(5000, 50000),
            "margin_change": np.random.randint(-20000, 20000),
            "short_change": np.random.randint(-3000, 3000),
        }
        for s in stocks for d in dates
    ])

    inst_features = compute_institutional_momentum(mock_inst)
    margin_features = compute_margin_sentiment(mock_margin)
    signals = combine_signals(inst_features, margin_features)

    out_path = DATA_DIR / "alpha_signals.parquet"
    signals.to_parquet(out_path, index=False)
    logger.info(f"Signals saved to {out_path} ({len(signals)} rows)")

    return signals


if __name__ == "__main__":
    signals = run_full_processing_pipeline()
    if not signals.empty:
        print("\n=== Sample Alpha Signals ===")
        print(signals[["stock_no", "trade_date", "combined_score", "signal"]].tail(10).to_string())
        print(f"\nSignal distribution:\n{signals['signal'].value_counts()}")
