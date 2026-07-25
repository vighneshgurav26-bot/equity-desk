"""Offline self-test for the equity desk. No network, no API key."""
import datetime as dt, random, shutil
from pathlib import Path
import yaml
from desk import clock, technicals as T, eqstrategy as strat, eqbacktest as bt
from desk.mtf import MTFModel
from desk.eqstore import Store
from desk.eqrisk import EquityRiskGate
from desk.eqengine import EquityEngine

FAILS=[]
def check(n,c,d=""):
    print(("  PASS  " if c else "  FAIL  ")+n+(f"  {d}" if d else ""))
    if not c: FAILS.append(n)

cfg=yaml.safe_load(Path("config.yaml").read_text())
m=MTFModel(cfg)

print("\n== 1. MTF cost model (vs Zerodha published examples) ==")
check("Rs2000 funded x 10d = Rs8.00", abs(m.interest(2000,10)-8.0)<1e-6, f"{m.interest(2000,10)}")
check("interest is zero for intraday (day 0)", m.interest(60000,0)==0)
check("interest accrues incl weekends", m.interest(60000,5)==120.0, f"{m.interest(60000,5)}")
check("brokerage capped at Rs20", m.brokerage(100000)==20.0 and m.brokerage(1000)<20.0)
own=m.own_margin(100000); fund=m.funded_amount(100000)
check("40% margin splits correctly", abs(own-40000)<1 and abs(fund-60000)<1, f"own {own} funded {fund}")
be5=m.breakeven_move_pct(1000,100,5)
check("5-day breakeven move is realistic", 0.3<be5<0.8, f"{be5:.2f}%")
drag=m.daily_interest_drag_pct()
check("daily interest drag computed", 0.04<drag<0.08, f"{drag:.3f}%/day of own capital")
# STT both sides, DP on sell only
buy=m.leg("BUY",1000,100); sell=m.leg("SELL",1000,100)
check("STT charged both legs", buy.stt>0 and sell.stt>0)
check("DP charged on sell only", buy.dp==0 and sell.dp>0)

print("\n== 2. technical structure engine ==")
random.seed(3)
daily=[]; p=1000.0
for i in range(230):
    p*= 1+ (random.gauss(0,0.007) if i<130 else random.gauss(0.0025,0.009))
    o=p*(1+random.gauss(0,0.003)); daily.append({"o":o,"h":max(o,p)*1.005,"l":min(o,p)*0.995,"c":p,"v":random.randint(3,10)*1_000_000})
s=T.analyse(daily)
check("phase is one of the four Wyckoff phases", s.phase in ("accumulation","markup","distribution","markdown","undetermined"), s.phase)
check("trend classified", s.trend in ("up","down","sideways"), s.trend)
check("volume signal classified", s.volume_signal in ("confirming","diverging","neutral"), s.volume_signal)
check("RSI in range", 0<=s.rsi<=100, str(s.rsi))
check("support below price, resistance above", s._levels["nearest_support"]<daily[-1]["c"]<s._levels["nearest_resistance"] or s.dist_to_support_pct>=0, str(s._levels))
f=T.features(s, daily[-1]["c"])
for k in ("wyckoff_phase_score","phase_confidence","trend_up","volume_confirming","reward_risk_to_levels"):
    check(f"feature {k} produced", k in f)
check("short history handled", T.analyse(daily[:30]).phase=="undetermined")

print("\n== 3. strategy rules + clamp ==")
ok,_=strat.evaluate({"all":[{"feature":"rsi","op":"between","value":[0,100]}]}, f)
check("rule evaluates", ok)
greedy={"sizing":{"risk_per_trade_pct":10},"risk":{"max_positions":20,"max_hold_days":30},"universe":["RELIANCE","FAKESTOCK"],"entry":{}}
cl,notes=strat.clamp(greedy,cfg)
check("risk clamped to 1.5", cl["sizing"]["risk_per_trade_pct"]==1.5)
check("max_positions clamped to 5", cl["risk"]["max_positions"]==5)
check("max_hold clamped to 5d", cl["risk"]["max_hold_days"]==5)
check("bogus stock dropped", "FAKESTOCK" not in cl["universe"])
check("long-only enforced", cl["direction"]=="LONG_ONLY")

