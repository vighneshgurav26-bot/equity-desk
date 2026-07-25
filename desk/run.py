"""Equity desk entrypoint — screen -> technical read -> bull/bear -> MTF risk gate
-> paper trade -> journal -> self-review. One cycle per invocation.

  python -m desk.run            one cycle (cron / Actions)
  python -m desk.run --loop     continuous (VPS)
  python -m desk.run --review   force a review
  python -m desk.run --reset    wipe state
"""
from __future__ import annotations
import argparse, datetime as dt, json, sys, time, traceback
from pathlib import Path
import yaml

from . import clock, technicals, eqstrategy as strat, eqbacktest as bt, eqjournal as journal
from .eqstore import Store
from .mtf import MTFModel
from .eqrisk import EquityRiskGate
from .eqengine import EquityEngine
from .eqbrain import EquityBrain
from . import eqdata

CFG = Path("config.yaml")

class Desk:
    def __init__(self, cfg):
        self.cfg=cfg; self.store=Store(); self.mtf=MTFModel(cfg)
        self.risk=EquityRiskGate(cfg, self.store, self.mtf)
        self.engine=EquityEngine(cfg, self.store, self.mtf)
        self.brain=EquityBrain(cfg)
        self.provider=eqdata.get_provider(cfg)

    def collect(self, symbols, ts):
        quotes, structs, feats = {}, {}, {}
        tg=self.cfg["technical_gate"]
        for sym in symbols:
            try:
                daily=self.provider.daily(sym, 400)
                q=self.provider.quote(sym)
            except Exception as e:
                self.store.log(ts.isoformat(), "DATA", f"{sym} fetch failed", str(e)[:150], sym); continue
            if not q or len(daily)<tg["min_history_days"]:
                continue
            st=technicals.analyse(daily)
            f=technicals.features(st, q["ltp"])
            # liquidity: avg turnover
            avg_turnover_cr=sum(c["c"]*c["v"] for c in daily[-20:])/20/1e7
            f["avg_turnover_cr"]=round(avg_turnover_cr,1)
            quotes[sym], structs[sym], feats[sym] = q, st, f
            self.store.save_structure(ts.isoformat(timespec="seconds"), sym, q["ltp"], st.phase, f)
        return quotes, structs, feats

    def ensure_strategy(self, ts):
        a=self.store.active_strategy()
        if a: return a
        spec,notes=strat.clamp(strat.SEED_SPEC, self.cfg)
        self.store.save_strategy(1, spec["name"], spec, spec["rationale"], {"mode":"seed"}, ts.isoformat(timespec="seconds"))
        self.store.log(ts.isoformat(), "STRATEGY", "Seeded strategy v1", spec["name"])
        return self.store.active_strategy()

    def screen(self, feats, ts):
        """Liquidity + volatility + clean-structure filter before strategy rules."""
        tg=self.cfg["technical_gate"]; lq=self.cfg["liquidity"]
        keep=[]; ranking=[]
        for sym,f in feats.items():
            fails=[]
            if f["price"]<lq["min_price"]: fails.append(f"price<{lq['min_price']}")
            if f.get("avg_turnover_cr",0)<lq["min_avg_turnover_cr"]: fails.append(f"turnover {f.get('avg_turnover_cr')}cr low")
            if not (tg["min_atr_pct"]<=f["atr_pct"]<=tg["max_atr_pct"]): fails.append(f"atr {f['atr_pct']}%")
            if f["phase_confidence"]<tg["min_phase_confidence"]: fails.append(f"phase conf {f['phase_confidence']}")
            ranking.append({"symbol":sym,"phase":("acc" if f["wyckoff_phase_score"]>0.9 else
                            "markup" if f["wyckoff_phase_score"]>0 else "dist/down"),
                            "score":round(f["phase_confidence"]*f.get("reward_risk_to_levels",0),2),
                            "tradable":not fails,"why":fails})
            if not fails: keep.append(sym)
        ranking.sort(key=lambda r:-r["score"])
        self.store.log(ts.isoformat(timespec="seconds"), "SCREEN",
                       f"Clean structure: {keep or 'none'}",
                       " | ".join(f"{r['symbol']}:{r['phase']} s={r['score']}"+(f" X {r['why'][0]}" if r['why'] else "") for r in ranking[:12]),
                       payload={"ranking":ranking})
        return keep

    def cycle(self, force_review=False):
        ts=clock.now(); active=self.ensure_strategy(ts); spec=active["spec"]; version=active["version"]
        pool=list(dict.fromkeys((spec.get("universe") or [])+self.cfg["universe"]["stocks"]))[:self.cfg["universe"]["max_watch"]]

        if not clock.is_market_open(ts):
            self.store.log(ts.isoformat(timespec="seconds"), "IDLE", "Market closed", f"{ts:%a %d %b %H:%M} IST")
            if force_review or self._review_due(version, ts): self.review(version, spec, ts)
            journal.write_all(self.store, self.cfg); return

        quotes, structs, feats = self.collect(pool, ts)
        if not quotes:
            self.store.log(ts.isoformat(timespec="seconds"), "IDLE", "No data this cycle", "provider blocked or returned nothing")
            journal.write_all(self.store, self.cfg); return

        self.engine.manage(quotes, ts)
        upnl, marked = self.engine.unrealised(quotes, ts)
        eq=self.risk.equity(upnl); day=ts.date().isoformat()
        deployed=sum(p["own_margin"] for p in self.store.open_trades())
        self.store.mark_equity(ts.isoformat(timespec="seconds"), eq, self.store.realised_total(), upnl,
                               len(self.store.open_trades()), round(100*deployed/eq,1) if eq else 0, self.store.realised_today(day))

        halted, why = self.risk.halted(eq, day)
        if halted:
            self.store.log(ts.isoformat(timespec="seconds"), "RISK", "Trading halted", why)
            journal.write_all(self.store, self.cfg); return

        tradable=self.screen(feats, ts)
        candidates=[]
        for sym in tradable:
            ok,fails=strat.evaluate(spec.get("entry",{}), feats[sym])
            if ok: candidates.append(sym)
        if not candidates:
            self.store.log(ts.isoformat(timespec="seconds"), "SCAN", "No entry setup",
                           " | ".join(f"{s}:{structs[s].phase} rr={feats[s].get('reward_risk_to_levels')}" for s in tradable[:8]))
        else:
            self._consider(candidates, quotes, structs, feats, spec, version, ts)

        if force_review or self._review_due(version, ts): self.review(version, spec, ts)
        journal.write_all(self.store, self.cfg, {"structures":feats, "market_open":True,
                          "marked":[{k:v for k,v in m.items() if k not in ('entry_structure','debate')} for m in marked]})

    def _consider(self, candidates, quotes, structs, feats, spec, version, ts):
        if not self.brain.available:
            self.store.log(ts.isoformat(timespec="seconds"), "SKIP", "Setup found but ANTHROPIC_API_KEY not set", "debate is mandatory"); return
        open_pos=self.store.open_trades()
        upnl,_=self.engine.unrealised(quotes, ts)
        for sym in candidates[:3]:
            try:
                d=self.brain.debate(sym, structs[sym], feats[sym], self.mtf, self.cfg)
            except Exception as e:
                self.store.log(ts.isoformat(timespec="seconds"), "ERROR", f"debate {sym} failed", str(e)[:150], sym); continue
            self.store.log(ts.isoformat(timespec="seconds"), "DEBATE", f"{sym} -> {d.get('verdict')} ({d.get('confidence',0):.2f})",
                           f"BULL: {d.get('bull','')[:400]}\n\nBEAR: {d.get('bear','')[:400]}", sym)
            if d.get("verdict")!="TAKE" or d.get("confidence",0)<0.55: continue
            dec=self.risk.evaluate(sym, quotes[sym]["ltp"], feats[sym], spec, ts, upnl, open_pos)
            self.store.log(ts.isoformat(timespec="seconds"), "RISK", f"{sym} gate: {'PASS' if dec.approved else 'BLOCK'}",
                           " | ".join(dec.reasons), sym, {"checks":dec.checks})
            if dec.approved:
                self.engine.enter(sym, quotes[sym]["ltp"], structs[sym], feats[sym], dec,
                                  d.get("thesis",""), d.get("confidence",0), json.dumps(d), version, ts)
                return

    def _review_due(self, version, ts):
        n=self.store.closed_count_since_version(version)
        if n>=self.cfg["brain"]["review_every_n_trades"]: return True
        last=self.store.last_trade_ts()
        idle=self.cfg["brain"]["review_after_idle_hours"]
        if last is None:
            a=self.store.active_strategy()
            if a and a["created_ts"]:
                return (ts-clock.to_ist(dt.datetime.fromisoformat(a["created_ts"]))).total_seconds()/3600>=idle
            return False
        return (ts-clock.to_ist(dt.datetime.fromisoformat(last))).total_seconds()/3600>=idle

    def review(self, version, spec, ts):
        if not self.brain.available: return
        closed=self.store.closed_trades(200, version); stats=bt.summarise(closed, self.cfg["account"]["starting_capital"])
        try: rv=self.brain.review({"strategy":spec,"performance":stats,
              "recent_trades":[{k:t.get(k) for k in ("symbol","entry_ts","exit_ts","exit_reason","held_days","mtf_interest","net_pnl","thesis")} for t in closed[:30]],
              "note":"MTF interest is a real cost; a strategy that holds too long loses to it."})
        except Exception as e:
            self.store.log(ts.isoformat(timespec="seconds"), "ERROR", "review failed", str(e)[:150]); return
        if not rv: return
        self.store.log(ts.isoformat(timespec="seconds"), "REVIEW", f"v{version}: {rv.get('action')}", (rv.get('lessons','')+' | '+rv.get('diagnosis',''))[:900])
        self.store.save_review(ts.isoformat(timespec="seconds"), "auto", version, version, stats, rv.get("lessons",""), rv.get("changes","kept"), json.dumps(rv))

def main():
    ap=argparse.ArgumentParser()
    for a in ("--loop","--review","--reset"): ap.add_argument(a, action="store_true")
    ap.add_argument("--interval", type=int, default=0); A=ap.parse_args()
    cfg=yaml.safe_load(CFG.read_text())
    if A.reset:
        for p in (Path("state/desk.db"),Path("docs/data.json")):
            if p.exists(): p.unlink()
        print("state cleared"); return 0
    desk=Desk(cfg); interval=A.interval or cfg["data"]["snapshot_interval_sec"]
    while True:
        try: desk.cycle(force_review=A.review)
        except Exception:
            traceback.print_exc()
            desk.store.log(clock.now().isoformat(timespec="seconds"), "ERROR", "cycle crashed", traceback.format_exc()[-700:])
        if not A.loop: break
        time.sleep(interval)
    return 0

if __name__=="__main__": sys.exit(main())
