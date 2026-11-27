import unittest

from risk.engine import Proposal, check


class TestRiskEngine(unittest.TestCase):
    def test_valid_long_approved_by_slot_cap(self):
        # Equity $1,000, risk 2% = $20; stop dist $5 -> risk qty = 4 shares ($400 notional)
        # Slot cap 25% = $250 -> capped to 2.5 shares
        p = Proposal(symbol="SPY", side="buy", entry=100.0, stop=95.0, target=110.0)
        qty, status = check(p, equity=1000.0, exposure=0.0, open_positions=0, pnl_today=0.0, high_water_mark=1000.0)
        self.assertEqual(status, "APPROVED")
        self.assertAlmostEqual(qty, 2.5)

    def test_valid_long_approved_by_risk_budget(self):
        # Stop dist 10% ($10) -> risk qty = $20 / $10 = 2.0 shares ($200 notional < $250 slot cap)
        p = Proposal(symbol="NVDA", side="buy", entry=100.0, stop=90.0, target=115.0)
        qty, status = check(p, equity=1000.0, exposure=0.0, open_positions=1, pnl_today=0.0, high_water_mark=1000.0)
        self.assertEqual(status, "APPROVED")
        self.assertAlmostEqual(qty, 2.0)

    def test_valid_trend_following_without_fixed_target(self):
        p = Proposal(symbol="QQQ", side="buy", entry=100.0, stop=90.0, target=None)
        qty, status = check(p, equity=1000.0, exposure=250.0, open_positions=1, pnl_today=0.0, high_water_mark=1000.0)
        self.assertEqual(status, "APPROVED")
        self.assertAlmostEqual(qty, 2.0)

    def test_reject_short_on_long_only_desk(self):
        p = Proposal(symbol="SPY", side="sell", entry=100.0, stop=105.0, target=90.0)
        qty, status = check(p, equity=1000.0, exposure=0.0, open_positions=0, pnl_today=0.0)
        self.assertEqual(qty, 0.0)
        self.assertIn("long-only", status)

    def test_reject_daily_loss_limit_hit(self):
        p = Proposal(symbol="SPY", side="buy", entry=100.0, stop=95.0, target=110.0)
        qty, status = check(p, equity=1000.0, exposure=0.0, open_positions=0, pnl_today=-50.0)
        self.assertEqual(qty, 0.0)
        self.assertIn("daily loss", status)

    def test_reject_hwm_circuit_breaker(self):
        p = Proposal(symbol="SPY", side="buy", entry=100.0, stop=95.0, target=110.0)
        qty, status = check(p, equity=850.0, exposure=0.0, open_positions=0, pnl_today=0.0, high_water_mark=1000.0)
        self.assertEqual(qty, 0.0)
        self.assertIn("circuit breaker", status)

    def test_reject_max_positions(self):
        p = Proposal(symbol="AAPL", side="buy", entry=100.0, stop=95.0, target=110.0)
        qty, status = check(p, equity=1000.0, exposure=500.0, open_positions=4, pnl_today=0.0)
        self.assertEqual(qty, 0.0)
        self.assertIn("too many open positions", status)

    def test_reject_stop_on_wrong_side(self):
        p = Proposal(symbol="AAPL", side="buy", entry=100.0, stop=105.0, target=115.0)
        qty, status = check(p, equity=1000.0, exposure=0.0, open_positions=0, pnl_today=0.0)
        self.assertEqual(qty, 0.0)
        self.assertIn("stop must be below entry", status)

    def test_reject_reward_too_small(self):
        p = Proposal(symbol="AAPL", side="buy", entry=100.0, stop=95.0, target=106.0)
        qty, status = check(p, equity=1000.0, exposure=0.0, open_positions=0, pnl_today=0.0)
        self.assertEqual(qty, 0.0)
        self.assertIn("reward too small", status)

    def test_reject_stop_too_tight_or_too_wide(self):
        tight = Proposal(symbol="SPY", side="buy", entry=100.0, stop=99.5, target=105.0)
        qty1, status1 = check(tight, equity=1000.0, exposure=0.0, open_positions=0, pnl_today=0.0)
        self.assertEqual(qty1, 0.0)
        self.assertIn("stop distance", status1)

        wide = Proposal(symbol="TSLA", side="buy", entry=100.0, stop=80.0, target=140.0)
        qty2, status2 = check(wide, equity=1000.0, exposure=0.0, open_positions=0, pnl_today=0.0)
        self.assertEqual(qty2, 0.0)
        self.assertIn("stop distance", status2)

    def test_reject_no_exposure_room_left(self):
        p = Proposal(symbol="MSFT", side="buy", entry=100.0, stop=95.0, target=110.0)
        qty, status = check(p, equity=1000.0, exposure=1000.0, open_positions=3, pnl_today=0.0)
        self.assertEqual(qty, 0.0)
        self.assertIn("no exposure room", status)

    def test_capped_by_remaining_exposure_room(self):
        # Remaining room $100 -> max 1.0 share at $100
        p = Proposal(symbol="MSFT", side="buy", entry=100.0, stop=95.0, target=110.0)
        qty, status = check(p, equity=1000.0, exposure=900.0, open_positions=3, pnl_today=0.0)
        self.assertEqual(status, "APPROVED")
        self.assertAlmostEqual(qty, 1.0)


if __name__ == "__main__":
    unittest.main()
