# Going to Alpaca PAPER — operator setup (2026-06-16)

You chose **paper first** (fake money, real execution) before risking the real $10. This is the
M4 step. Do these on the Mac, in the repo. ~5 minutes.

## What paper is (and isn't)

- Alpaca **paper** = a free simulated account with its own fake balance (~$100k by default) and its
  own **separate API keys**. Real orders, real fills, *fake* money. Your live $10 is never touched.
- Paper uses a paper-only endpoint + paper-only keys, so it is **independent of `runtime/STOP_TRADING`**
  (that switch guards real money / the retired Coinbase bot — leave it in place, do not remove it).

## Steps

1. **Generate paper keys.** Log in at <https://app.alpaca.markets>, switch the toggle to **Paper
   Trading**, open **API Keys**, and generate a key/secret. (Paper keys often start with `PK`.)

2. **Add them to `.env`** (these are *new* vars — your live `ALPACA_API_KEY` stays untouched and
   unused for paper):
   ```
   ALPACA_PAPER_API_KEY=PK...your_paper_key...
   ALPACA_PAPER_SECRET_KEY=...your_paper_secret...
   ```

3. **Turn on paper mode** and launch:
   ```bash
   cd ~/Documents/Claude/Projects/Investing/alpaca-autonomous-microbot
   ./run_app.sh --enable-paper        # writes app_config.json: live_paper=true
   ./run_app.sh                       # the app window
   ```
   The header badge should read **“PAPER · Alpaca connected.”** If it says **“add paper keys,”** the
   keys aren’t being read yet — recheck step 2 (no quotes/spaces) and relaunch.

4. **Use it weekly.** Open the app, review the Conservative plan ($10 → SPY/GLD/SLV/QQQ/BTC by weight),
   click **Approve (paper)**. Orders go to your Alpaca paper account; the Performance panel tracks the
   value of your basket positions vs cumulative contributions. Equities fill during market hours; BTC
   fills 24/7.

5. **Cross-check.** After approving, open the Alpaca paper dashboard and confirm the positions match
   the app. That’s the whole point of paper — proving the app executes correctly before real money.

## When is "B proven" (ready for real $10 / path A)?

- The app reliably proposes + paper-executes the plan each week.
- The Performance panel matches your Alpaca paper account over **several weeks**.
- No execution bugs (wrong sizes, missed/duplicate orders, symbol/venue errors).

Only then consider real money — and that's a **separate, explicit** step (a `live` mode that is
currently hard-blocked in code) plus the securities-lawyer conversation before any commercial use.

## To revert to safe simulation anytime

```bash
./run_app.sh --disable-paper
```

Governance: real-money LIVE remains NO-GO (blocked in code). `runtime/STOP_TRADING` stays present.
Keys live in `.env`, are never printed, never committed.
