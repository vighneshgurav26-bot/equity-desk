"""SQLite store for the equity desk (trades carry MTF fields + technical structure)."""
from __future__ import annotations
import json, sqlite3
from pathlib import Path

SCHEMA="""
CREATE TABLE IF NOT EXISTS trades(
 id INTEGER PRIMARY KEY AUTOINCREMENT, strategy_version INT, symbol TEXT,
 shares INT, entry_ts TEXT, entry_px REAL, exit_ts TEXT, exit_px REAL,
 status TEXT DEFAULT 'OPEN', exit_reason TEXT, stop_px REAL, target_px REAL,
 own_margin REAL, funded REAL, intraday INT DEFAULT 0, held_days INT,
 mfe_px REAL, mae_px REAL, gross_pnl REAL, costs REAL, mtf_interest REAL,
 net_pnl REAL, entry_structure TEXT, entry_features TEXT, thesis TEXT,
 confidence REAL, debate TEXT);
CREATE TABLE IF NOT EXISTS equity(ts TEXT PRIMARY KEY, equity REAL, realised REAL,
 unrealised REAL, open_positions INT, deployed_pct REAL, day_pnl REAL);
CREATE TABLE IF NOT EXISTS strategies(version INT PRIMARY KEY, created_ts TEXT,
 name TEXT, spec TEXT, rationale TEXT, backtest TEXT, status TEXT, retired_ts TEXT);
CREATE TABLE IF NOT EXISTS reviews(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT,
 trigger TEXT, from_version INT, to_version INT, stats TEXT, lessons TEXT,
 changes TEXT, raw TEXT);
CREATE TABLE IF NOT EXISTS journal(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT,
 kind TEXT, symbol TEXT, headline TEXT, detail TEXT, payload TEXT);
CREATE TABLE IF NOT EXISTS structures(ts TEXT, symbol TEXT, price REAL,
 phase TEXT, features TEXT, PRIMARY KEY(ts, symbol));
"""

class Store:
    def __init__(self, path=Path("state/desk.db")):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db=sqlite3.connect(path, timeout=30); self.db.row_factory=sqlite3.Row
        self.db.executescript(SCHEMA); self.db.commit()
    def close(self): self.db.close()
    # trades
    def open_trades(self): return [dict(r) for r in self.db.execute("SELECT * FROM trades WHERE status='OPEN'")]
    def closed_trades(self, limit=500, version=None):
        q="SELECT * FROM trades WHERE status='CLOSED'"; a=[]
        if version is not None: q+=" AND strategy_version=?"; a.append(version)
        q+=" ORDER BY exit_ts DESC LIMIT ?"; a.append(limit)
        return [dict(r) for r in self.db.execute(q,a)]
    def insert_trade(self, t):
        cur=self.db.execute(f"INSERT INTO trades({','.join(t)}) VALUES({','.join('?'*len(t))})", list(t.values()))
        self.db.commit(); return cur.lastrowid
    def update_trade(self, tid, **f):
        self.db.execute(f"UPDATE trades SET {','.join(k+'=?' for k in f)} WHERE id=?", [*f.values(), tid]); self.db.commit()
    def realised_total(self):
        return float(self.db.execute("SELECT COALESCE(SUM(net_pnl),0) s FROM trades WHERE status='CLOSED'").fetchone()["s"])
    def realised_today(self, day):
        return float(self.db.execute("SELECT COALESCE(SUM(net_pnl),0) s FROM trades WHERE status='CLOSED' AND exit_ts LIKE ?",(f"{day}%",)).fetchone()["s"])
    def realised_since(self, ts):
        return float(self.db.execute("SELECT COALESCE(SUM(net_pnl),0) s FROM trades WHERE status='CLOSED' AND exit_ts>=?",(ts,)).fetchone()["s"])
    def closed_count_since_version(self, v):
        return self.db.execute("SELECT COUNT(*) c FROM trades WHERE status='CLOSED' AND strategy_version=?",(v,)).fetchone()["c"]
    def last_trade_ts(self):
        return self.db.execute("SELECT MAX(entry_ts) m FROM trades").fetchone()["m"]
    # equity
    def mark_equity(self, ts, eq, real, unreal, n, dep, day):
        self.db.execute("INSERT OR REPLACE INTO equity VALUES(?,?,?,?,?,?,?)",(ts,eq,real,unreal,n,dep,day)); self.db.commit()
    def equity_curve(self, limit=3000):
        return [dict(r) for r in reversed(list(self.db.execute("SELECT * FROM equity ORDER BY ts DESC LIMIT ?",(limit,))))]
    def peak_equity(self, default):
        r=self.db.execute("SELECT MAX(equity) m FROM equity").fetchone()
        return float(r["m"]) if r and r["m"] is not None else default
    # strategies
    def active_strategy(self):
        r=self.db.execute("SELECT * FROM strategies WHERE status='ACTIVE' ORDER BY version DESC LIMIT 1").fetchone()
        if not r: return None
        d=dict(r); d["spec"]=json.loads(d["spec"]); return d
    def save_strategy(self, v, name, spec, rat, bt, ts):
        self.db.execute("UPDATE strategies SET status='RETIRED', retired_ts=? WHERE status='ACTIVE'",(ts,))
        self.db.execute("INSERT OR REPLACE INTO strategies(version,created_ts,name,spec,rationale,backtest,status) VALUES(?,?,?,?,?,?,'ACTIVE')",
                        (v,ts,name,json.dumps(spec),rat,json.dumps(bt))); self.db.commit()
    def next_version(self):
        return int(self.db.execute("SELECT COALESCE(MAX(version),0) v FROM strategies").fetchone()["v"])+1
    def strategy_history(self, limit=20):
        return [dict(r) for r in self.db.execute("SELECT version,name,rationale,status,created_ts,backtest FROM strategies ORDER BY version DESC LIMIT ?",(limit,))]
    # reviews + journal + structures
    def save_review(self, ts, trig, frm, to, stats, lessons, changes, raw):
        self.db.execute("INSERT INTO reviews(ts,trigger,from_version,to_version,stats,lessons,changes,raw) VALUES(?,?,?,?,?,?,?,?)",
                        (ts,trig,frm,to,json.dumps(stats),lessons,changes,raw)); self.db.commit()
    def reviews(self, limit=20):
        return [dict(r) for r in self.db.execute("SELECT * FROM reviews ORDER BY id DESC LIMIT ?",(limit,))]
    def log(self, ts, kind, headline, detail="", symbol="", payload=None):
        self.db.execute("INSERT INTO journal(ts,kind,symbol,headline,detail,payload) VALUES(?,?,?,?,?,?)",
                        (ts,kind,symbol,headline,detail,json.dumps(payload or {}))); self.db.commit()
        print(f"[{kind}] {headline}"+(f" — {detail}" if detail else ""))
    def journal(self, limit=200):
        return [dict(r) for r in self.db.execute("SELECT * FROM journal ORDER BY id DESC LIMIT ?",(limit,))]
    def save_structure(self, ts, symbol, price, phase, feats):
        self.db.execute("INSERT OR REPLACE INTO structures VALUES(?,?,?,?,?)",(ts,symbol,price,phase,json.dumps(feats))); self.db.commit()
