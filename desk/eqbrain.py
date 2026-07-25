"""Claude layer for the equity desk: bull/bear debate on the technical structure,
plus self-review. Analyst persona, but strictly technicals — no fundamentals,
because this desk has none to give it and inventing them would be worse than
useless."""
from __future__ import annotations
import json, os, re, requests
API="https://api.anthropic.com/v1/messages"

class EquityBrain:
    def __init__(self, cfg):
        self.cfg=cfg; self.model=cfg["brain"]["model"]; self.max=cfg["brain"]["max_tokens"]
        self.key=os.environ.get("ANTHROPIC_API_KEY","")
    @property
    def available(self): return bool(self.key)
    def _call(self, system, user, mx=None):
        r=requests.post(API, timeout=120, headers={"x-api-key":self.key,
            "anthropic-version":"2023-06-01","content-type":"application/json"},
            json={"model":self.model,"max_tokens":mx or self.max,"system":system,
                  "messages":[{"role":"user","content":user}]})
        r.raise_for_status()
        return "".join(b.get("text","") for b in r.json().get("content",[]) if b.get("type")=="text")
    @staticmethod
    def _json(t):
        t=re.sub(r"^```(?:json)?|```$","",t.strip(),flags=re.M).strip()
        try: return json.loads(t)
        except: 
            m=re.search(r"\{.*\}",t,re.S)
            return json.loads(m.group(0)) if m else None

    CTX="""You run a TECHNICALS-ONLY equity swing desk on NSE, Rs 2,00,000 paper,
trading Nifty large caps on Zerodha MTF (margin funding). Holds are intraday to
5 days maximum.

You are a seasoned technician. You read Wyckoff phase, trend structure, volume
confirmation, support/resistance and momentum. You do NOT have fundamentals —
no financials, no concalls, no valuation. Do not invent them or reason as if you
had them. If a call needs fundamental confirmation you don't have, that lowers
your confidence; say so.

The economics you fight: MTF costs 0.04%/day interest on the funded portion,
charged every calendar day incl. weekends, from T+1. Hold 5 days and that plus
round-trip charges is ~0.4-0.5% of notional before the stock moves. A swing that
only works on a fast move is a loser once it drags. Favour setups where the
nearest resistance is comfortably further than the nearest support (reward:risk),
volume confirms, and the move can plausibly complete inside 5 sessions."""

    def debate(self, symbol, structure, feats, mtf, cfg):
        margin=cfg["mtf"]["default_margin_pct"]/100
        be5=mtf.breakeven_move_pct(feats["price"], 100, 5, margin)
        payload={"symbol":symbol,"structure":structure.to_dict(),
                 "features":feats,"levels":getattr(structure,"_levels",{}),
                 "breakeven_move_pct_over_5d_incl_interest":round(be5,2)}
        sys=self.CTX+"""

Run a bull case and a bear case on THIS stock's technical structure, then a
verdict. Bull: why the phase/trend/volume/level structure supports a long that
completes within 5 days. Bear: attack it — is it late in markup, is volume
diverging, is resistance too close to pay for the interest, is RSI stretched?
Default to NO. Reply ONLY JSON:
{"bull":"...","bear":"...","verdict":"TAKE"|"SKIP","confidence":0.0-1.0,
 "thesis":"one sentence","invalidation":"what breaks it","key_risk":"..."}"""
        out=self._json(self._call(sys, json.dumps(payload, default=str), 1500))
        if not out or out.get("verdict") not in ("TAKE","SKIP"):
            return {"verdict":"SKIP","confidence":0.0,"thesis":"unusable brain output","bull":"","bear":""}
        return out

    def review(self, ctx):
        sys=self.CTX+"""

You are reviewing this desk's own closed trades. Be honest. Look at exit reasons:
lots of MAX_HOLD_5D with small losses means entries lacked momentum and interest
ate them; lots of STOP means entries were late or stops too tight. Check whether
MTF interest is a meaningful share of the losses. Reply ONLY JSON:
{"lessons":"3-5 sentences","diagnosis":"the main problem","action":"KEEP"|"TWEAK"|"REPLACE","changes":"plain english","confidence":0.0-1.0}"""
        return self._json(self._call(sys, json.dumps(ctx, default=str)[:50000], 1500))
