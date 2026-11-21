"""
Day 3 Fast Screening Engine (BT-001 ~ BT-022)
- Uses ONLY real cleaned data in data/clean/.
- Strictly NO look-ahead bias.
- Full round-trip costs deducted on every trade:
    US: 0.05% slippage/side (0.10% RT)
    MY: 0.13% fee+stamp+clearing + 0.10% slippage = 0.23%/side (0.46% RT)
- Excludes 0138.KL due to unverified >50% jump flags in raw data.
"""

from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CLEAN_DIR = ROOT / "data" / "clean"
OUT_CSV = ROOT / "backtests" / "day3_screen_results.csv"

US_COST_RT = 0.0010  # 0.05% per side slippage (0% commission)
MY_COST_RT = 0.0046  # 0.23% per side (0.13% stamp/clearing/fee + 0.10% slippage)


def load_market(market: str, interval: str, exclude: set[str] | None = None) -> dict[str, pd.DataFrame]:
    exclude = exclude or set()
    folder = CLEAN_DIR / market.lower() / interval
    data = {}
    for p in sorted(folder.glob("*.parquet")):
        sym = p.stem.replace("_", ".")
        if sym in exclude:
            continue
        df = pd.read_parquet(p)
        if not df.empty:
            data[sym] = df
    return data


def summarize_trades(
    bt_id: str,
    idea_id: str,
    name: str,
    market: str,
    tf: str,
    trade_returns: list[float],
    trade_dates: list[pd.Timestamp],
) -> dict:
    n = len(trade_returns)
    if n == 0:
        return {
            "bt_id": bt_id, "idea_id": idea_id, "name": name, "market": market, "tf": tf,
            "trades": 0, "net_ret_pct": 0.0, "max_dd_pct": 0.0, "win_rate_pct": 0.0,
            "profit_factor": 0.0, "sharpe": 0.0, "avg_trade_pct": 0.0, "status": "NO_TRADES",
        }

    # Aggregate to daily portfolio return (equal-weight across concurrent signals on same day)
    s = pd.DataFrame({"date": pd.to_datetime(trade_dates).normalize(), "ret": trade_returns})
    daily = s.groupby("date")["ret"].mean().sort_index()

    equity = (1.0 + daily).cumprod()
    peak = equity.cummax()
    dd = (equity / peak) - 1.0
    max_dd = float(dd.min() * 100.0)
    net_ret = float((equity.iloc[-1] - 1.0) * 100.0)

    arr = np.array(trade_returns, dtype=float)
    wins = arr[arr > 0]
    losses = arr[arr < 0]
    win_rate = float((arr > 0).mean() * 100.0)
    pf = float(wins.sum() / abs(losses.sum())) if len(losses) > 0 and abs(losses.sum()) > 1e-12 else (99.0 if len(wins) > 0 else 0.0)

    # Annualized Sharpe over active calendar span
    span_days = max((daily.index[-1] - daily.index[0]).days, 1)
    trades_per_year = len(daily) / (span_days / 365.25)
    std = float(daily.std(ddof=1)) if len(daily) > 1 else 0.0
    sharpe = float((daily.mean() / std) * np.sqrt(trades_per_year)) if std > 1e-12 else 0.0

    status = "CANDIDATE" if (n >= 50 and net_ret > 0 and sharpe >= 0.5 and max_dd > -15.0) else "REJECT"
    return {
        "bt_id": bt_id,
        "idea_id": idea_id,
        "name": name,
        "market": market,
        "tf": tf,
        "trades": n,
        "net_ret_pct": round(net_ret, 2),
        "max_dd_pct": round(max_dd, 2),
        "win_rate_pct": round(win_rate, 1),
        "profit_factor": round(pf, 2),
        "sharpe": round(sharpe, 2),
        "avg_trade_pct": round(float(arr.mean() * 100.0), 3),
        "status": status,
    }


