#!/usr/bin/env bash
#
# sync_p2_044_for_gpt.sh — run THIS ON THE MAC (not in the sandbox) to commit
# Claude's P2-044 pivot work onto a review branch so GPT can reference it.
#
# It is safe and idempotent: review branch only, no merge to main, no push unless
# you uncomment the push line, no live/runtime/broker action.
#
# Usage:
#   cd /path/to/alpaca-autonomous-microbot
#   bash sync_p2_044_for_gpt.sh
#
set -euo pipefail

BRANCH="review/p2-044a-pivot-feasibility-matrix"

FILES=(
  "pivot_feasibility_matrix.py"
  "tests/test_p2_044a_pivot_feasibility_matrix.py"
  "equities_swing_backtest_gate.py"
  "tests/test_p2_044b_equities_swing_backtest_gate.py"
  "swing_param_robustness.py"
  "tests/test_p2_044c_swing_param_robustness.py"
  "run_pivot_gate.py"
  "tests/test_p2_044d_run_pivot_gate.py"
  "fetch_etf_ohlcv.py"
  "tests/test_p2_044e_fetch_etf_ohlcv.py"
  "fetch_alpaca_bars.py"
  "tests/test_p2_044f_fetch_alpaca_bars.py"
  "venue_compare.py"
  "tests/test_p2_044g_venue_compare.py"
  "analyze_live_journal.py"
  "tests/test_p2_044h_analyze_live_journal.py"
  "news_edge_research.py"
  "tests/test_p2_045a_news_edge_research.py"
  "fetch_alpaca_news.py"
  "tests/test_p2_045b_fetch_alpaca_news.py"
  "fetch_crypto_news.py"
  "tests/test_p2_045c_fetch_crypto_news.py"
  "P2-044A_HANDOFF_FOR_GPT_2026-06-16.md"
  "CLAUDE_CODE_PROMPT.md"
  "sync_p2_044_for_gpt.sh"
)

echo "==> Repo: $(pwd)"
echo "==> HEAD before: $(git rev-parse --short HEAD) on $(git rev-parse --abbrev-ref HEAD)"

# Clear any stale sandbox lock (harmless if absent).
[ -f .git/index.lock ] && rm -f .git/index.lock && echo "==> removed stale .git/index.lock" || true

# Governance: ensure the kill-switch sentinel exists. Trading stays NO-GO.
if [ ! -f runtime/STOP_TRADING ]; then
  mkdir -p runtime && touch runtime/STOP_TRADING
  echo "==> restored runtime/STOP_TRADING (kill-switch sentinel)"
fi

# Create or switch to the review branch.
if git show-ref --verify --quiet "refs/heads/${BRANCH}"; then
  git checkout "${BRANCH}"
else
  git checkout -b "${BRANCH}"
fi

git add "${FILES[@]}"

# Run the offline tests before committing (no network, no broker).
echo "==> Running P2-044 tests..."
python3 -m pytest \
  tests/test_p2_044a_pivot_feasibility_matrix.py \
  tests/test_p2_044b_equities_swing_backtest_gate.py \
  tests/test_p2_044c_swing_param_robustness.py \
  tests/test_p2_044d_run_pivot_gate.py \
  tests/test_p2_044e_fetch_etf_ohlcv.py \
  tests/test_p2_044f_fetch_alpaca_bars.py \
  tests/test_p2_044g_venue_compare.py \
  tests/test_p2_044h_analyze_live_journal.py \
  tests/test_p2_045a_news_edge_research.py \
  tests/test_p2_045b_fetch_alpaca_news.py \
  tests/test_p2_045c_fetch_crypto_news.py -q

git commit -m "P2-044A-E: offline pivot screen, swing backtest gate, robustness sweep, orchestrator, data fetcher

- pivot_feasibility_matrix.py (A): cost-vs-move lane screen; recommends commission-free
  Alpaca equities/ETF swing. Feasibility screen, not a profit claim.
- equities_swing_backtest_gate.py (B): offline real-cost walk-forward gate (Donchian
  breakout swing, long-only, PDT-safe, fees+spread+slippage). Data-agnostic; needs REAL
  OHLCV via --csv to be decision-grade. Synthetic = smoke test only.
- swing_param_robustness.py (C): anti-overfitting OOS sweep; ROBUST/FRAGILE/FALSIFIED.
- run_pivot_gate.py (D): one-command orchestrator -> GO_TO_PAPER or NO_GO (never live).
- fetch_etf_ohlcv.py (E): Mac-side daily OHLCV fetcher/normalizer (yfinance) -> CSV the
  gates consume. Pure normalizer is unit-tested offline.
- fetch_alpaca_bars.py (F): Alpaca-native daily-bars fetcher (Alpaca API only, reuses keys);
  read-only market data, never prints keys. Preferred over E for single-vendor compliance.
- venue_compare.py (G): runs the same swing strategy through the gate under coinbase_taker/
  coinbase_maker/alpaca_crypto/alpaca_equities cost models, side by side.
- FEE-ACCOUNTING FIX in equities_swing_backtest_gate.py: commission is now subtracted from each
  trade's net P&L (was only in the gate threshold). Materially changes non-zero-commission venues.
- analyze_live_journal.py (H): DECISIVE real-data diagnosis. On the actual 54 live trades, GROSS P&L
  before any fees is -\$0.17; even a zero-fee venue still loses. Diagnosis=NO_EDGE: entries have no
  directional edge (mean gross -0.12%/trade, gross win 42.6%, t=-1.52). No venue/patch fixes this.
- news_edge_research.py (P2-045A): tests the UNTESTED hypothesis - does news/sentiment predict forward
  returns net of fees? Offline, OOS split, needs real prices+news to be decision-grade.
- fetch_alpaca_news.py (P2-045B): Mac-side Alpaca historical-news fetcher (same keys; never prints them).
- fetch_alpaca_bars.py now AUTO-ROUTES crypto (BTC/USD -> CryptoHistoricalDataClient, no keys) vs equity;
  required fix for this crypto bot. fetch_daily() is the entry point.
- fetch_crypto_news.py (P2-045C): crypto-focused news via CryptoCompare (free, NO key, pages back via
  lTs). Better crypto coverage than Alpaca's equity-leaning news.
- 89 tests passing. No live, no broker, no runtime mutation. Review branch only." \
  || echo "==> nothing to commit (already committed?)"

echo "==> HEAD after: $(git rev-parse --short HEAD) on $(git rev-parse --abbrev-ref HEAD)"
echo "==> Done. Review branch '${BRANCH}' is ready for GPT."
echo "==> To publish for GPT, optionally push:"
echo "      git push -u origin ${BRANCH}"
# Uncomment to auto-push:
# git push -u origin "${BRANCH}"
