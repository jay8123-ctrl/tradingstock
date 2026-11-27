# risk/engine.py: no AI in this file. Only humans edit it.
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Proposal:
    symbol: str
    side: str                  # "buy" (long-only on TradingStock)
    entry: float
    stop: float
    target: Optional[float] = None


# Approved limits from playbook.md & risk/limits.md
LONG_ONLY = True
RISK_PER_TRADE = 0.02          # lose max 2% of equity if the stop hits
MAX_EXPOSURE = 1.0             # all open positions together <= 1x equity (cash)
MAX_SLOT_FRAC = 0.25           # single position cap <= 25% of equity
MAX_DAILY_LOSS = 0.05          # down 5% today = no new trades
CIRCUIT_BREAKER_DD = 0.15      # down 15% from HWM = halt all new trades
MAX_POSITIONS = 4
MIN_REWARD = 1.5               # target must be >= 1.5x further than stop (when provided)
MIN_STOP_PCT = 0.015           # reject stops tighter than 1.5%
MAX_STOP_PCT = 0.15            # reject stops wider than 15.0%


def check(
    p: Proposal,
    equity: float,
    exposure: float,
    open_positions: int,
    pnl_today: float,
    high_water_mark: Optional[float] = None,
) -> tuple[float, str]:
    """Deterministic position-sizing and risk gate.

    Returns (approved_qty, status_message). Never calls any model or network API.
    """
    if equity <= 0:
        return 0.0, "REJECT: non-positive equity"

    if high_water_mark is not None and high_water_mark > 0:
        dd = (equity - high_water_mark) / high_water_mark
        if dd <= -CIRCUIT_BREAKER_DD:
            return 0.0, "REJECT: HWM circuit breaker triggered"

    if pnl_today <= -MAX_DAILY_LOSS * equity:
        return 0.0, "REJECT: daily loss limit hit"

    if open_positions >= MAX_POSITIONS:
        return 0.0, "REJECT: too many open positions"

    if p.entry <= 0 or p.stop <= 0:
        return 0.0, "REJECT: non-positive entry or stop price"

    side = p.side.lower().strip()
    if LONG_ONLY and side != "buy":
        return 0.0, "REJECT: long-only desk prohibits short entries"

    if side == "buy":
        if not (p.stop < p.entry):
            return 0.0, "REJECT: stop must be below entry for buy"
        if p.target is not None and not (p.entry < p.target):
            return 0.0, "REJECT: target must be above entry for buy"
    elif side == "sell":
        if not (p.entry < p.stop):
            return 0.0, "REJECT: stop must be above entry for sell"
        if p.target is not None and not (p.target < p.entry):
            return 0.0, "REJECT: target must be below entry for sell"
    else:
        return 0.0, "REJECT: invalid side"

    risk = abs(p.entry - p.stop)
    stop_pct = risk / p.entry
    if stop_pct < MIN_STOP_PCT or stop_pct > MAX_STOP_PCT:
        return 0.0, f"REJECT: stop distance {stop_pct:.2%} outside [{MIN_STOP_PCT:.1%}, {MAX_STOP_PCT:.1%}]"

    if p.target is not None:
        reward = abs(p.target - p.entry)
        if reward / risk < MIN_REWARD:
            return 0.0, "REJECT: reward too small for the risk"

    room = MAX_EXPOSURE * equity - exposure
    if room <= 0:
        return 0.0, "REJECT: no exposure room left"

    slot_cap = MAX_SLOT_FRAC * equity
    max_notional = min(room, slot_cap)
    qty_by_risk = (RISK_PER_TRADE * equity) / risk
    qty_by_notional = max_notional / p.entry
    qty = min(qty_by_risk, qty_by_notional)
    if qty <= 0:
        return 0.0, "REJECT: computed size is zero"

    return qty, "APPROVED"
