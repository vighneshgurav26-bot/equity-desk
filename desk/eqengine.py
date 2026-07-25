"""Paper execution for MTF equity positions: entries, daily marking, stops,
targets, the 5-day hard exit, and per-day interest accrual.
"""
from __future__ import annotations

import datetime as dt
import json
from . import clock


class EquityEngine:
    def __init__(self, cfg, store, mtf):
        self.cfg = cfg
        self.store = store
        self.mtf = mtf

    def _held_days(self, entry_ts, now):
        d0 = clock.to_ist(dt.datetime.fromisoformat(entry_ts)).date()
        return (now.date() - d0).days

    def unrealised(self, quotes, ts):
        total, marked = 0.0, []
        margin = self.cfg["mtf"]["default_margin_pct"] / 100
        for t in self.store.open_trades():
            q = quotes.get(t["symbol"])
            px = q["ltp"] if q else t["entry_px"]
            held = self._held_days(t["entry_ts"], ts)
            gross = (px - t["entry_px"]) * t["shares"]
            funded = self.mtf.funded_amount(t["entry_px"] * t["shares"], margin)
            interest = self.mtf.interest(funded, held)
            exit_cost = self.mtf.round_trip(t["entry_px"], px, t["shares"],
                                            held, margin).total
            upnl = gross - exit_cost
            total += upnl
            marked.append({**t, "live_px": px, "held_days": held,
                           "interest_so_far": round(interest, 2), "upnl": round(upnl, 2)})
        return total, marked

    def enter(self, symbol, price, structure, feats, decision, thesis,
              confidence, debate, version, ts, intraday=False):
        q = decision
        entry = self.mtf.fill_price("BUY", price)
        trade = {
            "strategy_version": version, "symbol": symbol,
            "shares": q.shares, "entry_ts": ts.isoformat(timespec="seconds"),
            "entry_px": entry, "status": "OPEN",
            "stop_px": q.stop_px, "target_px": q.target_px,
            "own_margin": q.own_margin, "funded": q.funded,
            "intraday": 1 if intraday else 0,
            "mfe_px": entry, "mae_px": entry,
            "entry_structure": json.dumps(structure.to_dict()),
            "entry_features": json.dumps(feats),
            "thesis": thesis, "confidence": confidence, "debate": debate,
        }
        tid = self.store.insert_trade(trade)
        self.store.log(ts.isoformat(timespec="seconds"), "ENTRY",
                       f"BUY {q.shares} {symbol} @ {entry} (MTF)",
                       f"notional Rs{q.notional:,.0f} own Rs{q.own_margin:,.0f} "
                       f"funded Rs{q.funded:,.0f} | stop {q.stop_px} target {q.target_px} "
                       f"| {structure.phase} | {thesis[:160]}",
                       symbol, {"trade_id": tid, "checks": q.checks})
        return tid

    def manage(self, quotes, ts):
        closed = []
        margin = self.cfg["mtf"]["default_margin_pct"] / 100
        sq = clock.parse_hhmm(self.cfg["session"]["intraday_square_off"])
        for t in self.store.open_trades():
            q = quotes.get(t["symbol"])
            if not q:
                continue
            px = self.mtf.fill_price("SELL", q["ltp"], q.get("bid"), q.get("ask"),
                                     q.get("bid_depth"), t["shares"])
            held = self._held_days(t["entry_ts"], ts)
            t["mfe_px"] = max(t.get("mfe_px", px), px)
            t["mae_px"] = min(t.get("mae_px", px), px)
            self.store.update_trade(t["id"], mfe_px=t["mfe_px"], mae_px=t["mae_px"])

            reason = None
            if t.get("intraday") and ts.time() >= sq:
                reason = "INTRADAY_SQUAREOFF"
            elif px <= t["stop_px"]:
                reason = "STOP"
            elif px >= t["target_px"]:
                reason = "TARGET"
            elif held >= self.cfg["risk_ceiling"]["max_hold_days"]:
                reason = "MAX_HOLD_5D"        # your swing limit, enforced
            if reason:
                closed.append(self._close(t, px, reason, ts, held, margin))
        return closed

    def _close(self, t, px, reason, ts, held, margin):
        gross = (px - t["entry_px"]) * t["shares"]
        cb = self.mtf.round_trip(t["entry_px"], px, t["shares"], held, margin)
        net = gross - cb.total
        self.store.update_trade(
            t["id"], status="CLOSED", exit_ts=ts.isoformat(timespec="seconds"),
            exit_px=px, exit_reason=reason, gross_pnl=round(gross, 2),
            costs=round(cb.total, 2), mtf_interest=round(cb.mtf_interest, 2),
            net_pnl=round(net, 2), held_days=held)
        self.store.log(ts.isoformat(timespec="seconds"), "EXIT",
                       f"SELL {t['shares']} {t['symbol']} @ {px} — {reason}",
                       f"net Rs{net:,.0f} (gross {gross:,.0f} - costs {cb.total:,.0f}, "
                       f"of which interest Rs{cb.mtf_interest:,.0f} over {held}d)",
                       t["symbol"], {"trade_id": t["id"]})
        return {**t, "exit_px": px, "net_pnl": net, "exit_reason": reason}
