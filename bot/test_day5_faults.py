"""
Day 5 Deliberate Fault, Stop-Loss, Circuit-Breaker & Crash-Restart Self-Test.
Tests every safety invariant without touching any real broker account or polluting production logs.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import paper_bot
import health_check


def run_all_tests() -> None:
    # Redirect incidents.md to temp file during self-test so production incidents.md stays clean
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        paper_bot.INCIDENTS_MD = tmp / "incidents_test.md"
        state_file = tmp / "state_test.json"

        # TEST 1: Live-mode guard blocks without exact phrase
        try:
            paper_bot.enforce_mode_guard("LIVE", "")
            raise AssertionError("Should have blocked LIVE mode without approval!")
        except PermissionError:
            print("[PASS] Test 1: MODE=LIVE blocked without '可以上实盘'")
        assert paper_bot.enforce_mode_guard("PAPER") == "PAPER"
        assert paper_bot.enforce_mode_guard("LIVE", "可以上实盘") == "LIVE"

        # TEST 2: Hard rule — No stop-loss -> No position
        for bad_stop in (None, 0.0, 100.0, 105.0):
            try:
                paper_bot.calculate_position_size(1000.0, 1000.0, 100.0, bad_stop)  # type: ignore
                raise AssertionError(f"Should have blocked stop={bad_stop}")
            except ValueError:
                pass
        print("[PASS] Test 2: Missing/invalid stop-loss strictly blocked")

        # TEST 3: Risk-based sizing (2% risk = $20, 25% max slot = $250 on $1000)
        qty, risk = paper_bot.calculate_position_size(1000.0, 1000.0, 50.0, 45.0)
        # stop_dist = $5 (10% stop), 2% risk = $20 -> target_alloc = $200 -> 4 shares ($200 <= $250 slot)
        assert qty == 4 and risk == 20.0, f"Unexpected sizing: qty={qty}, risk={risk}"
        qty2, risk2 = paper_bot.calculate_position_size(1000.0, 1000.0, 50.0, 48.0)
        # stop_dist = $2 (4% stop), 2% risk -> $500 target, capped by 25% slot ($250) -> 5 shares
        assert qty2 == 5 and risk2 == 10.0, f"Slot cap failed: qty={qty2}, risk={risk2}"
        print(f"[PASS] Test 3: Risk sizing & 25% slot cap verified (qty={qty}/$20 risk, capped qty={qty2}/$10 risk)")

        # TEST 4: Daily -5% loss cap halts new entries
        st = paper_bot.BotState(high_water_mark=1000.0, day_utc="2026-11-21", day_start_equity=1000.0)
        ok, reason = paper_bot.evaluate_risk_guards(st, 949.0, "2026-11-21")
        assert not ok and "DAILY_LOSS_CAP" in reason and st.halted_new_entries
        print(f"[PASS] Test 4: Daily -5% loss cap triggered halt ({reason})")

        # TEST 5: -15% Circuit Breaker halts permanently until manual reset
        st2 = paper_bot.BotState(high_water_mark=1000.0, day_utc="2026-11-21", day_start_equity=920.0)
        ok2, reason2 = paper_bot.evaluate_risk_guards(st2, 845.0, "2026-11-21")
        assert not ok2 and st2.circuit_breaker_triggered
        # Even on next day, circuit breaker MUST remain latched!
        ok_next, _ = paper_bot.evaluate_risk_guards(st2, 845.0, "2026-11-22")
        assert not ok_next and st2.circuit_breaker_triggered
        print(f"[PASS] Test 5: -15% Circuit Breaker latched across days ({reason2})")

        # TEST 6: Crash-Restart atomic state persistence
        st2.open_positions["NVDA"] = {"qty": 2, "stop": 118.50}
        st2.save(state_file)
        recovered = paper_bot.BotState.load(state_file)
        assert recovered.circuit_breaker_triggered is True
        assert recovered.high_water_mark == 1000.0
        assert recovered.open_positions["NVDA"]["stop"] == 118.50
        print("[PASS] Test 6: Crash-restart state recovery verified")

        # TEST 7: Hourly Health Check catches missing exchange stop-loss & stale heartbeat
        now = datetime.now(timezone.utc)
        st3 = paper_bot.BotState(
            high_water_mark=1000.0,
            day_utc="2026-11-21",
            day_start_equity=1000.0,
            last_heartbeat_utc=(now - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            open_positions={"NVDA": {"qty": 2, "stop": 118.50}},
        )
        ok_hc, issues = health_check.run_health_check(
            state=st3,
            broker_positions={"NVDA": {"qty": 2}},
            broker_stop_orders=set(),  # Simulate missing stop on exchange!
            current_equity=1000.0,
            now_utc=now,
        )
        assert not ok_hc and len(issues) == 2 and st3.halted_new_entries
        assert paper_bot.INCIDENTS_MD.exists()
        print(f"[PASS] Test 7: Hourly Health Check caught missing stop + stale heartbeat ({issues})")

        # TEST 8: Risk wall integration (risk/engine.py enforces max positions, daily loss, and HWM DD)
        q_max, _ = paper_bot.calculate_position_size(1000.0, 500.0, 50.0, 45.0, symbol="SPY", open_positions=4)
        q_loss, _ = paper_bot.calculate_position_size(1000.0, 1000.0, 50.0, 45.0, symbol="SPY", pnl_today=-50.0)
        q_dd, _ = paper_bot.calculate_position_size(850.0, 850.0, 50.0, 45.0, symbol="SPY", high_water_mark=1000.0)
        assert q_max == 0 and q_loss == 0 and q_dd == 0, f"Risk wall bypass detected: {(q_max, q_loss, q_dd)}"
        print("[PASS] Test 8: paper_bot.calculate_position_size strictly enforces risk/engine.py wall")

    print("\nALL 8 DAY-5 FAULT & RISK-WALL TESTS PASSED!")


if __name__ == "__main__":
    run_all_tests()
