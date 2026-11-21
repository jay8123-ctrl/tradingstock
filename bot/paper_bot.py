"""
TradingStock Paper Trading Bot — Strategy #1: SW-04 (US 20d Donchian Vol Breakout)
Follows Sections 8, 11, 13, 14 of ai-trading-desk operating rules:
- Mandatory MODE announcement (`MODE: PAPER` or `MODE: LIVE`).
- Refuses LIVE mode without explicit written approval phrase `可以上实盘`.
- Hard exchange-side stop-loss attached on EVERY entry (no stop -> no order).
- Risk-based sizing: 2% equity risk per trade, max 4 slots (25% cap each), 1x cash, long-only.
- Daily -5% loss cap & -15% HWM circuit breaker (halts new entries, keeps stops intact).
- Atomic state persistence (bot/state.json) for crash-restart recovery.
- Exact 22-column trade logging to trades.csv and incident logging to incidents.md.
"""

from __future__ import annotations

import csv
import json
import logging
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "bot" / "state.json"
TRADES_CSV = ROOT / "trades.csv"
INCIDENTS_MD = ROOT / "incidents.md"
LOG_PATH = ROOT / "bot" / "paper_bot.log"

US_UNIVERSE = [
    "SPY", "QQQ", "IWM", "SMH", "XLF", "XLE", "XLK", "GLD",
    "NVDA", "AAPL", "MSFT", "AMZN", "META", "TSLA", "AMD", "GOOGL", "JPM", "PLTR",
]

# Risk limits from playbook.md (approved)
RISK_PER_TRADE = 0.02       # 2%
DAILY_LOSS_LIMIT = -0.05    # -5%
CIRCUIT_BREAKER_DD = -0.15  # -15%
MAX_POSITIONS = 4
MAX_SLOT_FRAC = 0.25        # 1 / MAX_POSITIONS (1x cash)
STOP_ATR_MULT = 2.0
MAX_HOLD_DAYS = 10
MIN_STOP_PCT = 0.015
MAX_STOP_PCT = 0.15


def setup_logger() -> logging.Logger:
    logger = logging.getLogger("tradingstock.bot")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        fmt = logging.Formatter("%(asctime)sZ | %(levelname)s | %(message)s")
        fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
        fh.setFormatter(fmt)
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        logger.addHandler(fh)
        logger.addHandler(sh)
    return logger


logger = setup_logger()


def send_telegram(msg: str) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": msg},
            timeout=5,
        )
        return r.status_code == 200
    except Exception as e:
        logger.warning(f"Telegram send failed: {type(e).__name__}: {e}")
        return False


def log_incident(level: str, module: str, symptom: str, cause: str, fix: str, status: str = "OPEN") -> None:
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    line = f"| {now_utc} | {level} | {module} | {symptom} | {cause} | {fix} | {status} |\n"
    with open(INCIDENTS_MD, "a", encoding="utf-8") as f:
        f.write(line)
    send_telegram(f"[ALERT][{level}] {module}: {symptom} -> {fix}")


def append_trade_csv(row: dict[str, Any]) -> None:
    fields = [
        "trade_id", "strategy", "mode", "market", "side", "entry_time", "entry_price",
        "size", "stop", "target", "exit_time", "exit_price", "fees", "funding",
        "slippage", "pnl", "r_multiple", "reason_in", "reason_out", "regime",
        "backtest_expected_r", "notes",
    ]
    file_exists = TRADES_CSV.exists() and TRADES_CSV.stat().st_size > 0
    with open(TRADES_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        if not file_exists:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in fields})


@dataclass
class BotState:
    mode: str = "PAPER"
    high_water_mark: float = 1000.0
    day_utc: str = ""
    day_start_equity: float = 1000.0
    halted_new_entries: bool = False
    circuit_breaker_triggered: bool = False
    halt_reason: str = ""
    last_heartbeat_utc: str = ""
    open_positions: dict[str, dict[str, Any]] = None  # type: ignore

    def __post_init__(self) -> None:
        if self.open_positions is None:
            self.open_positions = {}

    @classmethod
    def load(cls, path: Path = STATE_PATH) -> "BotState":
        if not path.exists():
            return cls()
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return cls(**raw)

    def save(self, path: Path = STATE_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2)
        tmp.replace(path)


