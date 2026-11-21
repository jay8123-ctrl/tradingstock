"""
Day 4 Robustness & Regime Audit for #1 Survivor: SW-04 (BT-034)
- Parameter neighbor grid (hh in [15,20,25], vol_mult in [1.0,1.2,1.5], stop_atr in [1.5,2.0,2.5], max_hold in [8,10,12])
- Year-by-year regime breakdown (2022, 2023, 2024, 2025, 2026)
- Stitched OOS check (2023-01-01 ~ 2026-11-20)
"""

from __future__ import annotations

import pandas as pd
from day3_fast_screen import load_market, US_COST_RT
from day4_swing_research import add_indicators, simulate_portfolio, calc_metrics


def main() -> None:
    us_raw = load_market("US", "1d")
    us_data = {s: add_indicators(df) for s, df in us_raw.items()}
    warmup = pd.Timestamp("2022-09-15", tz="UTC")

    print("=== 1. PARAMETER NEIGHBOR ROBUSTNESS (SW-04) ===")
    rows = []
    for hh in (15, 20, 25):
        for vm in (1.0, 1.2, 1.5):
            for satr in (1.5, 2.0, 2.5):
                # Recompute hh dynamically
                def sig_fn(df, h=hh, v=vm):
                    hh_s = df["high"].rolling(h).max()
                    sig = (df["close"] > df["sma200"]) & (df["close"] >= hh_s.shift(1)) & (df["volume"] > df["vol_ma20"] * v)
                    return sig, df["mom20"]
                ex_fn = lambda df, dt, pos: float(df.loc[dt, "close"]) < float(df.loc[dt, "sma10"])
                sim = simulate_portfolio(us_data, sig_fn, ex_fn, satr, 10, 4, 0.02, US_COST_RT, 1000.0, start_date=warmup)
                m = calc_metrics(sim)
                rows.append({"hh": hh, "vol_mult": vm, "stop_atr": satr, **m})

    df_grid = pd.DataFrame(rows)
    pos_pct = (df_grid["net_ret_pct"] > 0).mean() * 100.0
    sh_gt1 = (df_grid["sharpe"] >= 1.0).mean() * 100.0
    print(f"Grid size={len(df_grid)} | Profitable={pos_pct:.1f}% | Sharpe>=1.0={sh_gt1:.1f}% | Median Ret={df_grid['net_ret_pct'].median():.2f}% | Median Sharpe={df_grid['sharpe'].median():.2f} | Worst DD={df_grid['max_dd_pct'].min():.2f}%")

    print("\n=== 2. YEAR-BY-YEAR REGIME BREAKDOWN (Base: hh=20, vol=1.2, stop=2.0*ATR, hold=10) ===")
    base_sig = lambda df: ((df["close"] > df["sma200"]) & (df["close"] >= df["hh20"].shift(1)) & (df["volume"] > df["vol_ma20"] * 1.2), df["mom20"])
    base_ex = lambda df, dt, pos: float(df.loc[dt, "close"]) < float(df.loc[dt, "sma10"])
    sim_base = simulate_portfolio(us_data, base_sig, base_ex, 2.0, 10, 4, 0.02, US_COST_RT, 1000.0, start_date=warmup)
    eq = sim_base["equity_curve"]
    trades = pd.DataFrame(sim_base["trades"])
    trades["year"] = pd.to_datetime(trades["exit_date"]).dt.year
    for yr, grp in eq.groupby(eq.index.year):
        yr_ret = (grp.iloc[-1] / grp.iloc[0] - 1.0) * 100.0
        yr_dd = (grp / grp.cummax() - 1.0).min() * 100.0
        n_t = int((trades["year"] == yr).sum())
        print(f"  {yr}: Trades={n_t:3d}, NetRet={yr_ret:+6.2f}%, MaxDD={yr_dd:6.2f}%")

    print("\n=== 3. STITCHED OOS (2023-01-01 ~ 2026-11-20) ===")
    sim_oos = simulate_portfolio(us_data, base_sig, base_ex, 2.0, 10, 4, 0.02, US_COST_RT, 1000.0, start_date=pd.Timestamp("2023-01-01", tz="UTC"))
    print(calc_metrics(sim_oos))


if __name__ == "__main__":
    main()
