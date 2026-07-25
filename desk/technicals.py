"""Technical structure engine — the whole analytical core of this desk.

Your prompt's TECHNICAL STRUCTURE brief, made computable:
  - Where is the stock in its trend cycle? -> Wyckoff phase
    (accumulation / markup / distribution / markdown)
  - Key support and resistance -> swing pivots + round numbers
  - Is volume confirming price or diverging? -> volume/price agreement

Everything is derived from daily candles (swing) with an intraday overlay, all
from Kite. No fundamentals, by design — this desk was scoped technicals-only.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass


# ------------------------------------------------------------------ helpers
def sma(v, n):
    return statistics.fmean(v[-n:]) if len(v) >= n else (statistics.fmean(v) if v else 0.0)


def ema(v, n):
    if not v:
        return 0.0
    k = 2 / (n + 1)
    e = v[0]
    for x in v[1:]:
        e = x * k + e * (1 - k)
    return e


def rsi(closes, n=14):
    if len(closes) < n + 1:
        return 50.0
    gains, losses = [], []
    for a, b in zip(closes[-n - 1:-1], closes[-n:]):
        d = b - a
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    ag, al = statistics.fmean(gains), statistics.fmean(losses)
    if al == 0:
        return 100.0
    rs = ag / al
    return round(100 - 100 / (1 + rs), 2)


def atr_pct(candles, n=14):
    if len(candles) < n + 1:
        return 0.0
    trs = []
    for p, c in zip(candles[-n - 1:-1], candles[-n:]):
        trs.append(max(c["h"] - c["l"], abs(c["h"] - p["c"]), abs(c["l"] - p["c"])))
    last = candles[-1]["c"]
    return round(100 * statistics.fmean(trs) / last, 3) if last else 0.0


def swings(candles, lookback=3):
    """Fractal swing highs/lows: a bar higher/lower than `lookback` neighbours."""
    highs, lows = [], []
    for i in range(lookback, len(candles) - lookback):
        w = candles[i - lookback:i + lookback + 1]
        c = candles[i]
        if c["h"] == max(x["h"] for x in w):
            highs.append((i, c["h"]))
        if c["l"] == min(x["l"] for x in w):
            lows.append((i, c["l"]))
    return highs, lows


def support_resistance(candles, price, k=3):
    """Nearest swing levels below (support) and above (resistance), plus round
    numbers — which act as real levels in Indian large caps."""
    highs, lows = swings(candles)
    res = sorted({round(h, 1) for _, h in highs if h > price})[:k]
    sup = sorted({round(l, 1) for _, l in lows if l < price}, reverse=True)[:k]
    step = 10 if price < 500 else (50 if price < 2000 else 100)
    rn_up = ((int(price) // step) + 1) * step
    rn_dn = (int(price) // step) * step
    return {"support": sup, "resistance": res,
            "round_above": rn_up, "round_below": rn_dn}


@dataclass
class Structure:
    phase: str = "undetermined"
    phase_confidence: float = 0.0
    trend: str = "sideways"          # up / down / sideways
    volume_signal: str = "neutral"   # confirming / diverging / neutral
    rsi: float = 50.0
    atr_pct: float = 0.0
    dist_to_resistance_pct: float = 0.0
    dist_to_support_pct: float = 0.0
    above_200dma: bool = False
    above_50dma: bool = False
    notes: list = None

    def to_dict(self):
        d = self.__dict__.copy()
        d["notes"] = self.notes or []
        return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in d.items()}

def analyse(daily: list[dict], intraday: list[dict] | None = None) -> Structure:
    """Full technical read from daily candles, with an optional intraday overlay."""
    s = Structure(notes=[])
    if len(daily) < 60:
        s.notes.append("insufficient history (<60 daily bars)")
        return s

    closes = [c["c"] for c in daily]
    vols = [c["v"] for c in daily]
    price = closes[-1]

    dma50, dma200 = sma(closes, 50), sma(closes, 200)
    s.above_50dma = price > dma50
    s.above_200dma = price > dma200
    s.rsi = rsi(closes)
    s.atr_pct = atr_pct(daily)

    # --- trend from the 50/200 structure and their slopes ---
    slope50 = closes[-1] - sma(closes[-60:-10], 50) if len(closes) >= 60 else 0
    if price > dma50 > dma200 and slope50 > 0:
        s.trend = "up"
    elif price < dma50 < dma200 and slope50 < 0:
        s.trend = "down"
    else:
        s.trend = "sideways"

    # --- volume confirmation over the last 10 bars ---
    recent = daily[-10:]
    up_vol = sum(c["v"] for c in recent if c["c"] >= c["o"])
    dn_vol = sum(c["v"] for c in recent if c["c"] < c["o"])
    avg_vol = sma(vols, 20)
    last_vol = vols[-1]
    price_up = closes[-1] > closes[-6]
    if price_up and up_vol > dn_vol * 1.2:
        s.volume_signal = "confirming"
    elif price_up and dn_vol > up_vol * 1.2:
        s.volume_signal = "diverging"
    elif not price_up and dn_vol > up_vol * 1.2:
        s.volume_signal = "confirming"
    elif not price_up and up_vol > dn_vol * 1.2:
        s.volume_signal = "diverging"
    else:
        s.volume_signal = "neutral"

    # --- Wyckoff phase: range position x trend x volume x momentum ---
    hi_60 = max(c["h"] for c in daily[-60:])
    lo_60 = min(c["l"] for c in daily[-60:])
    rng = hi_60 - lo_60
    pos = (price - lo_60) / rng if rng > 0 else 0.5
    vol_expanding = last_vol > avg_vol * 1.1

    phase, conf = "undetermined", 0.4
    if pos < 0.35 and s.trend != "down" and s.volume_signal != "diverging":
        phase, conf = "accumulation", 0.55 + (0.2 if vol_expanding else 0)
    elif pos < 0.35 and s.trend == "down":
        phase, conf = "markdown", 0.6 + (0.2 if vol_expanding else 0)
    elif pos > 0.65 and s.trend == "up" and s.volume_signal == "confirming":
        phase, conf = "markup", 0.6 + (0.15 if vol_expanding else 0)
    elif pos > 0.65 and (s.volume_signal == "diverging" or s.rsi > 70):
        phase, conf = "distribution", 0.55 + (0.2 if s.rsi > 72 else 0)
    elif 0.35 <= pos <= 0.65 and s.trend == "up":
        phase, conf = "markup", 0.5
    elif 0.35 <= pos <= 0.65 and s.trend == "down":
        phase, conf = "markdown", 0.5
    s.phase, s.phase_confidence = phase, round(min(conf, 0.9), 2)

    sr = support_resistance(daily, price)
    res = min(sr["resistance"] + [sr["round_above"]], key=lambda x: abs(x - price)) \
        if (sr["resistance"] or sr["round_above"]) else price * 1.05
    sup = min(sr["support"] + [sr["round_below"]], key=lambda x: abs(x - price)) \
        if (sr["support"] or sr["round_below"]) else price * 0.95
    s.dist_to_resistance_pct = round(100 * (res - price) / price, 2)
    s.dist_to_support_pct = round(100 * (price - sup) / price, 2)
    s._sr = sr
    s._levels = {"nearest_support": sup, "nearest_resistance": res,
                 "dma50": round(dma50, 2), "dma200": round(dma200, 2)}

    s.notes.append(f"{s.phase} (conf {s.phase_confidence}), {s.trend} trend, "
                   f"vol {s.volume_signal}, RSI {s.rsi}, "
                   f"{s.dist_to_support_pct}% above support / "
                   f"{s.dist_to_resistance_pct}% below resistance")
    return s


def features(structure: Structure, price: float) -> dict:
    """Flatten the structure into the desk's feature vocabulary."""
    lv = getattr(structure, "_levels", {})
    phase_score = {"accumulation": 1.0, "markup": 0.5, "distribution": -0.5,
                   "markdown": -1.0, "undetermined": 0.0}.get(structure.phase, 0.0)
    return {
        "price": price,
        "wyckoff_phase_score": phase_score,
        "phase_confidence": structure.phase_confidence,
        "trend_up": 1.0 if structure.trend == "up" else (-1.0 if structure.trend == "down" else 0.0),
        "volume_confirming": 1.0 if structure.volume_signal == "confirming"
                             else (-1.0 if structure.volume_signal == "diverging" else 0.0),
        "rsi": structure.rsi,
        "atr_pct": structure.atr_pct,
        "above_50dma": 1.0 if structure.above_50dma else 0.0,
        "above_200dma": 1.0 if structure.above_200dma else 0.0,
        "dist_to_resistance_pct": structure.dist_to_resistance_pct,
        "dist_to_support_pct": structure.dist_to_support_pct,
        "reward_risk_to_levels": round(
            structure.dist_to_resistance_pct / structure.dist_to_support_pct, 2)
            if structure.dist_to_support_pct > 0.1 else 0.0,
    }