def enforce_mode_guard(mode: str, approval_phrase: str = "") -> str:
    mode = mode.strip().upper()
    if mode not in ("PAPER", "LIVE"):
        raise ValueError(f"Invalid TRADING_MODE={mode}; must be PAPER or LIVE.")
    if mode == "LIVE" and approval_phrase.strip() != "可以上实盘":
        raise PermissionError(
            "HARD RULE BLOCK: Cannot start MODE: LIVE without explicit user approval phrase '可以上实盘'."
        )
    return mode


def calculate_position_size(
    equity: float,
    available_cash: float,
    entry_price: float,
    stop_price: float,
) -> tuple[int, float]:
    """
    Section 8.4 & 14: Risk-based sizing with 1x cash & 25% slot cap.
    HARD RULE: Refuses order if stop_price is missing or >= entry_price.
    Returns (shares_qty, risk_usd).
    """
    if stop_price is None or stop_price <= 0 or stop_price >= entry_price:
        raise ValueError("HARD RULE BLOCK: Valid exchange stop-loss (< entry_price) is mandatory before opening.")
    stop_dist = entry_price - stop_price
    stop_pct = stop_dist / entry_price
    if stop_pct < MIN_STOP_PCT or stop_pct > MAX_STOP_PCT:
        return 0, 0.0
    risk_budget = equity * RISK_PER_TRADE
    target_alloc = risk_budget / stop_pct
    max_slot_usd = equity * MAX_SLOT_FRAC
    alloc_usd = min(target_alloc, max_slot_usd, available_cash)
    qty = int(alloc_usd // entry_price)
    if qty <= 0:
        return 0, 0.0
    actual_risk = qty * stop_dist
    return qty, round(actual_risk, 2)


def evaluate_risk_guards(state: BotState, current_equity: float, today_utc: str) -> tuple[bool, str]:
    """
    Checks daily -5% loss cap and -15% HWM circuit breaker.
    Updates state in place. Returns (can_open_new, reason).
    """
    if state.day_utc != today_utc:
        state.day_utc = today_utc
        state.day_start_equity = current_equity
        if not state.circuit_breaker_triggered:
            state.halted_new_entries = False
            state.halt_reason = ""

    if current_equity > state.high_water_mark:
        state.high_water_mark = current_equity

    dd_from_hwm = (current_equity / max(state.high_water_mark, 1e-6)) - 1.0
    if dd_from_hwm <= CIRCUIT_BREAKER_DD:
        state.circuit_breaker_triggered = True
        state.halted_new_entries = True
        state.halt_reason = f"CIRCUIT_BREAKER: DD={dd_from_hwm*100:.2f}% <= -15.0%"
        return False, state.halt_reason

    daily_ret = (current_equity / max(state.day_start_equity, 1e-6)) - 1.0
    if daily_ret <= DAILY_LOSS_LIMIT:
        state.halted_new_entries = True
        state.halt_reason = f"DAILY_LOSS_CAP: Daily={daily_ret*100:.2f}% <= -5.0%"
        return False, state.halt_reason

    if state.circuit_breaker_triggered or state.halted_new_entries:
        return False, state.halt_reason or "MANUALLY_HALTED"

    return True, "OK"


def scan_sw04_signals(market_bars: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
    """
    Evaluates completed daily bars for SW-04:
    Close > SMA200 AND Close >= 20d High (prior 20 bars) AND Volume > 1.2 * VolMA20.
    Returns ranked candidates (highest mom20 first).
    """
    candidates = []
    for sym, df in market_bars.items():
        if len(df) < 205:
            continue
        c = df["close"]
        h = df["high"]
        l = df["low"]
        v = df["volume"]
        sma200 = c.rolling(200).mean().iloc[-1]
        hh20_prev = h.rolling(20).max().iloc[-2]
        vol_ma20 = v.rolling(20).mean().iloc[-1]
        tr = pd.concat([(h - l), (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
        atr14 = tr.rolling(14).mean().iloc[-1]
        mom20 = float(c.iloc[-1] / c.iloc[-21] - 1.0)

        last_c = float(c.iloc[-1])
        last_v = float(v.iloc[-1])
        if last_c > sma200 and last_c >= hh20_prev and last_v > vol_ma20 * 1.2 and np.isfinite(atr14):
            stop_p = round(last_c - STOP_ATR_MULT * float(atr14), 2)
            candidates.append({
                "symbol": sym,
                "signal_close": round(last_c, 2),
                "atr14": round(float(atr14), 4),
                "suggested_stop": stop_p,
                "mom20": round(mom20, 4),
            })
    candidates.sort(key=lambda x: x["mom20"], reverse=True)
    return candidates


def run_alpaca_paper_cycle() -> None:
    load_dotenv(ROOT / ".env")
    mode = enforce_mode_guard(
        os.getenv("TRADING_MODE", "PAPER"),
        os.getenv("LIVE_APPROVAL_PHRASE", ""),
    )
    api_key = os.getenv("ALPACA_PAPER_API_KEY", "").strip()
    api_secret = os.getenv("ALPACA_PAPER_API_SECRET", "").strip()

    startup_msg = f"MODE: {mode} | TradingStock SW-04 Bot starting..."
    logger.info(startup_msg)
    send_telegram(startup_msg)

    if not api_key or not api_secret:
        raise RuntimeError(
            "Missing ALPACA_PAPER_API_KEY / ALPACA_PAPER_API_SECRET in .env. "
            "Fill .env locally (never paste keys in chat)."
        )

    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import MarketOrderRequest, StopLossRequest
    from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass

    client = TradingClient(api_key, api_secret, paper=(mode == "PAPER"))
    acct = client.get_account()
    equity = float(acct.equity)
    cash = float(acct.cash)
    logger.info(f"Account verified | ID={acct.id} | Status={acct.status} | Equity=${equity:.2f} | Cash=${cash:.2f}")

    state = BotState.load()
    state.mode = mode
    now_utc = datetime.now(timezone.utc)
    today_str = now_utc.strftime("%Y-%m-%d")
    state.last_heartbeat_utc = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    can_trade, reason = evaluate_risk_guards(state, equity, today_str)
    state.save()
    if not can_trade:
        logger.warning(f"NEW ENTRIES HALTED: {reason}")
        log_incident("HIGH", "paper_bot", reason, "Risk limit triggered", "Halted new entries; stops preserved")
        return

    # Load clean local daily bars for signal scan (or refresh via alpaca_intraday_downloader)
    bars = {}
    for sym in US_UNIVERSE:
        p = ROOT / "data" / "clean" / "us" / "1d" / f"{sym}.parquet"
        if p.exists():
            bars[sym] = pd.read_parquet(p)

    # Check broker positions
    broker_pos = {p.symbol: p for p in client.get_all_positions()}
    open_slots = MAX_POSITIONS - len(broker_pos)
    if open_slots <= 0:
        logger.info(f"Max slots full ({len(broker_pos)}/{MAX_POSITIONS}). No new entries.")
        return

    cands = [c for c in scan_sw04_signals(bars) if c["symbol"] not in broker_pos]
    logger.info(f"SW-04 scan complete: {len(cands)} candidate(s) found.")

    for cand in cands[:open_slots]:
        sym = cand["symbol"]
        entry_est = cand["signal_close"]
        stop_p = cand["suggested_stop"]
        qty, risk_usd = calculate_position_size(equity, cash, entry_est, stop_p)
        if qty <= 0:
            logger.info(f"Skipping {sym}: qty=0 under 2% risk / 25% slot / cash constraints.")
            continue

        # OTO order: Entry + mandatory exchange-side Stop-Loss attached atomically
        req = MarketOrderRequest(
            symbol=sym,
            qty=qty,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
            order_class=OrderClass.OTO,
            stop_loss=StopLossRequest(stop_price=stop_p),
        )
        try:
            order = client.submit_order(req)
            logger.info(f"SUBMITTED OTO BUY {sym} qty={qty} stop=${stop_p} order_id={order.id}")
            state.open_positions[sym] = {
                "order_id": str(order.id),
                "qty": qty,
                "entry_est": entry_est,
                "stop": stop_p,
                "risk_usd": risk_usd,
                "entry_date": today_str,
            }
            cash -= qty * entry_est
            state.save()
            send_telegram(f"[多] {sym}, 预估价 ${entry_est}\n止损 ${stop_p}, 数量 {qty} 股 (风险 ${risk_usd})\n策略 SW-04 ({mode})")
        except Exception as e:
            logger.error(f"Order failed for {sym}: {e}")
            log_incident("HIGH", "paper_bot", f"Order submit failed for {sym}: {e}", "Broker API error", "No infinite retry; alerted user")


if __name__ == "__main__":
    run_alpaca_paper_cycle()
