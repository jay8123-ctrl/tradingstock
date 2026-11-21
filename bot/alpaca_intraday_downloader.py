"""
Alpaca Official 4+ Year Intraday Downloader (US Equities)
- Reads ALPACA_PAPER_API_KEY and ALPACA_PAPER_API_SECRET from .env (NEVER hardcoded).
- Downloads 4+ years of 5Min / 15Min / 1Hour official US equity bars in UTC.
- Runs integrity checks and logs provenance into data/sources.md.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dotenv import load_dotenv
import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from data_pipeline import US_UNIVERSE, check_and_clean, append_sources_log

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw" / "us_alpaca"
CLEAN_DIR = ROOT / "data" / "clean" / "us_alpaca"


def download_alpaca_bars(years: int = 4, minutes: int = 15) -> None:
    load_dotenv(ROOT / ".env")
    api_key = os.getenv("ALPACA_PAPER_API_KEY", "").strip()
    api_secret = os.getenv("ALPACA_PAPER_API_SECRET", "").strip()
    if not api_key or not api_secret:
        raise RuntimeError(
            "Missing ALPACA_PAPER_API_KEY / ALPACA_PAPER_API_SECRET in .env. "
            "Copy .env.example to .env and add your free Alpaca Paper keys first."
        )

    client = StockHistoricalDataClient(api_key, api_secret)
    tf = TimeFrame(minutes, TimeFrameUnit.Minute)
    label = f"{minutes}m"
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=365 * years + 30)

    raw_sub = RAW_DIR / label
    clean_sub = CLEAN_DIR / label
    raw_sub.mkdir(parents=True, exist_ok=True)
    clean_sub.mkdir(parents=True, exist_ok=True)

    reports = []
    for sym in US_UNIVERSE:
        try:
            req = StockBarsRequest(
                symbol_or_symbols=sym,
                timeframe=tf,
                start=start_dt,
                end=end_dt,
                adjustment="all",
                feed="iex",  # free tier feed; switch to 'sip' if subscribed
            )
            bars = client.get_stock_bars(req).df
            if bars.empty:
                reports.append({"symbol": sym, "interval": label, "status": "EMPTY"})
                continue
            if isinstance(bars.index, pd.MultiIndex):
                bars = bars.xs(sym, level="symbol")
            bars.index = pd.to_datetime(bars.index, utc=True)
            bars.index.name = "timestamp_utc"
            keep = [c for c in ["open", "high", "low", "close", "volume"] if c in bars.columns]
            bars = bars[keep]
            bars.to_parquet(raw_sub / f"{sym}.parquet")
            clean_df, rep = check_and_clean(bars, sym, label)
            if not clean_df.empty:
                clean_df.to_parquet(clean_sub / f"{sym}.parquet")
            reports.append(rep)
            print(f"  {sym}: {rep['clean_rows']} clean bars ({rep['start_utc']} ~ {rep['end_utc']})")
        except Exception as e:
            reports.append({"symbol": sym, "interval": label, "status": f"ERROR: {e}"})
            print(f"  {sym}: ERROR {e}")

    append_sources_log("US_ALPACA", label, reports)
    print("Done! Logged to data/sources.md.")


if __name__ == "__main__":
    download_alpaca_bars(years=4, minutes=15)
