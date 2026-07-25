# Setup — step by step

## Read this first: two different "Kite connections"

They are not the same thing and mixing them up will waste an afternoon.

| | Kite ↔ Claude (MCP) | Kite ↔ the desk |
|---|---|---|
| What it is | The connector in the Claude app | The `kiteconnect` Python client |
| Auth | OAuth, you click through | API key + secret + daily token |
| Needs a Kite Connect app? | No | **Yes** |
| What it does | Lets Claude read prices *in chat* | Lets the bot read prices *while it runs* |

Having the first does **not** give you the second. The desk runs perfectly well
on the free NSE public feed — start there, and only set up a Kite Connect app
if you decide you want 5-level depth (see step A10).

## The package already contains a strategy

`state/desk.db` ships with **v1 `V1_Liquid_RVoverIV_NextWeekly`** already
installed, calibrated on live NIFTY/BANKNIFTY/RELIANCE/ICICIBANK books from
24 Jul 2026. You do not need to seed anything.

**Do not run `--reset` unless you want that gone.** It wipes the database.

---

Two paths. Pick one.

| | **A — VPS (recommended)** | **B — GitHub Actions** |
|---|---|---|
| Where | Your FXVM Windows VPS | GitHub's servers, free |
| Effort | ~30 min once | ~20 min once |
| Data | NSE public works, Kite works | NSE often blocked from cloud IPs |
| Runs | Continuous, every 60s | Every 5 min via cron |
| Cost | You already pay for it | Free |

**Take path A.** The desk wants to see the tape every minute, and nseindia.com
returns 403 to datacentre IPs often enough to make Actions frustrating. Path B
is documented in full at the bottom if you want it anyway.

---

# Part 0 — Before anything

### 0.1 Get an Anthropic API key

1. Go to **console.anthropic.com** → sign in
2. **Settings → API keys → Create key**, name it `optionsdesk`
3. Copy it now — it's shown once. Starts `sk-ant-`
4. **Billing → add credits.** Budget roughly:
   - one research call + one debate per signal, one review per 10 trades
   - realistically **₹150–400/month** on a quiet strategy, more if it trades often
5. Set a **spend limit** under Billing so a runaway loop can't surprise you

### 0.2 Decide on Kite (optional, do it later if you like)

The desk runs fine on the free NSE feed. Kite gives you real 5-level depth,
which is what makes the book-walk impact model exact rather than approximate.

If you want it:
1. **kite.trade** → sign up with your Zerodha client ID
2. Create an app → app type **Connect**, redirect URL `http://127.0.0.1/`
3. Note the **API key** and **API secret**
4. Cost: the charges page currently shows Kite Connect at **₹500/month**, with a
   "Personal: Free" tier listed. Check which applies to you before subscribing.

**The catch:** the Kite access token expires around 07:30 IST daily and the
login is interactive. That's a manual step every morning. Start on the NSE feed;
add Kite once you're happy the thing works.

---

# Part A — VPS setup (recommended)

## A1. Install Python

RDP into the VPS.

1. **python.org/downloads** → Windows installer, 3.11 or newer
2. Run it — **tick "Add python.exe to PATH"** on the first screen. This is the
   step everyone skips and then spends an hour debugging.
3. Open **Command Prompt** and confirm:

```
python --version
```

You want `Python 3.11.x` or higher. If it says "not recognized", PATH didn't get
set — re-run the installer and choose Modify → Advanced → Add to environment
variables.

## A2. Put the desk on disk

