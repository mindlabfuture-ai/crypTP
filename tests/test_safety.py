import pytest
from types import SimpleNamespace as NS

from cryptp.dashboard import render_html, render_text, build_report, trend_state
from cryptp.executor import LiveExecutor
from cryptp.planner import TradePlan
from cryptp.safety import (SafetyError, check_perp_order, isolated_leverage, liquidation_price, safety_cfg,
                           verify_exchange_stop)
import pandas as pd


def plan(side="buy", entry=100.0, stop=98.0):
    d = 1 if side == "buy" else -1
    return TradePlan(symbol="SUI/USDT:USDT", side=side, entry=entry, stop=stop, targets=[entry + d * 3, entry + d * 6],
                     fractions=[0.5, 0.5], risk_per_unit=abs(entry - stop))


S = safety_cfg()


def test_liquidation_and_leverage_helpers():
    assert liquidation_price("buy", 100, 3, 0.5) == pytest.approx(100 * (1 - (1 / 3 - 0.005)))
    assert liquidation_price("sell", 100, 3, 0.5) > 100
    assert isolated_leverage(2500, 1000, 3) == 3 and isolated_leverage(50, 1000, 3) == 1 and isolated_leverage(9000, 1000, 3) == 3


def test_ok_order_passes_and_each_rule_blocks():
    ok, why = check_perp_order(plan(), 10, 1000, 3, S, last_price=100.1, funding_rate_8h_pct=0.01)
    assert ok, why
    assert not check_perp_order(plan(), 40, 1000, 3, S)[0]                                    # 4x leverage
    assert not check_perp_order(plan(stop=101), 10, 1000, 3, S)[0]                            # stop on the wrong side
    assert not check_perp_order(plan(), 10, 1000, 3, S, last_price=101.0)[0]                  # drifted 1%
    assert not check_perp_order(plan(), 10, 1000, 3, S, last_price=97.0)[0]                   # already through the stop
    assert not check_perp_order(plan(), 10, 1000, 3, S, funding_rate_8h_pct=0.10)[0]          # long pays 0.10%/8h
    assert check_perp_order(plan(), 10, 1000, 3, S, funding_rate_8h_pct=-0.10)[0]             # long RECEIVES: fine
    assert not check_perp_order(plan("sell", 100, 102), 10, 1000, 3, S, funding_rate_8h_pct=-0.10)[0]   # short pays
    assert not check_perp_order(plan(), 0.001, 1000, 3, S, min_qty=0.1)[0]


def test_stop_too_close_to_liquidation_blocked():
    ok, why = check_perp_order(plan(entry=100, stop=70), 25, 1000, 3, S)      # 30% stop at 3x: liq ~33% away
    assert not ok and any("liquidation" in w for w in why)


class FakeEx:
    def __init__(self, stop_on_exchange=True, fund=0.01, last=100.0):
        self.calls, self.stop_on_exchange, self.fund, self.last = [], stop_on_exchange, fund, last
        self.pos = 0.0

    def fetch_balance(self): return {"USDT": {"total": 1000.0}}
    def fetch_ticker(self, s): return {"last": self.last}
    def fetch_funding_rate(self, s): return {"fundingRate": self.fund / 100}
    def market(self, s): return {"limits": {"amount": {"min": 0.1}, "cost": {"min": 5}}}
    def amount_to_precision(self, s, q): return f"{q:.2f}"
    def price_to_precision(self, s, p): return f"{p:.2f}"
    def set_margin_mode(self, m, s, params=None): self.calls.append(("margin", m, params))
    def set_leverage(self, l, s): self.calls.append(("lev", l))

    def create_order(self, s, t, side, q, price=None, params=None):
        self.calls.append(("order", t, side, q, params))
        if t == "market" and not (params or {}).get("reduceOnly"):
            self.pos = float(q)
        if (params or {}).get("reduceOnly") and t == "market":
            self.pos = 0.0
        return {"id": "1"}

    def fetch_positions(self, syms=None):
        return [{"symbol": "SUI/USDT:USDT", "contracts": self.pos, "side": "long",
                 "stopLossPrice": 98.0 if self.stop_on_exchange else None, "info": {}}]

    def cancel_all_orders(self, s): self.calls.append(("cancel",))


@pytest.fixture
def live(monkeypatch, tmp_path):
    monkeypatch.setenv("CRYPTP_ALLOW_LIVE", "yes")
    return lambda ex: LiveExecutor(ex, None, 3.0, str(tmp_path / "KILL"))


def test_live_entry_sets_isolated_and_attaches_stop(live):
    ex = FakeEx()
    live(ex).submit(plan(), 10)
    assert ("margin", "isolated", {"leverage": 1}) in ex.calls
    mk = [c for c in ex.calls if c[0] == "order" and c[1] == "market"][0]
    assert mk[4]["stopLoss"] == "98.00"


def test_live_blocks_before_any_order(live):
    ex = FakeEx(fund=0.2)
    with pytest.raises(SafetyError):
        live(ex).submit(plan(), 10)
    assert not [c for c in ex.calls if c[0] == "order"]


def test_missing_exchange_stop_flattens_and_writes_kill(live, tmp_path):
    ex = FakeEx(stop_on_exchange=False)
    lx = live(ex)
    with pytest.raises(SafetyError):
        lx.submit(plan(), 10)
    assert ex.pos == 0.0 and (tmp_path / "KILL").exists()
    with pytest.raises(SafetyError):                                     # kill switch blocks the next entry
        lx.submit(plan(), 10)


def test_verify_exchange_stop_rejects_wrong_price():
    ex = FakeEx(); ex.pos = 1.0
    assert verify_exchange_stop(ex, "SUI/USDT:USDT", "buy", 98.0)[0]
    assert not verify_exchange_stop(ex, "SUI/USDT:USDT", "buy", 95.0)[0]


def _daily(closes):
    ts = pd.date_range("2024-01-01", periods=len(closes), freq="D", tz="UTC")
    return pd.DataFrame({"ts": ts, "open": closes, "high": closes, "low": closes, "close": closes, "volume": 1.0})


def test_dashboard_shows_funding_one_decimal_and_flags_expensive_longs():
    df = _daily([1.0] * 250 + [2.0] * 5 + [2.0])
    st = trend_state(df, "SUI/USDT:USDT", 200, now=pd.Timestamp("2030-01-01", tz="UTC").to_pydatetime(), funding_ann_pct=27.46)
    assert st["state"] == "LONG" and st["funding_30d_pct"] == pytest.approx(27.46 * 30 / 365)
    rep = build_report([st])
    assert "+27.5%" in render_text(rep) and "HIGH FUNDING" in render_text(rep)
    h = render_html(rep)
    assert "27.5%/yr" in h and "Longs pay 27.5%/yr" in h and "Long carry, 30 days" in h
    cheap = trend_state(df, "SUI/USDT:USDT", 200, now=pd.Timestamp("2030-01-01", tz="UTC").to_pydatetime(), funding_ann_pct=5.0)
    assert "Longs pay" not in render_html(build_report([cheap]))
