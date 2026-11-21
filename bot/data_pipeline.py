"""
Day 2 Data Pipeline & Integrity Checker for TradingStock AI Trading Desk.
- Downloads real historical data (yfinance: RESEARCH ONLY, never for live decisions).
- Normalizes all timestamps strictly to UTC.
- Runs integrity checks: duplicates, zero-volume bars, OHLC sanity, missing gaps, extreme spikes.
- Saves raw files to data/raw/ and cleaned files to data/clean/.
- Logs every download into data/sources.md.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
CLEAN_DIR = ROOT / "data" / "clean"
SOURCES_MD = ROOT / "data" / "sources.md"

US_UNIVERSE = [
    # Liquid ETFs
    "SPY", "QQQ", "IWM", "SMH", "XLF", "XLE", "XLK", "GLD",
    # Liquid Large-Cap Stocks
    "NVDA", "AAPL", "MSFT", "AMZN", "META", "TSLA", "AMD", "GOOGL", "JPM", "PLTR",
]

MY_UNIVERSE = [
    # Liquid Bursa Malaysia stocks with affordable 100-share board lots (fit USD 1,000 ≈ RM 4,400)
    "1155.KL",  # Maybank
    "1295.KL",  # Public Bank
    "1023.KL",  # CIMB
    "4863.KL",  # Telekom Malaysia
    "4197.KL",  # Sime Darby
    "6888.KL",  # Axiata
    "1066.KL",  # RHB Bank
    "8869.KL",  # Press Metal
    "5183.KL",  # Petronas Chemicals
    "6012.KL",  # Maxis
    "5296.KL",  # MR DIY
    "0166.KL",  # Inari Amertron
    "5211.KL",  # Sunway
    "0138.KL",  # MYEG / Zetrix
    "5168.KL",  # Hartalega
    "7113.KL",  # Top Glove
]


def normalize_utc(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    idx = pd.to_datetime(df.index)
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    else:
        idx = idx.tz_convert("UTC")
    df.index = idx
    df.index.name = "timestamp_utc"
    keep = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    return df[keep]


def check_and_clean(df: pd.DataFrame, symbol: str, interval: str) -> tuple[pd.DataFrame, dict]:
    report = {
        "symbol": symbol,
        "interval": interval,
        "raw_rows": int(len(df)),
        "duplicates_dropped": 0,
        "nan_rows_dropped": 0,
        "bad_ohlc_dropped": 0,
        "zero_vol_rows": 0,
        "extreme_jump_flags": 0,
        "clean_rows": 0,
        "start_utc": None,
        "end_utc": None,
        "status": "OK",
    }
    if df.empty:
        report["status"] = "EMPTY"
        return df, report

    df = df.sort_index()

    # 1. Duplicate timestamps
    dup_mask = df.index.duplicated(keep="last")
    report["duplicates_dropped"] = int(dup_mask.sum())
    if report["duplicates_dropped"] > 0:
        df = df[~dup_mask]

    # 2. NaN in OHLC
    nan_mask = df[["open", "high", "low", "close"]].isna().any(axis=1)
    report["nan_rows_dropped"] = int(nan_mask.sum())
    if report["nan_rows_dropped"] > 0:
        df = df[~nan_mask]

    # 3. Invalid OHLC (non-positive or high < low or open/close outside [low, high])
    bad_ohlc = (
        (df["open"] <= 0)
        | (df["high"] <= 0)
        | (df["low"] <= 0)
        | (df["close"] <= 0)
        | (df["high"] < df["low"])
        | (df["high"] < df[["open", "close"]].max(axis=1) - 1e-8)
        | (df["low"] > df[["open", "close"]].min(axis=1) + 1e-8)
    )
    report["bad_ohlc_dropped"] = int(bad_ohlc.sum())
    if report["bad_ohlc_dropped"] > 0:
        df = df[~bad_ohlc]

    # 4. Zero-volume bars (flag and drop for intraday; flag only for daily)
    if "volume" in df.columns:
        zero_vol = df["volume"].fillna(0) <= 0
        report["zero_vol_rows"] = int(zero_vol.sum())
        if interval != "1d" and report["zero_vol_rows"] > 0:
            df = df[~zero_vol]

    # 5. Extreme single-bar jump (>50% move) flag for review (do not fabricate/clip)
    pct = df["close"].pct_change().abs()
    report["extreme_jump_flags"] = int((pct > 0.50).sum())

    report["clean_rows"] = int(len(df))
    if len(df) > 0:
        report["start_utc"] = df.index[0].strftime("%Y-%m-%d %H:%M")
        report["end_utc"] = df.index[-1].strftime("%Y-%m-%d %H:%M")
    else:
        report["status"] = "EMPTY_AFTER_CLEAN"

    return df, report


def download_batch(market: str, symbols: list[str], interval: str, period: str) -> list[dict]:
    reports = []
    raw_sub = RAW_DIR / market.lower() / interval
    clean_sub = CLEAN_DIR / market.lower() / interval
    raw_sub.mkdir(parents=True, exist_ok=True)
    clean_sub.mkdir(parents=True, exist_ok=True)

    for sym in symbols:
        try:
            ticker = yf.Ticker(sym)
            raw_df = ticker.history(period=period, interval=interval, auto_adjust=True, actions=False)
            norm_df = normalize_utc(raw_df)
            safe_sym = sym.replace(".", "_")
            if not norm_df.empty:
                norm_df.to_parquet(raw_sub / f"{safe_sym}.parquet")
            clean_df, rep = check_and_clean(norm_df, sym, interval)
            if not clean_df.empty:
                clean_df.to_parquet(clean_sub / f"{safe_sym}.parquet")
            reports.append(rep)
        except Exception as e:
            reports.append({
                "symbol": sym,
                "interval": interval,
                "raw_rows": 0,
                "clean_rows": 0,
                "status": f"ERROR: {type(e).__name__}: {e}",
            })
    return reports


def append_sources_log(market: str, interval: str, reports: list[dict]) -> None:
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    ok_reps = [r for r in reports if r.get("status") == "OK"]
    err_reps = [r for r in reports if r.get("status") != "OK"]
    starts = [r["start_utc"] for r in ok_reps if r.get("start_utc")]
    ends = [r["end_utc"] for r in ok_reps if r.get("end_utc")]
    min_start = min(starts) if starts else "N/A"
    max_end = max(ends) if ends else "N/A"
    tot_dups = sum(r.get("duplicates_dropped", 0) for r in ok_reps)
    tot_bad = sum(r.get("bad_ohlc_dropped", 0) for r in ok_reps)
    tot_zvol = sum(r.get("zero_vol_rows", 0) for r in ok_reps)
    tot_jump = sum(r.get("extreme_jump_flags", 0) for r in ok_reps)
    check_summary = (
        f"OK={len(ok_reps)}/{len(reports)}, dup={tot_dups}, bad_ohlc={tot_bad}, "
        f"zero_vol={tot_zvol}, jump>50%={tot_jump}"
    )
    if err_reps:
        check_summary += f", err={[r['symbol'] for r in err_reps]}"

    line = (
        f"| {now_utc} | {market} | yfinance (研究专用) | "
        f"{len(reports)} 只 / `{interval}` | {min_start} ~ {max_end} | "
        f"`data/clean/{market.lower()}/{interval}/` | {check_summary} |\n"
    )
    with open(SOURCES_MD, "a", encoding="utf-8") as f:
        f.write(line)


def main() -> None:
    all_summary = {}
    jobs = [
        ("US", US_UNIVERSE, "1d", "5y"),
        ("US", US_UNIVERSE, "1h", "730d"),
        ("US", US_UNIVERSE, "5m", "60d"),
        ("MY", MY_UNIVERSE, "1d", "5y"),
        ("MY", MY_UNIVERSE, "1h", "730d"),
        ("MY", MY_UNIVERSE, "5m", "60d"),
    ]
    for market, syms, interval, period in jobs:
        print(f"Downloading {market} {interval} ({period}) for {len(syms)} symbols...")
        reps = download_batch(market, syms, interval, period)
        append_sources_log(market, interval, reps)
        all_summary[f"{market}_{interval}"] = reps
        ok = sum(1 for r in reps if r.get("status") == "OK")
        print(f"  -> {market} {interval}: {ok}/{len(syms)} OK")

    audit_path = ROOT / "data" / "integrity_audit.json"
    with open(audit_path, "w", encoding="utf-8") as f:
        json.dump(all_summary, f, indent=2)
    print(f"Audit report saved to {audit_path}")


if __name__ == "__main__":
    main()
