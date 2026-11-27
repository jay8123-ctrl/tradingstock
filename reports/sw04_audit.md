# Swarm 1 Read-Only Audit Report — SW-04 (`BT-034`)

- **Date**: `2026-11-27`
- **Target**: `SW-04` (`strategies/SW-04_us_donchian_vol.md`, `backtests/day4_swing_research.py`, `backtests/day4_sw04_robustness.py`, `bot/paper_bot.py`, `bot/data_pipeline.py`, `data/`)
- **Auditors**: 3 independent read-only workers (Lookahead, Costs & Fills, Data & Survivorship) + read-only `@verifier` cross-check
- **Total Ideas Tried in Repo (prior to audit)**: `46+` backtest IDs (`BT-001`–`BT-046`) + `27` parameter grid variants = `73+` trials (no multiple-testing adjustment recorded)
- **Official `@verifier` Verdict**: **`[rejected]` — `"not an edge"`**

---

## 1. Reproducibility & Measured Statistical Bar

Command re-run by `@verifier`:
```bash
.venv/bin/python backtests/day4_sw04_robustness.py
```

- **Exact match (0.00% drift)** to reported numbers on the unfixed simulator: `283` trades, `+119.67%` net return, `-12.47%` MaxDD, `Sharpe 1.23`, `PF 1.59`, `avg_r 0.243`.
- **Newly Measured `t-stat` & True 70/30 Split** (previously not computed):

| Slice / Variant | Trades | Net Return | MaxDD | Sharpe | Daily `t-stat` | Trade PnL `t-stat` | Desk Bar (`t > 3.0`, `100+`) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| Unfixed Full (`2022-09-15` ~ `2026-11-20`) | 283 | +119.67% | -12.47% | 1.23 | `2.5107` | `2.4991` | **FAIL** |
| Reported "OOS" (`2023-01-01` ~ `2026-11-20`, 97.5% overlap) | 276 | +129.28% | -12.47% | 1.34 | `2.6452` | `2.5915` | **FAIL** (not OOS) |
| True First 70% IS (`2022-09-15` ~ `2025-08-20`) | 194 | +82.95% | -9.21% | 1.36 | `2.3259` | `2.9479` | **FAIL** |
| **True Last 30% OOS (`2025-08-21` ~ `2026-11-20`)** | **88** | **+19.79%** | **-12.46%** | **0.93** | **`1.0378`** | **`0.9354`** | **FAIL (`<100` trades & `t<<3.0`)** |
| Causal Fix (a): Open before Close exits | 263 | +105.41% | - | 1.22 | - | - | **FAIL** |
| Causal Fix (a)+(b): + Day-0 stop check | 274 | +106.82% | - | 1.24 | `2.540` | `2.497` | **FAIL** |
| Causal Fix (a)+(b)+(d): + Next-open exit (`paper_bot` parity) | 265 | **+83.03%** | - | 1.08 | `2.195` | `2.305` | **FAIL** (< SPY `+87.00%`) |
| Causal Fix (a)+(b)+(d)+(f): + Whole shares at `$1,000` (`risk/engine.py`) | 225 | **+46.51%** | - | 0.91 | `1.852` | `1.907` | **FAIL** (103 signals skipped) |

---

## 2. Verified Findings (Ranked Most Dangerous First)

1. **[CRITICAL] Same-Day Close-to-Open Time-Travel & Entry-Day Stop Immunity**
   - **Location**: `backtests/day4_swing_research.py` L98–196
   - **Issue**: Inside `for dt in all_dates:`, Step 1 (L99–143) executes `dt` close exits (`SIGNAL_OR_TIME`) and frees slots/cash; Step 2 (L146–153) marks equity at `dt` close; Step 3 (L156–196) then enters new positions at `dt` **open** using `dt` close equity, cash, and slots (**54 days** affected; **17** same-symbol same-day re-entries). In addition, Step 3 entries are never checked against `row["low"] <= stop` on entry day `dt` (**7 trades** breached their stop on Day 0 without stopping out).
   - **Fix**: Open new positions at `dt` open using prior EOD `equity`/`cash`/`open_slots` *before* running `dt` intraday stop and EOD exit checks, and check `low <= stop` on Day 0 for newly opened positions.

2. **[CRITICAL] Fake "Walk-Forward / Stitched OOS" (No 70/30 Holdout)**
   - **Location**: `backtests/day4_swing_research.py` L11, L336–339; `backtests/day4_sw04_robustness.py` L53–55; `strategies/SW-04_us_donchian_vol.md` L19
   - **Issue**: No rolling 12m/3m walk-forward exists. `sim_oos` simply drops Q4 2022 (`2023-01-01` ~ `2026-11-20`), overlapping **276/283 trades (97.53%)** with the full sample used to pick SW-04 and run the 27-variant parameter grid. On the true untouched last 30% (`2025-08-21` ~ `2026-11-20`), SW-04 yields `88` trades and `t_daily = 1.0378`.
   - **Fix**: Freeze all rule/parameter tuning on the first 70% only; evaluate the untouched last 30% once.

