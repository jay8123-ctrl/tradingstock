---
name: backtest-checks
description: The checklist for any backtest on this desk. Use before reporting or accepting a result.
---

# Backtest Verification Checklist

- [ ] **Time Split**: Data split strictly by time. The last 30% remained untouched until the final run.
- [ ] **No Lookahead**: Every signal input is shifted — only data available *before* the trade bar is used.
- [ ] **Full Costs**: Fees + slippage applied on every entry and every exit (US >= 10 bps RT; Bursa MY >= 46 bps RT).
- [ ] **Clean Universe**: Delisted symbols / survivorship bias checked; prices adjusted for splits and dividends; data gaps reported (never silently filled).
- [ ] **Multiple Testing Transparency**: Total number of ideas/variants tried in this run is written at the top of the report.
- [ ] **Statistical Bar**: `t-stat > 3.0` and `100+` trades (and positive out-of-sample), otherwise the result is explicitly labeled `"not an edge"`.
