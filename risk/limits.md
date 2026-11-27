# Risk Limits — HUMANS ONLY

> **OWNERSHIP**: Only the human operator may modify `risk/limits.md` or `risk/engine.py`. Agents have read-only access.

Aligned with [playbook.md](../playbook.md):

| Parameter | Limit | Enforcement |
| :--- | :--- | :--- |
| Direction | `Long-only` (`buy` only) | `risk/engine.py` rejects `sell`/short entries |
| Max Risk per Trade | `2.0%` of equity | `RISK_PER_TRADE = 0.02` |
| Max Total Exposure | `1.0x` equity (Cash, no leverage) | `MAX_EXPOSURE = 1.0` |
| Max Single Slot | `25.0%` of equity | `MAX_SLOT_FRAC = 0.25` |
| Max Concurrent Positions | `4` | `MAX_POSITIONS = 4` |
| Max Daily Loss | `-5.0%` of equity | `MAX_DAILY_LOSS = 0.05` -> halt new entries |
| Account Circuit Breaker | `-15.0%` from HWM | `CIRCUIT_BREAKER_DD = 0.15` -> halt all new entries |
| Min Reward-to-Risk | `1.5x` | `MIN_REWARD = 1.5` (optional if trend-following exit has `target=None`, or required when target is specified) |
| Stop Distance Guard | `1.5% – 15.0%` from entry | `MIN_STOP_PCT = 0.015`, `MAX_STOP_PCT = 0.15` |
| Heartbeat Timeout | `2 hours` | Silent `desk-watch` -> no new entries |
| Paper Drift Limit | `1.5x` worst backtest DD | Paper DD > 1.5x backtest DD -> pause + alert |
| Live Keys | Isolated outside agent workspace | Agents never see live API keys |
