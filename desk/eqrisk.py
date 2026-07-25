"""MTF-aware risk gate for the equity desk.

Sizes off the technical stop (not a fixed lot), respects your rules — up to 5
stocks, up to 70% of capital deployed as own-margin, moderate leverage — and
prices in MTF interest for the expected hold so a swing that only works before
interest is refused.

Order of checks: kill switch -> drawdown -> hold-day sweep -> session ->
position count -> per-stock cap -> gross exposure -> sizing -> interest sanity.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from . import clock


@dataclass
class Decision:
    approved: bool = False
    shares: int = 0
    notional: float = 0.0
    own_margin: float = 0.0
    funded: float = 0.0
    stop_px: float = 0.0
    target_px: float = 0.0
    risk_amount: float = 0.0
    expected_interest: float = 0.0
    reasons: list = field(default_factory=list)
    checks: dict = field(default_factory=dict)

    def block(self, why): self.approved = False; self.reasons.append(why); return self


class EquityRiskGate:
    def __init__(self, cfg, store, mtf):
        self.cfg = cfg
        self.cap = cfg["risk_ceiling"]
        self.mtf_cfg = cfg["mtf"]
        self.store = store
        self.mtf = mtf
        self.start = float(cfg["account"]["starting_capital"])

    def equity(self, unrealised=0.0):
        return self.start + self.store.realised_total() + unrealised

    def halted(self, eq, day):
        peak = max(self.store.peak_equity(self.start), self.start)
        dd = 100 * (peak - eq) / peak if peak else 0
        if dd >= self.cap["kill_switch_drawdown_pct"]:
            return True, f"KILL SWITCH: drawdown {dd:.1f}% — manual reset"
        if self.store.realised_today(day) <= -self.start * self.cap["max_daily_loss_pct"] / 100:
            return True, "daily loss halt"
        wk_start = (dt.date.fromisoformat(day)
                    - dt.timedelta(days=dt.date.fromisoformat(day).weekday())).isoformat()
        if self.store.realised_since(wk_start) <= -self.start * self.cap["max_weekly_loss_pct"] / 100:
            return True, "weekly loss halt"
        return False, ""

    def evaluate(self, symbol, price, structure_feats, spec, ts,
                 unrealised, open_positions, intraday=False):
        d = Decision()
        day = ts.date().isoformat()
        eq = self.equity(unrealised)
        d.checks["equity"] = round(eq, 2)

        halted, why = self.halted(eq, day)
        if halted:
            return d.block(why)

        t = ts.time()
        if t < clock.parse_hhmm(self.cfg["session"]["no_entry_before"]):
            return d.block("before entry window")
        if t >= clock.parse_hhmm(self.cfg["session"]["no_entry_after"]):
            return d.block("past entry cutoff")

        if len(open_positions) >= self.cap["max_positions"]:
            return d.block(f"already at {self.cap['max_positions']} positions")
        if any(p["symbol"] == symbol for p in open_positions):
            return d.block("already long this stock")

        # --- stop from the technical structure: below nearest support ---
        stop_pct = max(structure_feats.get("dist_to_support_pct", 3.0), 0.8)
        stop_px = round(price * (1 - stop_pct / 100), 2)
        target_pct = structure_feats.get("dist_to_resistance_pct", stop_pct * 2)
        target_px = round(price * (1 + target_pct / 100), 2)

        margin_pct = self.mtf_cfg["default_margin_pct"] / 100
        risk_budget = eq * self.cap["max_risk_per_trade_pct"] / 100
        risk_per_share = price - stop_px
        if risk_per_share <= 0:
            return d.block("degenerate stop")
        shares = int(risk_budget / risk_per_share)
        if shares < 1:
            return d.block(f"1 share risks Rs{risk_per_share:.0f} > budget Rs{risk_budget:.0f}")

        notional = price * shares
        own = self.mtf.own_margin(notional, margin_pct)

        # --- per-stock cap ---
        max_stock = eq * self.cap["max_per_stock_pct"] / 100
        if own > max_stock:
            shares = int(max_stock / (price * margin_pct))
            notional = price * shares
            own = self.mtf.own_margin(notional, margin_pct)
            d.reasons.append(f"trimmed to per-stock cap ({shares} sh)")
        if shares < 1:
            return d.block("per-stock cap leaves <1 share")

        # --- gross exposure across the book (own-margin, your 70% rule) ---
        deployed = sum(self.mtf.own_margin(p["entry_px"] * p["shares"], margin_pct)
                       for p in open_positions)
        max_deploy = eq * self.mtf_cfg["max_gross_exposure_pct"] / 100
        if deployed + own > max_deploy:
            room = max_deploy - deployed
            shares = int(room / (price * margin_pct))
            notional = price * shares
            own = self.mtf.own_margin(notional, margin_pct)
            d.reasons.append(f"trimmed to 70% gross cap ({shares} sh)")
        if shares < 1:
            return d.block(f"gross exposure cap reached (Rs{deployed:,.0f} deployed)")

        # --- leverage cap ---
        if notional > eq * self.mtf_cfg["max_leverage"]:
            return d.block("leverage cap")

        # --- MTF interest for the expected hold vs the target ---
        funded = self.mtf.funded_amount(notional, margin_pct)
        hold = 1 if intraday else self.cap["max_hold_days"]
        interest = self.mtf.interest(funded, 0 if intraday else hold)
        gross_target = (target_px - price) * shares
        rt_cost = self.mtf.round_trip(price, target_px, shares,
                                      0 if intraday else hold, margin_pct).total
        if rt_cost > gross_target * 0.5:
            return d.block(f"costs Rs{rt_cost:,.0f} eat >50% of Rs{gross_target:,.0f} "
                           f"target (incl Rs{interest:,.0f} interest over {hold}d)")

        d.approved = True
        d.shares, d.notional, d.own_margin, d.funded = shares, notional, own, funded
        d.stop_px, d.target_px = stop_px, target_px
        d.risk_amount = round(risk_per_share * shares, 2)
        d.expected_interest = round(interest, 2)
        d.checks.update({"own_margin": round(own, 2), "funded": round(funded, 2),
                         "leverage": round(notional / eq, 2),
                         "interest_over_hold": round(interest, 2),
                         "roundtrip_cost": round(rt_cost, 2)})
        d.reasons.append(
            f"{shares} sh @ Rs{price:.1f} = Rs{notional:,.0f} notional "
            f"(own Rs{own:,.0f}, funded Rs{funded:,.0f}), risk Rs{d.risk_amount:,.0f}, "
            f"stop {stop_px} target {target_px}")
        return d