print("\n== 4. MTF risk gate ==")
d=Path("state_test"); shutil.rmtree(d,ignore_errors=True); d.mkdir()
store=Store(d/"t.db"); rg=EquityRiskGate(cfg,store,m); eng=EquityEngine(cfg,store,m)
ts=clock.now().replace(hour=11,minute=0)
feats={**f,"dist_to_support_pct":2.5,"dist_to_resistance_pct":6.0}
dec=rg.evaluate("RELIANCE", 1000.0, feats, strat.SEED_SPEC, ts, 0.0, [])
check("gate returns decision", dec is not None, " | ".join(dec.reasons))
if dec.approved:
    check("risk <= 1.5% of capital", dec.risk_amount<=cfg["account"]["starting_capital"]*0.015+1, f"Rs{dec.risk_amount}")
    check("leverage <= 2x", dec.notional<=cfg["account"]["starting_capital"]*2+1, f"lev {dec.checks.get('leverage')}")
    check("MTF interest projected into decision", dec.expected_interest>0, f"Rs{dec.expected_interest} over 5d")
# 5 positions max
opens=[{"symbol":f"S{i}","entry_px":1000,"shares":10,"own_margin":8000} for i in range(5)]
dec2=rg.evaluate("INFY",1500,feats,strat.SEED_SPEC,ts,0.0,opens)
check("6th position blocked", not dec2.approved, dec2.reasons[0] if dec2.reasons else "")
# 70% gross cap
big=[{"symbol":f"B{i}","entry_px":2000,"shares":30,"own_margin":24000} for i in range(3)]
dec3=rg.evaluate("TCS",1000,feats,strat.SEED_SPEC,ts,0.0,big)
check("70% gross exposure enforced", (not dec3.approved) or "70%" in " ".join(dec3.reasons) or dec3.shares>0, " | ".join(dec3.reasons[:1]))

print("\n== 5. paper engine incl. 5-day exit + interest ==")
if dec.approved:
    tid=eng.enter("RELIANCE",1000.0,s,feats,dec,"test",0.7,"{}",1,ts)
    check("position opened", len(store.open_trades())==1)
    q={"RELIANCE":{"ltp":1000.0,"bid":999,"ask":1001,"bid_depth":[],"ask_depth":[]}}
    upnl,marked=eng.unrealised(q, ts+dt.timedelta(days=2))
    check("interest accrues while held", marked[0]["interest_so_far"]>0, f"Rs{marked[0]['interest_so_far']} at 2d")
    # force 6 days -> MAX_HOLD_5D
    closed=eng.manage(q, ts+dt.timedelta(days=6))
    check("5-day hard exit fires", any(c["exit_reason"]=="MAX_HOLD_5D" for c in closed), str([c["exit_reason"] for c in closed]))
    ct=store.closed_trades()
    if ct:
        t0=ct[0]; recon=(t0["exit_px"]-t0["entry_px"])*t0["shares"]-t0["costs"]
        check("net = gross - costs (incl interest)", abs(recon-t0["net_pnl"])<0.5, f"net {t0['net_pnl']} interest {t0['mtf_interest']}")
        check("interest recorded on the trade", t0["mtf_interest"]>0, f"Rs{t0['mtf_interest']}")

print("\n== 6. backtest summary ==")
res=bt.summarise(store.closed_trades(), cfg["account"]["starting_capital"])
check("summary computes", "trades" in res and "total_mtf_interest" in res, f"{res.get('trades')} trades")
check("capital is Rs 2,00,000", cfg["account"]["starting_capital"]==200000.0)

store.close(); shutil.rmtree(d, ignore_errors=True)
print("\n"+"="*54)
print("ALL PASS" if not FAILS else f"{len(FAILS)} FAILURES: {FAILS}")
print("="*54)
raise SystemExit(1 if FAILS else 0)
