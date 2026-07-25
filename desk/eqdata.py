"""Equity data: Kite for quotes/depth/candles, Yahoo as the daily fallback."""
from __future__ import annotations

import datetime as dt
import requests

YF = "https://query1.finance.yahoo.com/v8/finance/chart/{s}.NS"
_UA = {"User-Agent": "Mozilla/5.0 (compatible; equitydesk/1.0)"}


class YahooEquity:
    name = "yahoo"

    def daily(self, symbol, days=400):
        try:
            r = requests.get(YF.format(s=symbol),
                             params={"interval": "1d", "range": f"{days}d"},
                             headers=_UA, timeout=12)
            r.raise_for_status()
            js = r.json()["chart"]["result"][0]
        except Exception:
            return []
        ts = js.get("timestamp") or []
        q = js["indicators"]["quote"][0]
        out = []
        for i, t in enumerate(ts):
            o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
            if None in (o, h, l, c):
                continue
            out.append({"t": dt.date.fromtimestamp(t).isoformat(),
                        "o": float(o), "h": float(h), "l": float(l),
                        "c": float(c), "v": float(q.get("volume", [0]*len(ts))[i] or 0)})
        return out

    def quote(self, symbol):
        d = self.daily(symbol, 5)
        if not d:
            return None
        last = d[-1]
        return {"symbol": symbol, "ltp": last["c"], "bid": 0.0, "ask": 0.0,
                "bid_depth": [], "ask_depth": [], "volume": last["v"],
                "source": "yahoo"}


class KiteEquity:
    name = "kite"

    def __init__(self):
        import os
        from kiteconnect import KiteConnect
        self.kite = KiteConnect(api_key=os.environ["KITE_API_KEY"])
        tok = os.environ.get("KITE_ACCESS_TOKEN")
        if not tok:
            from pathlib import Path
            f = Path("state/kite_token.txt")
            tok = f.read_text().strip() if f.exists() else None
        if not tok:
            raise RuntimeError("no kite token")
        self.kite.set_access_token(tok)
        self._tokens = {}

    def _token(self, symbol):
        if not self._tokens:
            for i in self.kite.instruments("NSE"):
                if i["segment"] == "NSE" and i["instrument_type"] == "EQ":
                    self._tokens[i["tradingsymbol"]] = i["instrument_token"]
        return self._tokens.get(symbol)

    def quote(self, symbol):
        try:
            k = f"NSE:{symbol}"
            q = self.kite.quote([k])[k]
        except Exception:
            return None
        depth = q.get("depth", {})
        bd = [{"price": float(x["price"]), "quantity": int(x["quantity"])}
              for x in depth.get("buy", []) if x.get("price")]
        ad = [{"price": float(x["price"]), "quantity": int(x["quantity"])}
              for x in depth.get("sell", []) if x.get("price")]
        return {"symbol": symbol, "ltp": float(q.get("last_price") or 0),
                "bid": bd[0]["price"] if bd else 0.0,
                "ask": ad[0]["price"] if ad else 0.0,
                "bid_depth": bd, "ask_depth": ad,
                "volume": float(q.get("volume") or 0), "source": "kite"}

    def daily(self, symbol, days=400):
        tok = self._token(symbol)
        if not tok:
            return []
        to = dt.date.today()
        frm = to - dt.timedelta(days=int(days * 1.5))
        try:
            raw = self.kite.historical_data(tok, frm, to, "day")
        except Exception:
            return []
        return [{"t": c["date"].date().isoformat() if hasattr(c["date"], "date") else str(c["date"]),
                 "o": c["open"], "h": c["high"], "l": c["low"], "c": c["close"],
                 "v": float(c["volume"])} for c in raw]


def get_provider(cfg):
    want = cfg["data"]["provider"]
    if want in ("kite", "auto"):
        try:
            return KiteEquity()
        except Exception as e:
            if want == "kite":
                raise
            print(f"[eqdata] kite unavailable ({e}); using Yahoo daily")
    return YahooEquity()
