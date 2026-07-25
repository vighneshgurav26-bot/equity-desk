"""Backtest for the equity desk. Replay technical structures across stored
daily history; summarise with MTF interest included."""
from __future__ import annotations
import statistics

def summarise(trades, capital):
    if not trades: return {"trades":0,"note":"no trades"}
    pnls=[t["net_pnl"] for t in trades]; wins=[p for p in pnls if p>0]; losses=[p for p in pnls if p<=0]
    eq=capital; peak=capital; mdd=0
    for p in pnls: eq+=p; peak=max(peak,eq); mdd=max(mdd,peak-eq)
    interest=sum(t.get("mtf_interest",0) or 0 for t in trades)
    return {"trades":len(trades),"net_pnl":round(sum(pnls),2),
            "return_pct":round(100*sum(pnls)/capital,2),
            "win_rate_pct":round(100*len(wins)/len(pnls),1),
            "avg_win":round(statistics.fmean(wins),2) if wins else 0,
            "avg_loss":round(statistics.fmean(losses),2) if losses else 0,
            "expectancy":round(statistics.fmean(pnls),2),
            "profit_factor":round(sum(wins)/abs(sum(losses)),3) if losses and sum(losses)!=0 else None,
            "max_drawdown":round(mdd,2),"max_dd_pct":round(100*mdd/capital,2),
            "total_mtf_interest":round(interest,2),
            "interest_as_pct_of_gross_loss":round(100*interest/abs(sum(losses)),1) if losses and sum(losses)<0 else 0,
            "exit_reasons":_c([t.get("exit_reason","?") for t in trades]),
            "avg_hold_days":round(statistics.fmean([t.get("held_days",0) or 0 for t in trades]),1)}

def _c(xs):
    o={}
    for x in xs: o[x]=o.get(x,0)+1
    return o
