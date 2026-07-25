"""Order-book walk — shared helper. The equity desk uses this for depth-aware
fills; everything option-specific was removed when this desk was scoped to
cash equity."""
from __future__ import annotations

def walk_book(depth, qty, side="BUY"):
    if not depth: return None
    levels=sorted(depth, key=lambda d: float(d["price"]), reverse=(side=="SELL"))
    need,cost=qty,0.0
    for lv in levels:
        take=min(need,int(lv.get("quantity") or 0))
        if take<=0: continue
        cost+=take*float(lv["price"]); need-=take
        if need<=0: return cost/qty
    return None