1. Unzip `optionsdesk.zip` to `C:\optionsdesk`
2. Confirm the layout — `C:\optionsdesk\config.yaml` and `C:\optionsdesk\desk\`
   should both exist. If you see `C:\optionsdesk\optionsdesk\config.yaml` you've
   got a nested folder; move things up one level.

```
cd C:\optionsdesk
dir
```

## A3. Install dependencies

```
cd C:\optionsdesk
python -m pip install --upgrade pip
python -m pip install requests PyYAML
```

Kite only (skip for now if you're starting on the NSE feed):

```
python -m pip install kiteconnect
```

## A4. Set the API key permanently

```
setx ANTHROPIC_API_KEY "sk-ant-your-key-here"
```

**Close the Command Prompt and open a new one** — `setx` only affects windows
opened after it runs. Verify:

```
echo %ANTHROPIC_API_KEY%
```

## A5. Prove the maths before you trust it

```
cd C:\optionsdesk
python selftest.py
```

This is offline — no network, no API key needed. It checks put-call parity, the
IV solver, the Zerodha charge arithmetic, the liquidity gate against your own
screenshotted books, position sizing, and a full paper entry-to-exit cycle.

**You want `ALL PASS` on the last line.** If anything fails, stop and send me
the output — don't run it live on a broken build.

## A6. Pull real lot sizes

```
python -m desk.lots refresh
```

Expect `source=nse_csv` or `source=kite`. If it says `source=fallback`, the
exchange CSV didn't download and the desk is using a hardcoded table that
**may be out of date** — SEBI revises F&O market lots periodically and a wrong
lot size corrupts every P&L number downstream. Verify NIFTY / BANKNIFTY /
RELIANCE against Kite before trading in that case.

## A7. First live cycle

Run this **during market hours (09:15–15:30 IST, Mon–Fri)** or it'll just tell
you the market is closed.

```
python -m desk.run
```

What good looks like:

```
[DATA]     Lot sizes from nse_csv — 190 symbols cached
[STRATEGY] Seeded strategy v1 — Seed_LiquidMomentum_RVoverIV
[SCREEN]   Tradable now: ['NIFTY', 'BANKNIFTY']
           NIFTY score=8.1 friction=0.79% liquid=14 |
           RELIANCE REJECTED: realised/implied 0.61 under 0.85 |
           MIDCPNIFTY REJECTED: no liquid near-ATM contract
[SCAN]     No entry rule fired
           NIFTY: edge=1.9 rv/iv=0.94 trend=0.11 friction=0.79%
```

That's the desk working correctly. **Most cycles do nothing** — that's the
point. Doing nothing is a valid output.

**If you see `no usable chain`:** NSE is refusing you. Try again in a minute; if
it persists, that IP is blocked and you'll need Kite.

## A8. Leave it running

```
cd C:\optionsdesk
python -m desk.run --loop
```

It cycles every 60 seconds, sleeps politely outside market hours, and manages
open positions on every pass. Leave the window open.

### Make it survive a reboot

Create `C:\optionsdesk\run_desk.bat`:

```bat
@echo off
cd /d C:\optionsdesk
:loop
python -m desk.run --loop
echo Desk exited, restarting in 60s...
timeout /t 60
goto loop
```

Then **Task Scheduler** → Create Task:

- **General:** name `Options Desk`, tick *Run whether user is logged on or not*,
  tick *Run with highest privileges*
- **Triggers:** New → *At startup*, and a second one *Daily at 09:00* (in case
  it died overnight)
- **Actions:** New → Start a program → `C:\optionsdesk\run_desk.bat`
- **Settings:** untick *Stop the task if it runs longer than…*

## A9. Watch it

Open `C:\optionsdesk\docs\index.html` in a browser. It reads `data.json`, which
is rewritten every cycle. Refresh to update.

The page shows, in order: whether the market is open, the equity figures, the
**decision trail** (collect → research → bull/bear → risk gate → fill) with the
actual text of each stage, the **screen** (what it will and won't trade right
now and why), the equity curve, open and closed trades, the current strategy
JSON, and what it learned in each review.

Also readable directly:
- `state\JOURNAL.md` — the whole record in markdown
- `state\trades.csv` — for pandas
- `state\desk.db` — SQLite, everything

## A10. Adding Kite later

Each morning after 07:30 IST:

```
cd C:\optionsdesk
set KITE_API_KEY=your_key
set KITE_API_SECRET=your_secret
python -m desk.providers.kite login
```

It prints a URL. Open it, log in with your Zerodha credentials + TOTP, and the
browser will redirect to a `127.0.0.1` address that fails to load — **that's
expected**. Copy the `request_token=...` value out of the address bar and paste
it into the prompt. Token saves to `state\kite_token.txt`.

Then set `data.provider: "kite"` in `config.yaml`.

To make the key/secret permanent, use `setx` as in step A4.

---

# Part B — GitHub Actions

## B1. Create the repo

1. **github.com/new** → name it `optionsdesk`
2. Public or private both work. Private if you'd rather nobody sees the journal.
3. Don't add a README — the zip has one.

## B2. Upload

Unzip locally, then on the repo page: **Add file → Upload files**, drag in the
**contents** of the `optionsdesk` folder (not the folder itself). Commit.

Check `config.yaml` is at the repo root, not inside a subfolder.

## B3. Add the API key as a secret

**Settings → Secrets and variables → Actions → New repository secret**

- Name: `ANTHROPIC_API_KEY`
- Value: your `sk-ant-` key

For Kite, add `KITE_API_KEY` and `KITE_ACCESS_TOKEN` the same way — but you'd be
updating `KITE_ACCESS_TOKEN` by hand every morning, which is why path A is better.

## B4. Allow the workflow to write

**Settings → Actions → General → Workflow permissions** → select
**Read and write permissions** → Save.

Without this the desk can't commit its state back and it loses its memory every
run.

## B5. First run

**Actions** tab → *options-desk* → **Run workflow**.

Green tick = working. Click into it and read the log — you should see the same
`[SCREEN]` / `[SCAN]` lines as A7.

It then runs on cron every 5 minutes through IST market hours, plus a review
pass after the close.

## B6. Publish the dashboard

**Settings → Pages** → Source: *Deploy from a branch* → branch `main`, folder
`/docs` → Save.

Live in a minute or two at
`https://<your-username>.github.io/optionsdesk/`

