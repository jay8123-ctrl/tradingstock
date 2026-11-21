"""
Section 11: Hourly Auto-Patrol Health Check (bot/health_check.py)
Checks:
1. Heartbeat freshness (<= 2 min during active runs).
2. Position reconciliation (broker positions == local state).
3. Mandatory exchange-side stop-loss check on EVERY open position.
4. Daily P&L vs -5% cap & HWM drawdown vs -15% circuit breaker.
If ANY check fails: halts new entries, leaves stops intact, logs incident, alerts Telegram.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from paper_bot import BotState, DAILY_LOSS_LIMIT, CIRCUIT_BREAKER_DD, log_incident, send_telegram


def run_health_check(
    state: BotState,
    broker_positions: dict[str, dict[str, Any]],
    broker_stop_orders: set[str],
    current_equity: float,
    now_utc: datetime | None = None,
    max_heartbeat_age_sec: int = 120,
) -> tuple[bool, list[str]]:
    now_utc = now_utc or datetime.now(timezone.utc)
    issues: list[str] = []

    # 1. Heartbeat check
    if state.last_heartbeat_utc:
        hb = datetime.fromisoformat(state.last_heartbeat_utc.replace("Z", "+00:00"))
        age = (now_utc - hb).total_seconds()
        if age > max_heartbeat_age_sec:
            issues.append(f"Stale heartbeat ({int(age)}s > {max_heartbeat_age_sec}s)")
    else:
        issues.append("Missing heartbeat timestamp")

    # 2. Position reconciliation
    local_syms = set(state.open_positions.keys())
    broker_syms = set(broker_positions.keys())
    if local_syms != broker_syms:
        issues.append(f"Position mismatch: local={sorted(local_syms)} vs broker={sorted(broker_syms)}")

    # 3. Mandatory exchange-side stop-loss on EVERY open position
    for sym in broker_syms:
        if sym not in broker_stop_orders:
            issues.append(f"CRITICAL: Open position {sym} has NO active exchange stop-loss!")

    # 4. Risk limits check
    if state.day_start_equity > 0:
        daily_ret = (current_equity / state.day_start_equity) - 1.0
        if daily_ret <= DAILY_LOSS_LIMIT:
            issues.append(f"Daily loss limit breached ({daily_ret*100:.2f}% <= -5%)")
    if state.high_water_mark > 0:
        dd = (current_equity / state.high_water_mark) - 1.0
        if dd <= CIRCUIT_BREAKER_DD:
            issues.append(f"Circuit breaker breached ({dd*100:.2f}% <= -15%)")

    if issues:
        state.halted_new_entries = True
        state.halt_reason = "; ".join(issues)
        log_incident(
            "CRITICAL",
            "health_check",
            state.halt_reason,
            "Hourly patrol failed",
            "Halted new entries; kept existing stops; notified user",
        )
        send_telegram(f"[HEALTH CHECK FAIL] {state.halt_reason}")
        return False, issues

    return True, []
