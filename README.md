# Autonomous Crypto Trading Bot — Coinbase (Primary) + Alpaca (Secondary)

A rule-bound, autonomous Python trading bot running two live accounts under launchd.

| Bot | Exchange | Status | Focus |
|---|---|---|---|
| **Coinbase bot** | Coinbase Advanced | ✅ PRIMARY — active | $1 controlled exploration, BTC/ETH/SOL |
| **Alpaca bot** | Alpaca | ⏸ SECONDARY — on hold | Equity/crypto scanning, no active trades |

> **Capital at risk.** This bot is an experiment. The entire funded amount may be lost.
> The system is engineered for discipline, not profit guarantees.

---

## Architecture

```
main.py  (orchestration loop, 60s cycle)
  │
  ├─► permissions.py       Queries Alpaca at startup; fail-closed on any ambiguity
  ├─► market_data.py       Alpaca data API; staleness-gated quotes and bars
  ├─► strategy_router.py   Scans symbols; produces TradeProposal objects only
  │     ├─ strategy_crypto.py     momentum_breakout, mean_reversion, ema_crossover
  │     ├─ strategy_equities.py   momentum_breakout, vwap_reversion (paper only)
  │     ├─ strategy_options.py    long_call/put (gated: broker approval required)
  │     └─ strategy_shorts.py     momentum_short (gated: $2,000+ equity required)
  ├─► risk_manager.py      AUTHORITATIVE: 25+ deterministic checks per proposal
  ├─► order_manager.py     Dedup-protected Alpaca API order router; dry_run = no-op
  ├─► position_manager.py  Stop-loss / take-profit / time-exit / force-flat
  ├─► journal.py           Append-only CSV; logs every decision including skips
  ├─► report.py            Daily report to /reports/
  └─► browser_monitor.py  Optional Playwright read-only dashboard observer
```

**Key design rule:** The strategy layer cannot place orders. It only produces proposals.
Every proposal passes through `risk_manager.check()`. Only approved proposals reach
`order_manager.execute()`, which calls the Alpaca API.

---

## Quickstart

### 1. Clone and set up environment

```bash
git clone <your-repo>
cd alpaca-autonomous-microbot

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

### 2. Configure credentials

```bash
cp .env.example .env
```

Edit `.env`:

```bash
# Paper trading (start here)
ALPACA_API_KEY=your_paper_api_key
ALPACA_SECRET_KEY=your_paper_secret_key
ALPACA_PAPER=true
LIVE_TRADING=false
```

> Get paper keys at: https://app.alpaca.markets/paper/dashboard/overview
> Get live keys at:  https://app.alpaca.markets/brokerage/dashboard/overview

### 3. Install browser automation (optional)

```bash
playwright install chromium
```

---

## Running the Bot

### Dry Run — no orders, no real data required (validates config only)

```bash
python main.py --mode dry_run
```

### Paper Trading — real market data, simulated orders

```bash
python main.py --mode paper
```

### Paper Trading — single scan cycle (for testing)

```bash
python main.py --mode paper --once
```

### Paper Trading — with read-only browser monitor

```bash
python main.py --mode paper --browser-monitor
```

### Live Crypto Only — real orders, real money

> Only proceed after dry_run and paper validation passes.

**Step 1 — Edit `.env`:**
```bash
ALPACA_API_KEY=your_LIVE_api_key
ALPACA_SECRET_KEY=your_LIVE_secret_key
ALPACA_PAPER=false
LIVE_TRADING=true
```

**Step 2 — Edit `config.yaml`:**
```yaml
mode: live
live_trading:
  enabled: true
  allow_crypto: true
