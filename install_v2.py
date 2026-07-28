"""ONE-SHOT: install the v3 relaxed strategy. Run once, then delete."""
import json, sys
sys.path.insert(0, ".")
import yaml
from desk import clock
from desk import eqstrategy as strat
from desk.eqstore import Store

V3 = json.loads(r"""{"name": "Wyckoff_v3_WideOpen", "rationale": "v3: phase_confidence 0.45->0.35, R:R 1.6->1.3, RSI band 40-72 -> 35-78, ATR band 1.0-6.0 -> 0.7-8.0. The 200-DMA trend filter moves into the any-of tier (50-DMA now also qualifies) so early trend turns are catchable. Only hard blocks left: no confirmed markdown phase, no RSI above 78. Position limits (5), 70% exposure cap, 5-day max hold and 1.5% risk are UNCHANGED \u2014 MTF interest makes those non-negotiable.", "universe": ["RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "SBIN", "AXISBANK", "KOTAKBANK", "BHARTIARTL", "LT", "ITC", "BAJFINANCE", "MARUTI", "TATAMOTORS", "TATASTEEL", "HINDALCO", "SUNPHARMA", "TITAN", "HCLTECH", "NESTLEIND", "WIPRO", "ULTRACEMCO", "POWERGRID", "NTPC", "ASIANPAINT"], "entry": {"all": [{"feature": "phase_confidence", "op": ">=", "value": 0.35}, {"feature": "reward_risk_to_levels", "op": ">=", "value": 1.3}, {"feature": "atr_pct", "op": "between", "value": [0.7, 8.0]}, {"feature": "rsi", "op": "between", "value": [35, 78]}], "any": [{"feature": "wyckoff_phase_score", "op": ">=", "value": 1.0}, {"feature": "wyckoff_phase_score", "op": "==", "value": 0.5}, {"feature": "volume_confirming", "op": ">", "value": 0.5}, {"feature": "trend_up", "op": ">", "value": 0.5}, {"feature": "above_200dma", "op": ">", "value": 0.5}, {"feature": "above_50dma", "op": ">", "value": 0.5}], "none": [{"feature": "rsi", "op": ">", "value": 78}, {"feature": "wyckoff_phase_score", "op": "<=", "value": -0.9}]}, "sizing": {"risk_per_trade_pct": 1.5}, "risk": {"max_positions": 5, "max_hold_days": 5, "intraday_fraction": 0.0}, "direction": "LONG_ONLY"}""")

cfg = yaml.safe_load(open("config.yaml"))
spec, notes = strat.clamp(V3, cfg)
st = Store()
nv = st.next_version()
st.save_strategy(nv, spec["name"], spec, spec["rationale"],
                 {"mode": "v3_relaxed"}, clock.now().isoformat(timespec="seconds"))
st.log(clock.now().isoformat(timespec="seconds"), "STRATEGY",
       "Installed v%d: %s" % (nv, spec["name"]),
       spec["rationale"][:300] + ((" | clamps: %s" % notes) if notes else ""))
print("Installed and activated v%d: %s" % (nv, spec["name"]))