def run_daily_strategies(market: str, data: dict[str, pd.DataFrame], cost_rt: float, start_idx: int) -> list[dict]:
    results = []
    idx = start_idx

    # ID-05: Gap-Down Fade (Close[t-1] > SMA50[t-1], Open[t] gaps down -1% to -4%, buy Open[t] sell Close[t])
    rets, dates = [], []
    for sym, df in data.items():
        sma50 = df["close"].rolling(50).mean().shift(1)
        prev_c = df["close"].shift(1)
        gap = (df["open"] / prev_c) - 1.0
        sig = (prev_c > sma50) & (gap <= -0.01) & (gap >= -0.04)
        oc_ret = (df["close"] / df["open"]) - 1.0 - cost_rt
        for dt, r in oc_ret[sig].items():
            rets.append(float(r))
            dates.append(dt)
    results.append(summarize_trades(f"BT-{idx:03d}", "ID-05", "Gap-Down Fade (Uptrend)", market, "1d(5y)", rets, dates))
    idx += 1

    # ID-06: 3-Day Oversold Intraday Bounce (2 down days + RSI(2)<15 prior close, buy Open[t] sell Close[t])
    rets, dates = [], []
    for sym, df in data.items():
        delta = df["close"].diff()
        gain = delta.clip(lower=0).rolling(2).mean()
        loss = (-delta.clip(upper=0)).rolling(2).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi2 = (100.0 - (100.0 / (1.0 + rs))).shift(1)
        down2 = (df["close"].shift(1) < df["close"].shift(2)) & (df["close"].shift(2) < df["close"].shift(3))
        sig = down2 & (rsi2 < 15)
        oc_ret = (df["close"] / df["open"]) - 1.0 - cost_rt
        for dt, r in oc_ret[sig].items():
            rets.append(float(r))
            dates.append(dt)
    results.append(summarize_trades(f"BT-{idx:03d}", "ID-06", "Oversold RSI2<15 Day Bounce", market, "1d(5y)", rets, dates))
    idx += 1

    # ID-11: NR7 Breakout (prior day narrowest range of 7 days, if High[t] > High[t-1] enter at High[t-1] -> Close[t])
    rets, dates = [], []
    for sym, df in data.items():
        rng = df["high"] - df["low"]
        nr7 = (rng == rng.rolling(7).min()).shift(1).fillna(False)
        prev_h = df["high"].shift(1)
        prev_l = df["low"].shift(1)
        # Only enter if open <= prev_h (no gap-over) and high breaks prev_h
        sig = nr7 & (df["open"] <= prev_h) & (df["high"] > prev_h)
        # Conservative stop check: if low < prev_l assume stopped at prev_l, else exit at close
        for dt in df.index[sig]:
            entry = float(prev_h.loc[dt])
            stop = float(prev_l.loc[dt])
            if df.loc[dt, "low"] <= stop:
                r = (stop / entry) - 1.0 - cost_rt
            else:
                r = (float(df.loc[dt, "close"]) / entry) - 1.0 - cost_rt
            rets.append(r)
            dates.append(dt)
    results.append(summarize_trades(f"BT-{idx:03d}", "ID-11", "NR7 Intraday Breakout", market, "1d(5y)", rets, dates))
    idx += 1

    # ID-12: Inside-Day Breakout (prior day inside bar, break mother high -> close, stop at prior low)
    rets, dates = [], []
    for sym, df in data.items():
        inside = ((df["high"] < df["high"].shift(1)) & (df["low"] > df["low"].shift(1))).shift(1).fillna(False)
        prev_h = df["high"].shift(1)
        prev_l = df["low"].shift(1)
        sig = inside & (df["open"] <= prev_h) & (df["high"] > prev_h)
        for dt in df.index[sig]:
            entry = float(prev_h.loc[dt])
            stop = float(prev_l.loc[dt])
            if df.loc[dt, "low"] <= stop:
                r = (stop / entry) - 1.0 - cost_rt
            else:
                r = (float(df.loc[dt, "close"]) / entry) - 1.0 - cost_rt
            rets.append(r)
            dates.append(dt)
    results.append(summarize_trades(f"BT-{idx:03d}", "ID-12", "Inside-Day Breakout", market, "1d(5y)", rets, dates))
    idx += 1

    # ID-18: Overnight Gap Leaders (gap +0.5% to +4%, buy Open -> Close)
    rets, dates = [], []
    for sym, df in data.items():
        prev_c = df["close"].shift(1)
        gap = (df["open"] / prev_c) - 1.0
        sig = (gap >= 0.005) & (gap <= 0.04)
        oc_ret = (df["close"] / df["open"]) - 1.0 - cost_rt
        for dt, r in oc_ret[sig].items():
            rets.append(float(r))
            dates.append(dt)
    results.append(summarize_trades(f"BT-{idx:03d}", "ID-18", "Gap-Up Continuation (0.5-4%)", market, "1d(5y)", rets, dates))
    idx += 1

    # ID-19: Turn-of-Month Day Trade (last 1 trading day + first 3 trading days of month, buy Open -> Close)
    rets, dates = [], []
    target_syms = ["SPY", "QQQ"] if market == "US" else list(data.keys())[:5]
    for sym in target_syms:
        if sym not in data:
            continue
        df = data[sym]
        dom = df.index.day
        sig = (dom >= 28) | (dom <= 4)
        oc_ret = (df["close"] / df["open"]) - 1.0 - cost_rt
        for dt, r in oc_ret[sig].items():
            rets.append(float(r))
            dates.append(dt)
    results.append(summarize_trades(f"BT-{idx:03d}", "ID-19", "Turn-of-Month Open-Close", market, "1d(5y)", rets, dates))
    idx += 1

    # ID-20: Turnaround Monday (Friday down, Monday gaps down, buy Open -> Close)
    rets, dates = [], []
    for sym, df in data.items():
        prev_ret = df["close"].pct_change().shift(1)
        gap = (df["open"] / df["close"].shift(1)) - 1.0
        sig = (df.index.dayofweek == 0) & (prev_ret < -0.005) & (gap < 0)
        oc_ret = (df["close"] / df["open"]) - 1.0 - cost_rt
        for dt, r in oc_ret[sig].items():
            rets.append(float(r))
            dates.append(dt)
    results.append(summarize_trades(f"BT-{idx:03d}", "ID-20", "Turnaround Monday Dip", market, "1d(5y)", rets, dates))
    idx += 1

    return results