3. **[CRITICAL] Statistical Bar Missing & Failed (`t-stat < 3.0`)**
   - **Location**: `backtests/day4_swing_research.py` L212–244, L354–361
   - **Issue**: `calc_metrics` never computes `t-stat`; pass criteria were weakened to `trades >= 50` and `sharpe >= 0.8`. Actual measured `t_daily` is `2.5107` (and `2.195` under causal execution; `1.0378` on true 30% OOS).
   - **Fix**: Compute daily and trade-level `t-stat` in `calc_metrics` and enforce `t-stat > 3.0` and `100+` trades.

4. **[HIGH] Severe Survivorship & Hindsight Universe Bias**
   - **Location**: `bot/data_pipeline.py` L23–28; `bot/paper_bot.py` L41–44
   - **Issue**: Static 18-symbol `US_UNIVERSE` hand-picked in 2026 with zero delisted symbols and extreme 2022–2026 winners (`PLTR +1691%`, `NVDA +874%`, `AMD +454%`, `SMH +304%`, `META +279%`; equal-weight B&H `+274.63%`).
   - **Fix**: Test on a survivorship-free / point-in-time historical constituent universe or broad ETFs without ex-post single-stock cherry-picking.

5. **[HIGH] Backtest Close-on-Close Exit vs. `paper_bot.py` Next-Session Exit**
   - **Location**: `backtests/day4_swing_research.py` L117–119 vs. `bot/paper_bot.py` L276–294, L343–356
   - **Issue**: Backtest fills `Close < SMA10` at the same bar's exact `close`; `paper_bot.py` submits market orders in the next session. Fixing this drops causal return to `+83.03%` (below SPY B&H `+87.00%`).
   - **Fix**: Fill signal/time exits at `dt+1` `open` in `simulate_portfolio`.

6. **[HIGH] Whole-Share Truncation Incompatibility at `$1,000` Equity**
   - **Location**: `bot/paper_bot.py` L199 vs. `backtests/day4_swing_research.py` L183
   - **Issue**: With `$1,000` equity (`25%` slot cap = `$250`), integer-share truncation (`int(approved_qty // 1)`) blocks **12 of 18 symbols** currently trading above `$250` (`AAPL, AMD, GLD, GOOGL, IWM, JPM, META, MSFT, QQQ, SMH, SPY, TSLA`), skipping 103 signals and dropping return to `+46.51%`.
   - **Fix**: Either align the backtest to whole shares (and filter the universe / raise capital) or adopt fractional-share execution compatible with broker stop orders.

7. **[HIGH] `paper_bot.py` Reads Stale Local `yfinance` Parquet Files**
   - **Location**: `bot/paper_bot.py` L332–337 vs. `data/sources.md` L6
   - **Issue**: Violates `data/sources.md` (`yfinance` is research-only). `run_alpaca_paper_cycle()` reads static local parquet files and never checks bar freshness.
   - **Fix**: Fetch fresh completed daily bars from Alpaca `StockHistoricalDataClient` and verify bar freshness before scanning signals/exits.

8. **[MEDIUM-HIGH] Cost Accounting on Open-End Positions & Pre-Fill Trade Logging**
   - **Location**: `backtests/day4_swing_research.py` L152, L204; `bot/paper_bot.py` L355–382, L451–460
   - **Issue**: Open positions at backtest end are marked to market with zero costs deducted (0 open at end of BT-034 full sample, so unaffected there, but affects 10/12 other runs and the 70% IS split). `paper_bot.py` logs pre-fill `pos.current_price`, `fees=0.0`, `slippage=""` instead of polling actual fill receipts.
   - **Fix**: Split cost deduction into entry half-cost and exit half-cost (and liquidate at final bar); poll Alpaca order fills in `paper_bot.py`.

9. **[MEDIUM] Data Pipeline Missing Gap Detection, Unaudited Splits & `MY_1d` UTC Date Shift**
   - **Location**: `bot/data_pipeline.py` L5, L58–62, L69–134, L147
   - **Issue**: `check_and_clean` implements zero calendar gap detection despite docstring claim; `actions=False` leaves splits/dividends unaudited; `MY_1d` (`00:00+08:00`) converts to `16:00+00:00` of the **previous UTC calendar day**, shifting `.date()`/`.dayofweek` by `-1` day in UTC.
   - **Fix**: Add exchange-calendar gap counting, fetch `actions=True` for corporate-action audit logs, and normalize daily dates in exchange-local timezone.

---

## 3. Risk-Wall Integration & Safety Test Status

- `.venv/bin/python bot/test_day5_faults.py`: **PASSED (8/8)** — including Test 8 confirming `bot/paper_bot.py` routes sizing through `risk/engine.py`.
- `.venv/bin/python -m unittest discover -s risk -p "test_*.py" -v`: **PASSED (12/12)**.
