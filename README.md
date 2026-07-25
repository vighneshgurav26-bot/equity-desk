# Equity Desk — ₹2,00,000 — MTF stock swing (technicals-only)

A third, separate paper desk. Trades **Nifty large caps on Zerodha MTF**,
intraday to **5-day swings**, on **technical structure alone**. Own repo, own
state, own dashboard — independent of the two options desks.

## Why technicals-only (the honest scoping)

Your brief asked for a seasoned analyst reading annual reports, MD&A, concall
transcripts, Screener ratios and shareholding patterns. **None of those sources
are reachable by an unattended bot** — Screener 403s automated requests, NSE's
fundamentals API blocks datacentre IPs, and there is no free automatable feed
for Indian concalls or annual reports. A bot that "analyses fundamentals" it
can't actually read would hallucinate ROE trends and promoter-pledge flags on
real money decisions — worse than useless.

So this desk was deliberately scoped to what price and volume genuinely support:
the **TECHNICAL STRUCTURE** dimension of your brief, done properly.

## What it actually does

**Technical read** (from Kite daily candles):
- **Wyckoff phase** — accumulation / markup / distribution / markdown, with a
  confidence score.
- **Trend** — 50/200-DMA structure and slope.
- **Volume** — confirming or diverging vs price over the last 10 sessions.
- **Support / resistance** — swing pivots plus round numbers, and the
  reward:risk between nearest resistance and nearest support.
- RSI, ATR%, distance to levels.

**The pipeline mirrors your four images:** collect → technical read →
bull/bear debate → risk gate → verdict → MTF paper trade → journal → review.

**MTF economics, modelled exactly** (verified against zerodha.com/charges,
25 Jul 2026):
- Interest **0.04%/day (~14.6% p.a.)** on the funded portion, from T+1, charged
  every calendar day **including weekends** — so a 5-day hold pays 5 days of it.
- Brokerage 0.3% or ₹20 (lower), STT both sides, exchange, stamp, GST, DP,
  ₹15+GST pledge on buy and unpledge on sell.
- This is why the **5-day cap is hard**: interest turns a slow winner into a
  loser, and the gate refuses any setup whose costs eat more than half the
  target.

## Your rules, enforced as hard ceilings

| Rule | Setting | Where |
|---|---|---|
| Up to 5 stocks at once | `max_positions: 5` | risk gate |
| Up to 70% of capital deployed | `max_gross_exposure_pct: 70` | risk gate |
| Moderate risk | 1.5% risk/trade, 40% margin (1.67× leverage), 2× cap | config |
| Swing ≤ 5 days | `max_hold_days: 5` | engine forces exit |

The bot can tighten these; it cannot loosen them. `clamp()` silently caps any
strategy that tries.

## Setup

Same as the other desks (see SETUP.md in the options repo). Differences:
- Its **own** GitHub repo (or VPS folder). Never share a `state/` folder.
- `config.yaml` capital is ₹2,00,000.
- Uses Kite for quotes/depth/history; falls back to Yahoo daily candles.
- 15-minute cadence — a swing desk doesn't need minute polling.
- The Wyckoff strategy auto-installs on first run.

## Honest caveats

- **Technicals-only means no fundamental catalyst awareness.** It will trade a
  clean chart into an earnings shock it can't see. Overnight gap risk is real on
  multi-day holds. That's the trade-off you chose, and it's the honest one.
- Wyckoff phase detection is a heuristic over price/volume, not ground truth.
- Judge it on forward paper performance across a few weeks and both a trending
  and a choppy regime — not on any single week.