def run_hourly_strategies(market: str, data: dict[str, pd.DataFrame], cost_rt: float, start_idx: int) -> list[dict]:
    results = []
    idx = start_idx

    # ID-01: First-Hour Momentum (bar 0 green > +0.3%, buy bar 1 open -> last bar close, stop at bar 0 low)
    rets, dates = [], []
    for sym, df in data.items():
        df = df.copy()
        df["day"] = df.index.normalize()
        for day, grp in df.groupby("day"):
            if len(grp) < 3:
                continue
            b0 = grp.iloc[0]
            if (b0["close"] / b0["open"] - 1.0) > 0.003:
                entry = float(grp.iloc[1]["open"])
                stop = float(b0["low"])
                rest = grp.iloc[1:]
                if (rest["low"] <= stop).any():
                    r = (stop / entry) - 1.0 - cost_rt
                else:
                    r = (float(rest.iloc[-1]["close"]) / entry) - 1.0 - cost_rt
                rets.append(r)
                dates.append(day)
    results.append(summarize_trades(f"BT-{idx:03d}", "ID-01", "First-Hour Momentum", market, "1h(~3y)", rets, dates))
    idx += 1

    # ID-07: Intraday Z-Score Dip (1h close < SMA20 - 2*STD20, hold 2 bars or EOD)
    rets, dates = [], []
    for sym, df in data.items():
        df = df.copy()
        ma = df["close"].rolling(20).mean()
        sd = df["close"].rolling(20).std()
        z = (df["close"] - ma) / sd.replace(0, np.nan)
        df["day"] = df.index.normalize()
        df["z"] = z
        for day, grp in df.groupby("day"):
            if len(grp) < 4:
                continue
            for i in range(len(grp) - 2):
                if grp.iloc[i]["z"] < -2.0:
                    entry = float(grp.iloc[i + 1]["open"])
                    exit_p = float(grp.iloc[min(i + 2, len(grp) - 1)]["close"])
                    rets.append((exit_p / entry) - 1.0 - cost_rt)
                    dates.append(day)
                    break  # max 1 trade per symbol per day
    results.append(summarize_trades(f"BT-{idx:03d}", "ID-07", "Intraday 1h Z-Score Dip", market, "1h(~3y)", rets, dates))
    idx += 1

    # ID-09: ORB-1h Breakout (break bar 0 high in subsequent bars, stop at bar 0 low, exit EOD)
    rets, dates = [], []
    for sym, df in data.items():
        df = df.copy()
        df["day"] = df.index.normalize()
        for day, grp in df.groupby("day"):
            if len(grp) < 3:
                continue
            b0_h = float(grp.iloc[0]["high"])
            b0_l = float(grp.iloc[0]["low"])
            rest = grp.iloc[1:]
            # Find first bar that breaks b0_h
            for j in range(len(rest)):
                if rest.iloc[j]["open"] <= b0_h and rest.iloc[j]["high"] > b0_h:
                    entry = b0_h
                    after = rest.iloc[j:]
                    if (after["low"] <= b0_l).any():
                        r = (b0_l / entry) - 1.0 - cost_rt
                    else:
                        r = (float(after.iloc[-1]["close"]) / entry) - 1.0 - cost_rt
                    rets.append(r)
                    dates.append(day)
                    break
    results.append(summarize_trades(f"BT-{idx:03d}", "ID-09", "ORB-1h Breakout", market, "1h(~3y)", rets, dates))
    idx += 1

    # ID-21/22: Last-Hour Power Trend (before last bar, intraday return > +0.5% and near HOD, buy last bar open -> close)
    rets, dates = [], []
    for sym, df in data.items():
        df = df.copy()
        df["day"] = df.index.normalize()
        for day, grp in df.groupby("day"):
            if len(grp) < 4:
                continue
            pre = grp.iloc[:-1]
            last = grp.iloc[-1]
            day_open = float(pre.iloc[0]["open"])
            pre_close = float(pre.iloc[-1]["close"])
            pre_high = float(pre["high"].max())
            if (pre_close / day_open - 1.0) > 0.005 and (pre_close >= pre_high * 0.997):
                r = (float(last["close"]) / float(last["open"])) - 1.0 - cost_rt
                rets.append(r)
                dates.append(day)
    results.append(summarize_trades(f"BT-{idx:03d}", "ID-21" if market == "US" else "ID-22", "Last-Hour Power Trend", market, "1h(~3y)", rets, dates))
    idx += 1

    return results