```

**Step 3 — Run:**
```bash
python main.py --mode live --asset-class crypto
```

---

## Running Tests

```bash
pytest tests/ -v
```

Run a specific test file:

```bash
pytest tests/test_risk_manager.py -v
pytest tests/test_permissions.py -v
pytest tests/test_config.py -v
```

---

## Risk Limits (Current Config)

| Limit | Value |
|---|---|
| Max live crypto trade | $3.00 |
| Max total exposure | $6.00 |
| Max daily loss | $2.00 |
| Max trades per day | 5 |
| Max open positions | 2 |
| Consecutive loss stop | 2 losses |
| Equity floor (live disable) | $7.00 |
| Stale data threshold | 15 seconds |
| Max spread (crypto) | 0.5% |
| Stop-loss | 1.5% |
| Take-profit | 2.5% |
| Max hold time | 90 minutes |

---

## Live Asset Classes

| Asset Class | Live Enabled | Condition |
|---|---|---|
| Crypto spot | ✅ Default | Alpaca account must support it |
| Equities (long) | ❌ Paper only | Manually enable in config |
| Long options | ❌ Disabled | Requires Alpaca options approval |
| Short selling | ❌ Disabled | Requires $2,000+ equity |
| Margin | ❌ Disabled | Requires $2,000+ equity |

---

## Kill Switches

The bot stops trading and logs a reason when any of these trigger:

1. **`LIVE_TRADING=false`** in `.env` — master kill switch, blocks all live orders
2. **`live_trading.enabled: false`** in `config.yaml` — config-level block
3. **Equity floor** — stops live trading below $7.00
4. **Daily loss limit** — stops all new trades after $2.00 realized loss
5. **Consecutive losses** — stops after 2 losing trades in a row
6. **Max trades/day** — stops after 5 trades
7. **API error rate** — halts if API errors exceed 10 per session
8. **Account blocked** — broker has blocked trading (detected via API)
9. **Browser security prompt** — Playwright detected a login/agreement page

---

## Unattended Safety Checklist

Before running live unattended, verify:

- [ ] Dry-run completed with no config errors
- [ ] Paper trading ran for at least one session without errors
- [ ] `tests/` pass: `pytest tests/ -v`
- [ ] `.env` has `LIVE_TRADING=true` set intentionally
- [ ] `config.yaml` has `mode: live` and `live_trading.enabled: true`
- [ ] `config.yaml` has `live_trading.allow_crypto: true` (and nothing else live)
- [ ] `.env` is in `.gitignore` and NOT committed to git
- [ ] API keys are live keys (not paper) in `.env`
- [ ] `ALPACA_PAPER=false` in `.env` for live mode
- [ ] Journal file `journal.csv` is writable
- [ ] `logs/` directory exists and is writable
- [ ] `reports/` directory exists and is writable
- [ ] Max daily loss (`$2.00`) is acceptable given your balance
- [ ] You have reviewed the journal after paper trading
- [ ] You have checked Alpaca dashboard manually before starting live

---

## File Structure

```
alpaca-autonomous-microbot/
├── main.py                 Entry point and orchestration loop
├── broker_alpaca.py        Alpaca API wrapper
├── permissions.py          Account permissions gate (fail-closed)
├── market_data.py          Market data + technical indicators
├── strategy_router.py      Routes symbols to strategy modules
├── strategy_crypto.py      Crypto strategies (momentum_breakout, mean_reversion, ema_crossover)
├── strategy_equities.py    Equity strategies (paper/dry-run only)
├── strategy_options.py     Options (gated behind broker approval)
├── strategy_shorts.py      Short selling (gated behind $2k equity)
├── risk_manager.py         Authoritative risk layer (25+ checks)
├── order_manager.py        Dedup-protected order routing
├── position_manager.py     Stop-loss / TP / time exits / force-flat
├── journal.py              Append-only CSV decision logger
├── report.py               Daily report generator
├── browser_monitor.py      Read-only Playwright dashboard monitor
├── utils.py                Config, env, logging, time helpers
├── config.yaml             Configuration
├── requirements.txt        Python dependencies
├── .env.example            Environment variable template
├── .gitignore              Secrets excluded from git
├── tests/
│   ├── test_risk_manager.py   Risk layer tests
│   ├── test_permissions.py    Permissions gate tests
│   └── test_config.py         Config and env tests
├── logs/                   Log files (gitignored)
└── reports/                Daily reports (gitignored)
```

---

## Strategy Overview

### Crypto — Momentum Breakout
- Entry: price closes above N-bar high with above-average volume (>1.2× avg)
- Trend confirmation: EMA9 > EMA21
- Overbought guard: RSI < 80
- Stop: 1.5% below entry
- Target: 2.5% above entry
- Time exit: 90 minutes max

### Crypto — Mean Reversion
- Entry: price near/below lower Bollinger Band (bb_pct_b < 0.15) + RSI < 35
- Not in strong downtrend guard: EMA9 not more than 2% below EMA21
- Stop: 1.5% below entry
- Target: BB mid-band reversion

### Equity — Momentum Breakout (paper only)
- Same breakout logic as crypto, applied to SPY/QQQ/AAPL/MSFT/NVDA
- Force-flat before 2:55 PM local time

### Equity — VWAP Reversion (paper only)
- Entry: price below VWAP with RSI recovering (30–45)
- Target: VWAP + small buffer

---

## Logs and Reports

- Trade journal: `journal.csv` — every decision, trade, and skip with full context
- Daily logs: `logs/bot_YYYYMMDD.log`
- Daily reports: `reports/report_YYYYMMDD.txt`
- Browser screenshots (if enabled): `logs/screenshots/`

---

## Security Notes

- API keys are only read from `.env` via `python-dotenv`
- Keys are never printed, logged, or committed
- `get_alpaca_keys()` raises if keys are placeholder or empty
- Browser monitor never scrapes credentials, cookies, or session tokens
- Browser monitor never clicks trade/submit/confirm buttons
- If a security prompt is detected in the browser, trading halts

---

## Modifying Risk Limits

Edit `config.yaml`. Changes take effect on next bot start.
Do NOT increase position sizes automatically — the bot is configured
to hold limits constant even as the account grows (until you manually update).
