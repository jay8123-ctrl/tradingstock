"""
Day 3 Round 2 Screening (BT-024 ~ BT-033)
Testing higher-selectivity US Day-Trade ideas (with regime filters, VWAP, cross-sectional leaders)
AND benchmarking short-term Swing (2-5d) vs Day Trade on US & MY to see where real edge survives full costs.
"""

from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd

from day3_fast_screen import load_market, summarize_trades, US_COST_RT, MY_COST_RT

ROOT = Path(__file__).resolve().parent.parent
OUT_CSV = ROOT / "backtests" / "day3_round2_results.csv"


def main() -> None:
    us_1d = load_market("US", "1d")
    us_1h = load_market("US", "1h")
    my_1d = load_market("MY", "1d", exclude={"0138.KL"})

    results = []

    # Helper: SPY regime filter (SPY Close[t-1] > SMA50[t-1])
    spy_1d = us_1d["SPY"]
    spy_bull = (spy_1d["close"] > spy_1d["close"].rolling(50).mean()).shift(1).fillna(False)
    spy_bull.index = spy_bull.index.normalize()

    # BT-024: US Turnaround Monday Dip + Bull Regime + 2% Stop (ID-20v2)
    rets, dates = [], []
    for sym, df in us_1d.items():
        prev_ret = df["close"].pct_change().shift(1)
        gap = (df["open"] / df["close"].shift(1)) - 1.0
        days = df.index.normalize()
        bull = days.map(spy_bull).fillna(False).to_numpy(dtype=bool)
        sig = (df.index.day_of_week == 0) & (prev_ret < -0.005) & (gap < -0.003) & bull
        for dt in df.index[sig]:
            entry = float(df.loc[dt, "open"])
            stop = entry * 0.98
            if float(df.loc[dt, "low"]) <= stop:
                r = -0.02 - US_COST_RT
            else:
                r = (float(df.loc[dt, "close"]) / entry) - 1.0 - US_COST_RT
            rets.append(r)
            dates.append(dt)
    results.append(summarize_trades("BT-024", "ID-20v2", "US Turnaround Monday (Bull+2%SL)", "US", "1d(5y)", rets, dates))

    # BT-025: US 1h VWAP Pullback in Bull Regime (ID-02)
    rets, dates = [], []
    for sym, df in us_1h.items():
        df = df.copy()
        df["day"] = df.index.normalize()
        for day, grp in df.groupby("day"):
            if len(grp) < 5 or not bool(spy_bull.get(day, False)):
                continue
            tp = (grp["high"] + grp["low"] + grp["close"]) / 3.0
            vwap = (tp * grp["volume"]).cumsum() / grp["volume"].cumsum().replace(0, np.nan)
            # Bar 0 closes above VWAP, Bar 1 dips to touch VWAP and closes above it -> buy Bar 2 open -> EOD, stop 1.5%
            if grp.iloc[0]["close"] > vwap.iloc[0] and grp.iloc[1]["low"] <= vwap.iloc[1] * 1.002 and grp.iloc[1]["close"] > vwap.iloc[1]:
                entry = float(grp.iloc[2]["open"])
                stop = entry * 0.985
                rest = grp.iloc[2:]
                if (rest["low"] <= stop).any():
                    r = -0.015 - US_COST_RT
                else:
                    r = (float(rest.iloc[-1]["close"]) / entry) - 1.0 - US_COST_RT
                rets.append(r)
                dates.append(day)
    results.append(summarize_trades("BT-025", "ID-02", "US 1h VWAP Pullback (Bull)", "US", "1h(~3y)", rets, dates))

    # BT-026: US Cross-Sectional 1h Top-2 Leaders (ID-16)
    # Build daily bar0 return and bar1->EOD return per symbol
    b0_rets = {}
    rest_rets = {}
    for sym, df in us_1h.items():
        df = df.copy()
        df["day"] = df.index.normalize()
        for day, grp in df.groupby("day"):
            if len(grp) < 4:
                continue
            b0 = grp.iloc[0]
            r0 = float(b0["close"] / b0["open"] - 1.0)
            entry = float(grp.iloc[1]["open"])
            stop = entry * 0.98
            rest = grp.iloc[1:]
            if (rest["low"] <= stop).any():
                r_rest = -0.02 - US_COST_RT
            else:
                r_rest = float(rest.iloc[-1]["close"] / entry - 1.0) - US_COST_RT
            b0_rets.setdefault(day, {})[sym] = r0
            rest_rets.setdefault(day, {})[sym] = r_rest

    rets, dates = [], []
    for day in sorted(b0_rets.keys()):
        if not bool(spy_bull.get(day, False)):
            continue
        ranked = sorted(b0_rets[day].items(), key=lambda x: x[1], reverse=True)
        top2 = [s for s, r0 in ranked[:2] if r0 > 0.005]
        for s in top2:
            rets.append(rest_rets[day][s])
            dates.append(day)
    results.append(summarize_trades("BT-026", "ID-16", "US 1h Top-2 Leaders (Bull)", "US", "1h(~3y)", rets, dates))

    # BT-027: US Cross-Sectional 1h Bottom-2 Oversold Reversion (ID-16-Rev)
    rets, dates = [], []
    for day in sorted(b0_rets.keys()):
        if not bool(spy_bull.get(day, False)):
            continue
        ranked = sorted(b0_rets[day].items(), key=lambda x: x[1])
        bot2 = [s for s, r0 in ranked[:2] if r0 < -0.015]
        for s in bot2:
            rets.append(rest_rets[day][s])
            dates.append(day)
    results.append(summarize_trades("BT-027", "ID-16R", "US 1h Bottom-2 Oversold Bounce (Bull)", "US", "1h(~3y)", rets, dates))

    # BT-028: US ETF Relative Strength 1h Leader (ID-14)
    etfs = {"SPY", "QQQ", "IWM", "SMH", "XLF", "XLE", "XLK", "GLD"}
    rets, dates = [], []
    for day in sorted(b0_rets.keys()):
        etf_scores = [(s, r) for s, r in b0_rets[day].items() if s in etfs]
        if not etf_scores:
            continue
        best_s, best_r = max(etf_scores, key=lambda x: x[1])
        if best_r > 0.003:
            rets.append(rest_rets[day][best_s])
            dates.append(day)
    results.append(summarize_trades("BT-028", "ID-14", "US 1h Strongest ETF Leader", "US", "1h(~3y)", rets, dates))

    # --- BENCHMARK: Short-Term Swing (2-5 days) to compare cost drag ---
    # BT-029: US RSI(2)<10 in Uptrend (Close > SMA200), hold until Close > SMA5 (max 5d), 5% stop
    rets, dates = [], []
    for sym, df in us_1d.items():
        sma200 = df["close"].rolling(200).mean()
        sma5 = df["close"].rolling(5).mean()
        delta = df["close"].diff()
        gain = delta.clip(lower=0).rolling(2).mean()
        loss = (-delta.clip(upper=0)).rolling(2).mean()
        rsi2 = 100.0 - (100.0 / (1.0 + gain / loss.replace(0, np.nan)))
        i = 200
        n = len(df)
        while i < n - 1:
            if df["close"].iloc[i] > sma200.iloc[i] and rsi2.iloc[i] < 10:
                entry = float(df["open"].iloc[i + 1])
                stop = entry * 0.95
                exit_idx = min(i + 5, n - 1)
                exit_p = float(df["close"].iloc[exit_idx])
                for j in range(i + 1, min(i + 6, n)):
                    if float(df["low"].iloc[j]) <= stop:
                        exit_p = stop
                        exit_idx = j
                        break
                    if float(df["close"].iloc[j]) > float(sma5.iloc[j]):
                        exit_p = float(df["close"].iloc[j])
                        exit_idx = j
                        break
                rets.append((exit_p / entry) - 1.0 - US_COST_RT)
                dates.append(df.index[i + 1])
                i = exit_idx + 1
            else:
                i += 1
    results.append(summarize_trades("BT-029", "SW-01", "US 2-5d RSI(2)<10 Uptrend Swing", "US", "1d(5y)", rets, dates))

    # BT-030: MY RSI(2)<10 in Uptrend (Close > SMA200), hold until Close > SMA5 (max 5d), 5% stop
    rets, dates = [], []
    for sym, df in my_1d.items():
        sma200 = df["close"].rolling(200).mean()
        sma5 = df["close"].rolling(5).mean()
        delta = df["close"].diff()
        gain = delta.clip(lower=0).rolling(2).mean()
        loss = (-delta.clip(upper=0)).rolling(2).mean()
        rsi2 = 100.0 - (100.0 / (1.0 + gain / loss.replace(0, np.nan)))
        i = 200
        n = len(df)
        while i < n - 1:
            if df["close"].iloc[i] > sma200.iloc[i] and rsi2.iloc[i] < 10:
                entry = float(df["open"].iloc[i + 1])
                stop = entry * 0.95
                exit_idx = min(i + 5, n - 1)
                exit_p = float(df["close"].iloc[exit_idx])
                for j in range(i + 1, min(i + 6, n)):
                    if float(df["low"].iloc[j]) <= stop:
                        exit_p = stop
                        exit_idx = j
                        break
                    if float(df["close"].iloc[j]) > float(sma5.iloc[j]):
                        exit_p = float(df["close"].iloc[j])
                        exit_idx = j
                        break
                rets.append((exit_p / entry) - 1.0 - MY_COST_RT)
                dates.append(df.index[i + 1])
                i = exit_idx + 1
            else:
                i += 1
    results.append(summarize_trades("BT-030", "SW-02", "MY 2-5d RSI(2)<10 Uptrend Swing", "MY", "1d(5y)", rets, dates))

    df_res = pd.DataFrame(results).sort_values(["sharpe", "net_ret_pct"], ascending=False)
    df_res.to_csv(OUT_CSV, index=False)
    print(df_res.to_string(index=False))


if __name__ == "__main__":
    main()
