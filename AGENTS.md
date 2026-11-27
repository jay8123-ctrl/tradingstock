# AGENTS.md — TradingStock Research Desk

```text
AGENTS.md: TRADINGSTOCK DESK

MARKETS      US Equities (Alpaca Paper) & Bursa Malaysia (Moomoo MY research) — Long-only, 1x cash
MISSION      find, test and reject strategies. never place real orders
COMMANDS     tests: pytest -q (or python3 -m unittest discover -s risk -p "test_*.py" -v)
             data: python3 bot/data_pipeline.py
             fault-tests: python3 bot/test_day5_faults.py
             backtest: python3 backtests/<script>.py
OWNERSHIP    data/ → data-engineer | strategies/ → quant |
             backtests/ → written by scripts only | risk/ → NOBODY (HUMANS ONLY)
SPLIT        tune on the first 70% of data. the last 30% stays
             untouched until the final test
NO PEEKING   signals only use data from BEFORE the bar they trade
COSTS        fees + slippage on every fill (US default >= 10 bps round-trip; MY >= 46 bps round-trip)
THE BAR      no "edge" without a t-stat above 3.0 and 100+ trades
HONESTY      never invent a number. not measured = "not measured"
DONE         tests pass, every number has its command + file + line,
             then post "@verifier [done]"
NEVER        place real orders, open .env files, edit risk/, edit playbook.md limits
```

## Desk Rules & Hard Boundaries

1. **Read-Only Risk Wall**: `risk/engine.py` and `risk/limits.md` are owned exclusively by the human operator. No agent may edit them or weaken any limit in `playbook.md`.
2. **Cross-Model Verification**: No strategy or backtest finding is accepted until `@verifier` (running on a different model in read-only mode) re-runs the exact command and posts `[accepted]`.
3. **Research & Paper Only**: Agents never access live broker keys or `.env` files. Promotion to live trading requires explicit human sign-off (`可以上实盘`) after 30+ matching paper trades.
4. **External Research Context Only**: Filings, news, macro calendars, or `gemini-api` research outputs provide context only; trade signals must come strictly from deterministic code.
