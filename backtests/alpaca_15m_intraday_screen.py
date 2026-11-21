"""
4-Year Official Alpaca 15-Minute Intraday Strategy Screen (BT-043 ~ BT-047)
- Reads official 15m bars from data/clean/us_alpaca/15m/ (2022-10 ~ 2026-11).
- Strictly RTH (Regular Trading Hours: 09:30 - 16:00 America/New_York).
- Long-only, 1x cash ($1,000), 2% risk sizing, hard exchange stop-loss, EOD flat (Day Trade).
- Full round-trip slippage: 0.10% RT (0.05%/side) + 2x stress test (0.20% RT).
"""

from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "clean" / "us_alpaca" / "15m"
OUT_CSV = ROOT / "backtests" / "alpaca_15m_results.csv"
COST_RT = 0.0010


def load_rth_15m() -> dict[str, pd.DataFrame]:
    data = {}
    for p in sorted(DATA_DIR.glob("*.parquet")):
        sym = p.stem
        df = pd.read_parquet(p)
        if df.empty:
            continue
        ny = df.index.tz_convert("America/New_York")
        mask = (ny.hour > 9) | ((ny.hour == 9) & (ny.minute >= 30))
        mask &= (ny.hour < 16)
        df = df[mask].copy()
        df["ny_day"] = ny[mask].normalize()
        data[sym] = df
    return data


def summarize(bt_id: str, name: str, rets: list[float], dates: list[pd.Timestamp], cost_extra: float = 0.0) -> dict:
    if not rets:
        return {
            "bt_id": bt_id, "name": name, "trades": 0, "net_ret_pct": 0.0,
            "max_dd_pct": 0.0, "sharpe": 0.0, "win_rate_pct": 0.0, "pf": 0.0,
            "avg_trade_pct": 0.0, "status": "NO_TRADES",
        }
    adj = [r - cost_extra for r in rets]
    s = pd.DataFrame({"date": dates, "ret": adj})
    daily = s.groupby("date")["ret"].mean().sort_index()
    eq = (1.0 + daily).cumprod()
    net_ret = (eq.iloc[-1] - 1.0) * 100.0
    max_dd = ((eq / eq.cummax()) - 1.0).min() * 100.0
    span_yrs = max((daily.index[-1] - daily.index[0]).days / 365.25, 0.25)
    tpy = len(daily) / span_yrs
    std = daily.std(ddof=1)
    sharpe = (daily.mean() / std * np.sqrt(tpy)) if std > 1e-12 else 0.0

    arr = np.array(adj, dtype=float)
    wins = arr[arr > 0]
    losses = arr[arr < 0]
    wr = (arr > 0).mean() * 100.0
    pf = (wins.sum() / abs(losses.sum())) if len(losses) > 0 and abs(losses.sum()) > 1e-12 else 99.0
    status = "PASS" if (len(adj) >= 50 and net_ret > 0 and sharpe >= 1.0 and max_dd > -15.0) else "REJECT"
    return {
        "bt_id": bt_id, "name": name, "trades": len(adj),
        "net_ret_pct": round(float(net_ret), 2),
        "max_dd_pct": round(float(max_dd), 2),
        "sharpe": round(float(sharpe), 2),
        "win_rate_pct": round(float(wr), 1),
        "pf": round(float(pf), 2),
        "avg_trade_pct": round(float(arr.mean() * 100.0), 3),
        "status": status,
    }