def run_cross_market_lead_lag(us_1d: dict[str, pd.DataFrame], my_1d: dict[str, pd.DataFrame], bt_id: str) -> dict:
    # ID-13: US SMH/QQQ > +1.5% on day t -> buy MY tech (0166.KL) Open[t+1] -> Close[t+1]
    if "SMH" not in us_1d or "0166.KL" not in my_1d:
        return summarize_trades(bt_id, "ID-13", "US SMH -> MY Tech Lead-Lag", "MY", "1d(5y)", [], [])
    smh = us_1d["SMH"]["close"].pct_change()
    smh.index = smh.index.normalize()
    inari = my_1d["0166.KL"].copy()
    inari["day"] = inari.index.normalize()
    rets, dates = [], []
    for idx_dt, row in inari.iterrows():
        prev_day = row["day"] - pd.Timedelta(days=1)
        if prev_day in smh.index and smh.loc[prev_day] > 0.015:
            r = (float(row["close"]) / float(row["open"])) - 1.0 - MY_COST_RT
            rets.append(r)
            dates.append(row["day"])
    return summarize_trades(bt_id, "ID-13", "US SMH -> MY 0166.KL Lead-Lag", "MY", "1d(5y)", rets, dates)


def main() -> None:
    us_1d = load_market("US", "1d")
    us_1h = load_market("US", "1h")
    my_1d = load_market("MY", "1d", exclude={"0138.KL"})
    my_1h = load_market("MY", "1h", exclude={"0138.KL"})

    all_res = []
    all_res.extend(run_daily_strategies("US", us_1d, US_COST_RT, start_idx=1))
    all_res.extend(run_hourly_strategies("US", us_1h, US_COST_RT, start_idx=8))
    all_res.extend(run_daily_strategies("MY", my_1d, MY_COST_RT, start_idx=12))
    all_res.extend(run_hourly_strategies("MY", my_1h, MY_COST_RT, start_idx=19))
    all_res.append(run_cross_market_lead_lag(us_1d, my_1d, "BT-023"))

    df_res = pd.DataFrame(all_res).sort_values(["sharpe", "net_ret_pct"], ascending=False)
    df_res.to_csv(OUT_CSV, index=False)
    print(df_res.to_string(index=False))


if __name__ == "__main__":
    main()
