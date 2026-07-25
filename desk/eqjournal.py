"""Journal + dashboard data for the equity desk."""
from __future__ import annotations
import json
from pathlib import Path
from . import eqbacktest as bt

DOCS=Path("docs"); OUT=Path("state")

def write_all(store, cfg, extra=None):
    DOCS.mkdir(exist_ok=True); OUT.mkdir(exist_ok=True)
    cap=float(cfg["account"]["starting_capital"])
    closed=store.closed_trades(2000); stats=bt.summarise(closed, cap); curve=store.equity_curve()
    a=store.active_strategy()
    payload={"generated":(curve[-1]["ts"] if curve else ""),"capital":cap,
        "equity":(curve[-1]["equity"] if curve else cap),"stats":stats,
        "open":store.open_trades(),"closed":closed[:60],
        "curve":[{"ts":c["ts"],"equity":c["equity"]} for c in curve][-500:],
        "strategy":{"version":a["version"] if a else 0,"name":a["name"] if a else "none",
                    "rationale":a["rationale"] if a else "","spec":a["spec"] if a else {},
                    "backtest":json.loads(a["backtest"]) if a and a.get("backtest") else {}},
        "reviews":store.reviews(8),"journal":store.journal(120),**(extra or {})}
    (DOCS/"data.json").write_text(json.dumps(payload, indent=1, default=str))
    _md(store, stats, a, closed)

def _md(store, stats, a, closed):
    L=["# Equity Desk — MTF — Trading Journal",""]
    if a: L+=[f"**v{a['version']} — {a['name']}**","",a["rationale"] or "",""]
    L+=["## Performance",""]+[f"- **{k}**: {v}" for k,v in stats.items()]
    L+=["","## Closed trades","","| entry | symbol | sh | in | out | days | reason | interest | net |","|---|---|---|---|---|---|---|---|---|"]
    for t in closed[:100]:
        L.append(f"| {t['entry_ts']} | {t['symbol']} | {t['shares']} | {t['entry_px']} | {t.get('exit_px')} | {t.get('held_days')} | {t.get('exit_reason')} | {t.get('mtf_interest')} | **{t.get('net_pnl')}** |")
    (OUT/"JOURNAL.md").write_text("\n".join(L))