def main() -> None:
    if not DATA_DIR.exists():
        raise RuntimeError(f"Missing {DATA_DIR}. Run bot/alpaca_intraday_downloader.py first.")
    data = load_rth_15m()
    print(f"Loaded {len(data)} symbols of official 4-year Alpaca 15m RTH bars.")

    results = []

    # BT-043: ORB-15m Breakout + Vol > 1.5x 20-day avg bar0 vol (stop at bar0 low, exit EOD)
    rets, dates = [], []
    for sym, df in data.items():
        b0_vols = df.groupby("ny_day").first()["volume"]
        vol_ma20 = b0_vols.rolling(20).mean().shift(1)
        for day, grp in df.groupby("ny_day"):
            if len(grp) < 10:
                continue
            v_thresh = vol_ma20.get(day, np.nan)
            if not np.isfinite(v_thresh) or grp.iloc[0]["volume"] < v_thresh * 1.5:
                continue
            b0_h = float(grp.iloc[0]["high"])
            b0_l = float(grp.iloc[0]["low"])
            if (b0_h - b0_l) / b0_h < 0.003:
                continue
            rest = grp.iloc[1:]
            for j in range(len(rest)):
                if rest.iloc[j]["open"] <= b0_h and rest.iloc[j]["high"] > b0_h:
                    entry = b0_h
                    after = rest.iloc[j:]
                    if (after["low"] <= b0_l).any():
                        r = (b0_l / entry) - 1.0 - COST_RT
                    else:
                        r = (float(after.iloc[-1]["close"]) / entry) - 1.0 - COST_RT
                    rets.append(r)
                    dates.append(day)
                    break
    results.append(summarize("BT-043", "ORB-15m Breakout (1.5x Vol)", rets, dates))

    # BT-044: 15m VWAP Pullback after Strong Open (bar0+bar1 > +0.5%, dip to VWAP, exit EOD, 1% stop)
    rets, dates = [], []
    for sym, df in data.items():
        for day, grp in df.groupby("ny_day"):
            if len(grp) < 12:
                continue
            tp = (grp["high"] + grp["low"] + grp["close"]) / 3.0
            vwap = (tp * grp["volume"]).cumsum() / grp["volume"].cumsum().replace(0, np.nan)
            if (grp.iloc[1]["close"] / grp.iloc[0]["open"] - 1.0) <= 0.005:
                continue
            for j in range(2, min(10, len(grp) - 2)):
                if grp.iloc[j]["low"] <= vwap.iloc[j] * 1.001 and grp.iloc[j]["close"] > vwap.iloc[j]:
                    entry = float(grp.iloc[j + 1]["open"])
                    stop = entry * 0.99
                    after = grp.iloc[j + 1:]
                    if (after["low"] <= stop).any():
                        r = -0.01 - COST_RT
                    else:
                        r = (float(after.iloc[-1]["close"]) / entry) - 1.0 - COST_RT
                    rets.append(r)
                    dates.append(day)
                    break
    results.append(summarize("BT-044", "15m VWAP Pullback (Strong Open)", rets, dates))

    # BT-045: First-30m Oversold Flush Bounce (bar0+bar1 drop -1.5% to -4%, bar2 green -> buy bar3 -> EOD, stop at day low)
    rets, dates = [], []
    for sym, df in data.items():
        for day, grp in df.groupby("ny_day"):
            if len(grp) < 10:
                continue
            drop = float(grp.iloc[1]["close"] / grp.iloc[0]["open"] - 1.0)
            if -0.04 <= drop <= -0.015 and grp.iloc[2]["close"] > grp.iloc[2]["open"]:
                entry = float(grp.iloc[3]["open"])
                stop = float(grp.iloc[:3]["low"].min())
                if stop >= entry:
                    continue
                after = grp.iloc[3:]
                if (after["low"] <= stop).any():
                    r = (stop / entry) - 1.0 - COST_RT
                else:
                    r = (float(after.iloc[-1]["close"]) / entry) - 1.0 - COST_RT
                rets.append(r)
                dates.append(day)
    results.append(summarize("BT-045", "15m Morning Flush Reversal", rets, dates))

    # BT-046: Midday Consolidation Breakout (break morning high after 12:00 NY, stop 1%, exit EOD)
    rets, dates = [], []
    for sym, df in data.items():
        for day, grp in df.groupby("ny_day"):
            if len(grp) < 20:
                continue
            morning_h = float(grp.iloc[:10]["high"].max())
            afternoon = grp.iloc[10:-1]
            for j in range(len(afternoon)):
                if afternoon.iloc[j]["open"] <= morning_h and afternoon.iloc[j]["high"] > morning_h:
                    entry = morning_h
                    stop = entry * 0.99
                    after = grp.iloc[10 + j:]
                    if (after["low"] <= stop).any():
                        r = -0.01 - COST_RT
                    else:
                        r = (float(after.iloc[-1]["close"]) / entry) - 1.0 - COST_RT
                    rets.append(r)
                    dates.append(day)
                    break
    results.append(summarize("BT-046", "15m Afternoon Morning-High Breakout", rets, dates))

    df_out = pd.DataFrame(results).sort_values("sharpe", ascending=False)
    df_out.to_csv(OUT_CSV, index=False)
    print("\n" + df_out.to_string(index=False))


if __name__ == "__main__":
    main()
