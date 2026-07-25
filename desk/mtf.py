"""Zerodha MTF (Margin Trading Facility) cost + leverage model.

Verified against zerodha.com/charges and the MTF FAQ, 25-Jul-2026:

  Interest    0.04%/day (~14.6% p.a.) on the FUNDED amount, from T+1,
              charged every calendar day incl. weekends/holidays until sold.
  Brokerage   0.3% or Rs 20 per executed order, whichever is LOWER (both legs).
  Pledge      Rs 15 + GST per ISIN, once, on buy.
  Unpledge    Rs 15 + GST per ISIN, once, on sell.
  STT         0.1% on buy AND sell (delivery equity).
  Exchange    NSE ~0.00297% per side.
  SEBI        Rs 10 / crore.  Stamp: 0.015% on buy.  GST: 18% on (brokerage+txn+sebi).
  DP charge   Rs 15.34 per scrip on sell (CDSL fee + Zerodha), qty-independent.

The interest is the whole reason a swing desk needs its own model: hold a
Rs 1,00,000 funded position 5 days and that is Rs 200 gone before the stock
moves. A day trader never sees it (intraday MTF is squared off same day, T+1
never arrives); a 5-day swing pays it five times over, weekends included. If it
is not in the P&L the desk is lying to itself.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass
class EquityCosts:
    brokerage: float = 0.0
    stt: float = 0.0
    exchange: float = 0.0
    sebi: float = 0.0
    stamp: float = 0.0
    gst: float = 0.0
    dp: float = 0.0
    pledge: float = 0.0
    mtf_interest: float = 0.0
    total: float = 0.0

    def to_dict(self) -> dict:
        return {k: round(v, 2) for k, v in asdict(self).items()}

    def __add__(self, o: "EquityCosts") -> "EquityCosts":
        return EquityCosts(**{k: getattr(self, k) + getattr(o, k) for k in asdict(self)})


class MTFModel:
    def __init__(self, cfg: dict):
        c = cfg["costs"]
        self.brk_pct = float(c["brokerage_pct"]) / 100.0
        self.brk_cap = float(c["brokerage_cap"])
        self.stt_pct = float(c["stt_pct"]) / 100.0
        self.exch_pct = float(c["exchange_pct"]) / 100.0
        self.sebi_pct = float(c["sebi_pct"]) / 100.0
        self.stamp_pct = float(c["stamp_buy_pct"]) / 100.0
        self.gst_pct = float(c["gst_pct"]) / 100.0
        self.dp_per_sell = float(c["dp_charge_per_scrip"])
        self.pledge_fee = float(c["pledge_unpledge_fee"])
        self.mtf_daily = float(c["mtf_interest_pct_per_day"]) / 100.0
        m = cfg["mtf"]
        self.default_margin = float(m["default_margin_pct"]) / 100.0
        self.slippage_pct = float(c.get("slippage_pct", 0.05)) / 100.0

    # ---------- leverage ----------
    def funded_amount(self, notional: float, margin_pct: float | None = None) -> float:
        """Portion Zerodha lends = notional minus the client's own margin."""
        m = margin_pct if margin_pct is not None else self.default_margin
        return max(notional * (1.0 - m), 0.0)

    def own_margin(self, notional: float, margin_pct: float | None = None) -> float:
        m = margin_pct if margin_pct is not None else self.default_margin
        return notional * m

    def brokerage(self, turnover: float) -> float:
        return min(turnover * self.brk_pct, self.brk_cap)

    # ---------- fills ----------
    def fill_price(self, side: str, ltp: float, bid: float = 0.0,
                   ask: float = 0.0, depth: list | None = None,
                   qty: int = 0) -> float:
        if depth and qty > 0:
            from .liquidity import walk_book
            vwap = walk_book(depth, qty, side)
            if vwap is not None:
                return round(vwap, 2)
        if bid and ask and ask > bid > 0:
            return round(ask if side == "BUY" else bid, 2)
        slip = ltp * self.slippage_pct
        return round(ltp + slip if side == "BUY" else ltp - slip, 2)

    # ---------- charges ----------
    def leg(self, side: str, price: float, qty: int) -> EquityCosts:
        t = price * qty
        c = EquityCosts()
        c.brokerage = self.brokerage(t)
        c.stt = t * self.stt_pct                 # delivery: both sides
        c.exchange = t * self.exch_pct
        c.sebi = t * self.sebi_pct
        if side == "BUY":
            c.stamp = t * self.stamp_pct
            c.pledge = self.pledge_fee * 1.18     # auto-pledge on MTF buy
        else:
            c.dp = self.dp_per_sell
            c.pledge = self.pledge_fee * 1.18     # unpledge on sell
        c.gst = (c.brokerage + c.exchange + c.sebi) * self.gst_pct
        c.total = (c.brokerage + c.stt + c.exchange + c.sebi + c.stamp
                   + c.gst + c.dp + c.pledge)
        return c

    def interest(self, funded: float, days_held: int) -> float:
        """From T+1, every calendar day incl. weekends. day 0 (intraday) = free."""
        chargeable = max(days_held, 0)
        return funded * self.mtf_daily * chargeable

    def round_trip(self, entry: float, exit_px: float, qty: int,
                   days_held: int, margin_pct: float | None = None) -> EquityCosts:
        c = self.leg("BUY", entry, qty) + self.leg("SELL", exit_px, qty)
        funded = self.funded_amount(entry * qty, margin_pct)
        c.mtf_interest = self.interest(funded, days_held)
        c.total += c.mtf_interest
        return c

    def breakeven_move_pct(self, entry: float, qty: int, days_held: int,
                           margin_pct: float | None = None) -> float:
        """% the stock must rise just to cover all charges + interest."""
        notional = entry * qty
        if notional <= 0:
            return 100.0
        rt = self.round_trip(entry, entry, qty, days_held, margin_pct)
        return 100.0 * rt.total / notional

    def daily_interest_drag_pct(self, margin_pct: float | None = None) -> float:
        """What one extra day of holding costs, as % of the OWN capital at risk.
        This is what makes 'not more than 5 days' a real rule, not a slogan."""
        m = margin_pct if margin_pct is not None else self.default_margin
        if m <= 0:
            return 0.0
        return 100.0 * self.mtf_daily * (1.0 - m) / m