## B7. The thing that will bite you

nseindia.com blocks datacentre IPs. From a GitHub runner you'll intermittently
see `no usable chain` in the log. Nothing is broken — the exchange just won't
serve that IP. If it's more than occasional, move to path A or switch to Kite.

---

# Part C — What to do in week one

**Day 1.** Confirm it's cycling and the screen is producing sensible verdicts.
Don't expect trades. The seed strategy is deliberately tight and the screen
holds back anything illiquid or quiet.

**Days 2–5.** Watch the `[SCREEN]` lines. If everything is always rejected for
the same reason, the gate may be too tight for current conditions — tell me
which reason and I'll recalibrate. If it's trading 4 times a day, it's too loose.

**Around day 5–10.** First self-review fires (10 closed trades, or 30 idle
hours). Read it on the dashboard under *What it learned*. This is the part worth
your attention — the diagnosis tells you whether it understands its own record.

**Week 3+.** Replay backtests start to mean something, because by then the desk
has archived enough real chain snapshots to test against. Before that it's
falling back on synthetic repricing, which is labelled low-confidence for good
reason.

### Knobs you might actually want to turn

All in `config.yaml`. The bot cannot change these.

| Setting | Now | Turn it if |
|---|---|---|
| `liquidity.index.min_premium` | 60 | It's rejecting everything on premium |
| `liquidity.index.max_spread_pct` | 0.70 | Too strict in volatile sessions |
| `volatility.min_rv_iv_ratio` | 0.85 | It never trades — this is the usual culprit |
| `universe.max_underlyings_live` | 4 | You want it watching more or fewer |
| `risk_ceiling.max_risk_per_trade_pct` | 1.5 | You want smaller or larger clips |
| `brain.review_every_n_trades` | 10 | You want faster or slower learning |

### Commands

```
python -m desk.run                one cycle
python -m desk.run --loop         continuous
python -m desk.run --review       force a strategy review now
python -m desk.run --backtest     backtest the active spec, trade nothing
python -m desk.run --reset        wipe all state and start over
python -m desk.lots refresh       re-pull lot sizes
python selftest.py                offline maths check
```

---

# Part D — When something goes wrong

| Symptom | Cause | Fix |
|---|---|---|
| `python not recognized` | PATH not set | Re-run installer, tick *Add to PATH* |
| `No module named yaml` | deps missing | `python -m pip install requests PyYAML` |
| `ANTHROPIC_API_KEY not set` | `setx` needs a fresh shell | Close and reopen Command Prompt |
| `no usable chain` | NSE blocking the IP | Retry; if persistent, use Kite or a different host |
| `kite unavailable` | package or token missing | `pip install kiteconnect`, then the login flow |
| `Lot sizes from fallback` | exchange CSV unreachable | Verify NIFTY/BANKNIFTY lots by hand before trading |
| Signal fires but no trade | risk gate vetoed it | Read the `[RISK]` line — it says exactly what and by how much |
| Nothing ever trades | screen or rules too tight | Check `[SCREEN]` rejection reasons; the idle review fires after 30h and loosens |
| `No entry rule fired` every cycle | normal | This is the desk being selective, not broken |

---

# Part E — Two things to keep in mind

**It is paper only.** There is no `place_order` call anywhere in the code. The
Kite provider is read-only by construction. Wiring it to real money would be a
deliberate change, and the honest prerequisite is a few hundred forward paper
trades showing positive expectancy *after* charges — not one good week.

**Judge a strategy version by its forward record, not the backtest that
promoted it.** An unsupervised search over strategy space against a small sample
will find things that look profitable and aren't. The champion/challenger gate,
the minimum trade counts and the archived-snapshot replay all slow that down.
They reduce the problem. They don't remove it.
