"""Equity technical strategy: JSON rules over the technical feature vocabulary.
Same safe-data design as the options desks — the brain writes rules, never code.
"""
from __future__ import annotations
import copy
from . import technicals

OPS = {">":lambda a,b:a>b, ">=":lambda a,b:a>=b, "<":lambda a,b:a<b,
       "<=":lambda a,b:a<=b, "==":lambda a,b:abs(a-b)<1e-9,
       "between":lambda a,b:b[0]<=a<=b[1], "outside":lambda a,b:a<b[0] or a>b[1]}

def evaluate(rules, feats):
    fails=[]
    def chk(c):
        n=c.get("feature")
        if n not in feats: fails.append(f"unknown feature {n}"); return False
        f=OPS.get(c.get("op"))
        if not f: fails.append(f"unknown op {c.get('op')}"); return False
        ok=f(float(feats[n]), c["value"])
        if not ok: fails.append(f"{n}={feats[n]} fails {c['op']} {c['value']}")
        return ok
    ok=all(chk(c) for c in rules.get("all",[]))
    anys=rules.get("any",[])
    if anys and not any(chk(c) for c in anys): ok=False
    for c in rules.get("none",[]):
        if chk(c): fails.append(f"blocked by none:{c.get('feature')}"); ok=False
    return ok, fails

def clamp(spec, cfg):
    s=copy.deepcopy(spec); cap=cfg["risk_ceiling"]; notes=[]
    z=s.setdefault("sizing",{})
    if z.get("risk_per_trade_pct",99)>cap["max_risk_per_trade_pct"]:
        z["risk_per_trade_pct"]=cap["max_risk_per_trade_pct"]; notes.append("risk clamped")
    r=s.setdefault("risk",{})
    for k,ck in [("max_positions","max_positions"),("max_hold_days","max_hold_days")]:
        if r.get(k,99)>cap[ck]: r[k]=cap[ck]; notes.append(f"{k} clamped")
    allowed=set(cfg["universe"]["stocks"])
    uni=[u for u in s.get("universe",[]) if u in allowed]
    s["universe"]=uni or cfg["universe"]["stocks"][:8]
    s["direction"]="LONG_ONLY"   # MTF is long-only funded delivery
    return s, notes

SEED_SPEC={
  "name":"Wyckoff_Accumulation_Markup_VolConfirm",
  "rationale":(
    "Technicals-only equity swing on MTF. Buys stocks that are in Wyckoff "
    "accumulation turning to markup, above the 200-DMA, with volume confirming "
    "price and a nearest-resistance/nearest-support reward:risk of at least 1.8. "
    "Sizing is off the technical stop below support; the 5-day cap is hard "
    "because MTF interest turns a slow winner into a loser. No fundamentals — "
    "this desk was deliberately scoped to what can be computed from price and "
    "volume alone, rather than pretending to read financials it cannot reach."),
  "universe":["RELIANCE","HDFCBANK","ICICIBANK","INFY","TCS","LT","SBIN","AXISBANK"],
  "entry":{
    "all":[
      {"feature":"above_200dma","op":">","value":0.5},
      {"feature":"phase_confidence","op":">=","value":0.55},
      {"feature":"volume_confirming","op":">","value":0.5},
      {"feature":"reward_risk_to_levels","op":">=","value":1.8},
      {"feature":"atr_pct","op":"between","value":[1.0,6.0]},
      {"feature":"rsi","op":"between","value":[40,72]},
    ],
    "any":[
      {"feature":"wyckoff_phase_score","op":">=","value":1.0},   # accumulation
      {"feature":"wyckoff_phase_score","op":"==","value":0.5},   # markup
    ],
    "none":[
      {"feature":"rsi","op":">","value":72},
      {"feature":"trend_up","op":"<","value":0.0},
    ],
  },
  "sizing":{"risk_per_trade_pct":1.5},
  "risk":{"max_positions":5,"max_hold_days":5,"intraday_fraction":0.0},
}
