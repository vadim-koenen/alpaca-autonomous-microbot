"""
main.py — Alpaca Autonomous Micro-Trading Bot

Entry point and main orchestration loop.

Usage:
  python main.py --mode dry_run
  python main.py --mode paper
  python main.py --mode live --asset-class crypto

Flow per cycle:
  1. Load config + env
  2. Connect to Alpaca, fetch permissions
  3. Build account state snapshot
  4. Check kill switches (halt, daily loss, equity floor)
  5. Run strategy router → get proposals
  6. For each proposal: risk_manager.check() → if approved: order_manager.execute()
  7. position_manager.monitor() → apply stops / TPs / time exits
  8. Optional: browser_monitor.capture_snapshot() every N cycles
  9. Sleep → repeat
 10. On shutdown: generate daily report
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time
import logging
from datetime import date, datetime
from typing import Any

from browser_monitor import BrowserMonitor
from journal import get_journal
from market_data import MarketData
from memory.event_store import get_event_store
from order_manager import OrderManager, SessionState
from permissions import AccountPermissions, fetch_permissions
from position_manager import PositionManager
from report import ReportGenerator
from risk_manager import RiskManager, AccountState
from strategy_router import StrategyRouter
from utils import (
    RUNTIME_DIR,
    acquire_process_lock,
    assert_not_live_without_env,
    build_broker,
    calculate_crypto_entry_blockers,
    calculate_crypto_exposure,
    compute_config_hash,
    get_broker_name,
    get_config_path,
    get_cfg,
    get_mode,
    is_paper,
    kill_switch_active,
    load_config,
    load_env,
    release_process_lock,
    safe_float,
    setup_logging,
)

# ---------------------------------------------------------------------------
# Globals for graceful shutdown
# ---------------------------------------------------------------------------
_running = True
_broker = None
_session: SessionState | None = None
_position_mgr: PositionManager | None = None


_shutdown_count = 0


def _handle_signal(signum, frame):
    global _running, _shutdown_count
    _shutdown_count += 1
    logger = logging.getLogger("main")
    if _shutdown_count == 1:
        logger.warning(f"Signal {signum} received — initiating graceful shutdown (press Ctrl+C again to force-quit)")
        _running = False
    else:
        # Second press: force-quit immediately, bypassing cleanup
        logger.warning("Second signal received — force-quitting now")
        import os
        os._exit(1)


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


# ---------------------------------------------------------------------------
# Diagnose helper — one-shot indicator snapshot, no orders
# ---------------------------------------------------------------------------

def _run_diagnose(market_data, logger) -> None:
    """
    Fetch live quotes + indicators for all configured crypto symbols
    and print a human-readable table to stdout. No orders, no journal writes.
    """
    from market_data import add_indicators
    from utils import get_cfg

    crypto_symbols = get_cfg("crypto", "symbols", default=["BTC/USD", "ETH/USD"])
    lookback = get_cfg("strategy", "lookback_bars", default=20)

    sep = "─" * 70
    print(f"\n{'=' * 70}")
    print("DIAGNOSE — Live Indicator Snapshot")
    print(f"Lookback bars: {lookback}  |  Min confidence: {get_cfg('strategy','min_confidence_score',default=0.65)}")
    print(f"{'=' * 70}\n")

    for symbol in crypto_symbols:
        print(f"{sep}")
        print(f"  {symbol}")
        print(f"{sep}")

        try:
            quote = market_data.get_crypto_quote(symbol)

            # Always show raw quote, even if invalid — helps diagnose the problem
            if quote.bid == 0 and quote.ask == 0:
                print(f"  ⚠  No quote returned from API (bid=0, ask=0) — check API keys or Alpaca status")
                print()
                continue

            age_s = ""
            if quote.timestamp:
                from utils import now_utc as _now
                age_s = f"  age={((_now()-quote.timestamp).total_seconds()):.1f}s"
            print(f"  Quote  : bid={quote.bid:.4f}  ask={quote.ask:.4f}  mid={quote.mid:.4f}{age_s}")
            if not quote.valid:
                print(f"  ⚠  Quote is STALE (age > {get_cfg('crypto','stale_data_seconds',default=60)}s) — data feed may be delayed")
                print()
                continue
            spread = (quote.ask - quote.bid) / quote.mid * 100 if quote.mid > 0 else 0
            print(f"  Spread : {spread:.4f}%  (max allowed: {get_cfg('crypto','max_spread_pct',default=0.5)}%)")

            df = market_data.get_crypto_bars_df(symbol, limit=max(lookback + 10, 40))
            if df.empty or len(df) < 10:
                print(f"  ⚠  Not enough bars ({len(df)} returned, need 10+)")
                print(f"     This usually means the Alpaca bars API returned no data.")
                print(f"     Check: https://status.alpaca.markets/")
                print()
                continue

            df = add_indicators(df)
            row = df.iloc[-1]
            prev = df.iloc[-(lookback + 1):-1]

            close = float(row["c"])
            rsi = float(row.get("rsi_14", 0))
            ema9 = float(row.get("ema_9", close))
            ema21 = float(row.get("ema_21", close))
            rel_vol = float(row.get("rel_volume", 0))
            bb_pct_b = float(row.get("bb_pct_b", 0.5))
            bb_lower = float(row.get("bb_lower", 0))
            bb_mid = float(row.get("bb_mid", close))
            mom_5 = float(row.get("mom_5", 0))
            recent_high = float(prev["h"].max()) if not prev.empty else 0
            recent_low = float(prev["l"].min()) if not prev.empty else 0

            print(f"  Bars   : {len(df)} returned  |  lookback high={recent_high:.4f}  low={recent_low:.4f}")
            print(f"  Close  : {close:.4f}")
            print(f"  RSI-14 : {rsi:.2f}   (momentum need <80; mean_rev need <35)")
            print(f"  RelVol : {rel_vol:.3f}  (momentum need >1.2)")
            print(f"  EMA9   : {ema9:.4f}  {'> EMA21 ✓' if ema9 > ema21 else '< EMA21 ✗'} ({ema21:.4f})")
            print(f"  BB%b   : {bb_pct_b:.3f}  (mean_rev need <0.15)  lower={bb_lower:.4f}  mid={bb_mid:.4f}")
            print(f"  Mom5   : {mom_5:.4f}")
            print()

            # Momentum breakout diagnosis
            breakout = close > recent_high
            vol_ok = rel_vol > 1.2
            trend_ok = ema9 > ema21
            not_overbought = rsi < 80

            print("  ── Momentum Breakout ──")
            print(f"     [{'✓' if breakout else '✗'}] breakout: close {close:.2f} {'>' if breakout else '<='} high {recent_high:.2f}")
            print(f"     [{'✓' if vol_ok else '✗'}] volume:   rel_vol {rel_vol:.2f} {'>' if vol_ok else '<='} 1.2")
            print(f"     [{'✓' if trend_ok else '✗'}] trend:    EMA9 {'>' if trend_ok else '<'} EMA21")
            print(f"     [{'✓' if not_overbought else '✗'}] RSI:      {rsi:.1f} {'< 80 ✓' if not_overbought else '>= 80 ✗'}")
            if all([breakout, vol_ok, trend_ok, not_overbought]):
                print("     → All hard conditions MET — would generate signal if confidence ≥ 0.65")
            else:
                missing = [c for c, v in [("breakout", breakout), ("volume", vol_ok), ("trend", trend_ok), ("not_overbought", not_overbought)] if not v]
                print(f"     → Missing: {', '.join(missing)}")
            print()

            # Mean reversion diagnosis
            oversold = rsi < 35
            at_lower = bb_pct_b < 0.15
            not_downtrend = ema9 >= ema21 * 0.98

            print("  ── Mean Reversion ──")
            print(f"     [{'✓' if oversold else '✗'}] RSI oversold: {rsi:.1f} {'< 35 ✓' if oversold else '>= 35 ✗'}")
            print(f"     [{'✓' if at_lower else '✗'}] lower band:   bb_pct_b {bb_pct_b:.3f} {'< 0.15 ✓' if at_lower else '>= 0.15 ✗'}")
            print(f"     [{'✓' if not_downtrend else '✗'}] not downtrend: EMA9/EMA21 ratio {ema9/ema21:.4f} {'≥ 0.98 ✓' if not_downtrend else '< 0.98 ✗'}")
            if all([oversold, at_lower, not_downtrend]):
                print("     → All hard conditions MET — would generate signal if confidence ≥ 0.65")
            else:
                missing = [c for c, v in [("rsi_oversold", oversold), ("at_lower_band", at_lower), ("no_downtrend", not_downtrend)] if not v]
                print(f"     → Missing: {', '.join(missing)}")
            print()

        except Exception as e:
            print(f"  ⚠  Error fetching data for {symbol}: {e}")
            print()

    print(f"{'=' * 70}")
    print("Diagnose complete. No orders placed.")
    print(f"{'=' * 70}\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Alpaca Autonomous Micro-Trading Bot")
    p.add_argument(
        "--mode",
        choices=["dry_run", "paper", "live"],
        default=None,
        help="Override config mode. Default: read from config.yaml",
    )
    p.add_argument(
        "--asset-class",
        choices=["crypto", "equities", "all"],
        default="all",
        help="Restrict scanning to a specific asset class (default: all)",
    )
    p.add_argument(
        "--browser-monitor",
        action="store_true",
        default=False,
        help="Enable Playwright browser monitoring (read-only, optional)",
    )
    p.add_argument(
        "--once",
        action="store_true",
        default=False,
        help="Run a single scan cycle then exit (useful for testing)",
    )
    p.add_argument(
        "--diagnose",
        action="store_true",
        default=False,
        help=(
            "Print a live indicator snapshot for all symbols then exit. "
            "No orders or journal writes. Good for understanding why signals "
            "are or aren't firing."
        ),
    )
    p.add_argument(
        "--force-lock",
        action="store_true",
        default=False,
        help=(
            "Override stale process lock and start anyway. "
            "Only use if you are certain no other live bot is running."
        ),
    )
    return p.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    global _running, _broker, _session, _position_mgr
    store = get_event_store()

    # ── 1. Environment and config ─────────────────────────────────────────
    load_env()
    args = parse_args()

    # If --mode is specified on CLI, override config temporarily
    if args.mode:
        cfg = load_config()
        cfg["mode"] = args.mode

    logger = setup_logging("main")
    mode = get_mode()

    broker_name = get_broker_name()
    config_hash, safe_config = compute_config_hash(load_config())
    run_id = store.start_run(
        bot_name=f"{broker_name}_{args.asset_class}",
        broker=broker_name,
        mode=mode,
        asset_class=args.asset_class,
        config_hash=config_hash,
        payload={
            "config_file": str(get_config_path()),
            "argv_asset_class": args.asset_class,
        },
    )
    store.record_config_version(
        config_file=str(get_config_path()),
        config_hash=config_hash,
        mode=mode,
        broker=broker_name,
        asset_class=args.asset_class,
        payload={
            "risk_caps": {
                "crypto_exposure_cap": safe_config.get("crypto", {}).get(
                    "max_total_crypto_exposure_usd"
                ),
                "global_exposure_cap": safe_config.get("global_risk", {}).get(
                    "max_total_live_exposure_usd"
                ),
                "max_daily_loss": safe_config.get("global_risk", {}).get(
                    "max_daily_loss_usd"
                ),
            },
            "strategy": safe_config.get("strategy", {}),
        },
    )
    store.record_event(
        event_type="startup",
        severity="info",
        broker=broker_name,
        asset_class=args.asset_class,
        payload={
            "mode": mode,
            "config_file": str(get_config_path()),
            "config_hash": config_hash,
            "run_id": run_id,
        },
        source_component="main",
        source_file="main.py",
    )
    logger.info("=" * 60)
    logger.info(
        f"Autonomous Micro-Bot starting | mode={mode.upper()} | "
        f"broker={broker_name.upper()}"
    )
    logger.info("=" * 60)

    # ── 2. Safety gates ───────────────────────────────────────────────────
    try:
        assert_not_live_without_env()
    except RuntimeError as e:
        store.record_incident(
            severity="critical",
            component="main",
            summary="Live trading gate blocked startup",
            details={"error": str(e), "mode": mode},
            broker=broker_name,
            asset_class=args.asset_class,
            source_file="main.py",
        )
        logger.critical(str(e))
        sys.exit(1)

    # Process lock: prevent two live bot instances on the same account
    if not acquire_process_lock(force=args.force_lock):
        from utils import LOCK_FILE
        try:
            existing_pid = LOCK_FILE.read_text().strip()
        except Exception:
            existing_pid = "unknown"
        logger.critical(
            f"PROCESS LOCK: another live bot instance is already running "
            f"(PID {existing_pid}). Refusing to start a second live instance. "
            "Stop the first process or delete the broker-specific runtime/<broker>.lock if it is stale."
        )
        sys.exit(1)

    # Kill-switch file check at startup
    if kill_switch_active():
        logger.critical(
            "KILL SWITCH ACTIVE: runtime/STOP_TRADING file exists. "
            "Remove it to allow trading, then restart."
        )
        release_process_lock()
        sys.exit(1)

    if mode == "live":
        logger.warning(
            "LIVE MODE ACTIVE. Real orders will be placed. "
            "Capital at risk. Max trade: $2. Max exposure: $4. "
            "Daily loss limit: $2."
        )
        time.sleep(3)  # Give operator a moment to abort if this was accidental

    # ── 3. Connect to broker (Alpaca or Coinbase) ─────────────────────────
    try:
        _broker = build_broker()
    except Exception as e:
        store.record_incident(
            severity="critical",
            component="broker_init",
            summary=f"Failed to initialise {get_broker_name()} broker",
            details={"error": str(e)},
            broker=broker_name,
            asset_class=args.asset_class,
            source_file="main.py",
        )
        logger.critical(f"Failed to initialise {get_broker_name()} broker: {e}")
        sys.exit(1)

    # ── --diagnose fast path (skip account check, go straight to market data) ──
    if args.diagnose:
        market_data = MarketData(_broker)
        print(f"\nConnecting to Alpaca market data... (Ctrl+C twice to force-quit)\n")
        _run_diagnose(market_data, logger)
        return

    # ── 4. Fetch account permissions ──────────────────────────────────────
    permissions: AccountPermissions = fetch_permissions(_broker)
    logger.info(permissions.summary())

    if not permissions.is_healthy and mode != "dry_run":
        store.record_incident(
            severity="critical",
            component="permissions",
            summary="Account unhealthy; startup failed closed",
            details={
                "account_status": permissions.account_status,
                "account_blocked": permissions.account_blocked,
                "trading_blocked": permissions.trading_blocked,
                "paper": permissions.paper,
            },
            broker=broker_name,
            asset_class=args.asset_class,
            source_file="main.py",
        )
        logger.critical(
            f"Account is not healthy (status={permissions.account_status}, "
            f"blocked={permissions.account_blocked}/{permissions.trading_blocked}). "
            "Cannot trade. Exiting."
        )
        sys.exit(1)

    # ── 5. Instantiate components ─────────────────────────────────────────
    journal = get_journal()
    market_data = MarketData(_broker)
    strategy_router = StrategyRouter(_broker, market_data)
    risk_manager = RiskManager()
    _session = SessionState()
    order_manager = OrderManager(_broker, journal)
    _position_mgr = PositionManager(_broker, journal)
    reporter = ReportGenerator()

    # Restore persisted position state from previous session (if any)
    # This rebuilds stop/TP levels so managed exits survive a restart
    if mode != "dry_run":
        _position_mgr.restore_state(_session)
        if _session.open_positions:
            logger.info(
                f"State restored: {len(_session.open_positions)} position(s) "
                f"loaded from disk — {list(_session.open_positions.keys())}"
            )

    # Optional browser monitor
    browser_monitor = None
    if args.browser_monitor:
        try:
            browser_monitor = BrowserMonitor(paper=is_paper())
            logger.info("Browser monitor initialised (read-only)")
        except Exception as e:
            logger.warning(f"Browser monitor failed to init (non-fatal): {e}")
            browser_monitor = None

    # Track starting equity for the daily report
    starting_equity = permissions.equity
    scan_interval = 60  # seconds between scan cycles
    browser_check_every = 10  # run browser check every N cycles
    cycle_count = 0

    logger.info(
        f"Starting equity: ${starting_equity:.4f} | "
        f"Buying power: ${permissions.buying_power:.4f} | "
        f"Crypto enabled: {permissions.crypto_enabled}"
    )

    # ── Startup: effective risk config summary ────────────────────────────
    # Logs every active risk limit so stale env, launchd env issues, or
    # unintended defaults are immediately visible in the launch log.
    _log_effective_risk_config(logger, mode)

    # ── 6. Main loop ──────────────────────────────────────────────────────
    while _running:
        cycle_count += 1
        logger.debug(f"--- Cycle {cycle_count} ---")

        # Daily reset: clear per-day counters when UTC date rolls over.
        # This lets the bot run unattended through midnight without launchd
        # needing to restart it.  Soft halts (consecutive-loss limit) are
        # also cleared so a fresh trading day can proceed normally.
        if _session.maybe_daily_reset():
            logger.info(
                "DAILY RESET: consecutive_losses, daily_trade_count, "
                "daily_realized_pnl, api_error_count reset to 0 for new UTC day."
            )

        try:
            # Refresh permissions and account state every cycle
            permissions = fetch_permissions(_broker)

            # Build AccountState snapshot for risk manager
            open_positions_list = _broker.get_all_positions()
            open_orders_list = _broker.get_open_orders()

            # Total tracked crypto notional: bot-placed (filled) + broker-
            # recovered positions both count toward max_total_crypto_exposure.
            # Split into two buckets so the exposure guard can log precisely
            # which portion is external/untradeable vs API-controllable.
            (
                _tracked_crypto_exposure,
                _broker_recovered_crypto_exposure,
            ) = calculate_crypto_exposure(_session.open_positions)
            (
                _manual_review_crypto_count,
                _non_controllable_crypto_count,
            ) = calculate_crypto_entry_blockers(_session.open_positions)
            (
                _aggregate_exposure_known,
                _current_equity_exposure,
                _pending_equity_exposure,
                _recovered_equity_exposure,
                _aggregate_exposure_error,
            ) = calculate_alpaca_equity_exposure(
                open_positions_list,
                open_orders_list,
                _session.open_positions,
            )
            if not _aggregate_exposure_known:
                logger.warning(
                    "ENTRY_BLOCKED reason=aggregate_exposure_unknown "
                    f"detail={_aggregate_exposure_error}"
                )

            account_state = AccountState(
                equity=permissions.equity,
                buying_power=permissions.buying_power,
                open_positions=len(open_positions_list),
                open_position_symbols=[
                    getattr(p, "symbol", "") for p in open_positions_list
                ],
                open_orders=len(open_orders_list),
                open_order_symbols=[
                    getattr(o, "symbol", "") for o in open_orders_list
                ],
                daily_realized_pnl=_session.daily_realized_pnl,
                daily_trade_count=_session.daily_trade_count,
                consecutive_losses=_session.consecutive_losses,
                crypto_enabled=permissions.crypto_enabled,
                options_enabled=permissions.options_enabled,
                options_level=permissions.options_level,
                margin_enabled=permissions.margin_enabled,
                short_selling_enabled=permissions.short_selling_enabled,
                account_blocked=permissions.account_blocked,
                trading_blocked=permissions.trading_blocked,
                api_error_count=_session.api_error_count,
                tracked_crypto_exposure_usd=_tracked_crypto_exposure,
                broker_recovered_crypto_exposure_usd=_broker_recovered_crypto_exposure,
                manual_review_crypto_position_count=_manual_review_crypto_count,
                non_controllable_crypto_position_count=_non_controllable_crypto_count,
                aggregate_exposure_known=_aggregate_exposure_known,
                current_equity_position_exposure_usd=_current_equity_exposure,
                pending_equity_order_exposure_usd=_pending_equity_exposure,
                recovered_equity_position_exposure_usd=_recovered_equity_exposure,
            )

            # ── Kill switches ─────────────────────────────────────────────
            # Manual operator kill switch: touch runtime/STOP_TRADING
            if kill_switch_active():
                _session.halt("runtime/STOP_TRADING file detected — manual kill switch")
                logger.critical(
                    "KILL SWITCH FILE detected: runtime/STOP_TRADING. "
                    "Halting all new trades. Remove file and restart to resume."
                )

            if _session.halted:
                logger.warning(f"Session halted: {_session.halt_reason}. No new trades.")
                _maybe_sleep(scan_interval, args.once)
                if args.once:
                    break
                continue

            # Equity floor
            equity_floor = get_cfg("account", "disable_live_below_equity", default=7.0)
            if mode == "live" and permissions.equity < equity_floor:
                _session.halt(
                    f"Equity ${permissions.equity:.2f} below floor ${equity_floor:.2f}"
                )
                continue

            # Daily loss limit
            max_daily_loss = get_cfg("global_risk", "max_daily_loss_usd", default=2.0)
            if _session.daily_realized_pnl <= -abs(max_daily_loss):
                _session.halt(
                    f"Daily loss limit hit: ${_session.daily_realized_pnl:.2f}"
                )
                continue

            # ── Monitor existing positions ────────────────────────────────
            _position_mgr.monitor(_session)

            # If position monitor triggered a halt (e.g. consecutive losses)
            if _session.halted:
                logger.warning(f"Halted after position exit: {_session.halt_reason}")
                _maybe_sleep(scan_interval, args.once)
                if args.once:
                    break
                continue

            # ── Optional browser snapshot ─────────────────────────────────
            if browser_monitor and cycle_count % browser_check_every == 0:
                try:
                    snapshot = browser_monitor.capture_snapshot(
                        api_equity=permissions.equity,
                        api_buying_power=permissions.buying_power,
                        api_positions=len(open_positions_list),
                    )
                    should_pause = browser_monitor.check_and_pause_if_discrepancy(
                        snapshot, _session
                    )
                    if should_pause and snapshot.security_warning:
                        logger.critical(
                            "Browser detected security/agreement page. "
                            "Halting until manual review."
                        )
                        break
                except Exception as e:
                    logger.warning(f"Browser monitor cycle error (non-fatal): {e}")

            # ── Strategy scan ─────────────────────────────────────────────
            proposals = strategy_router.scan(permissions, buying_power=permissions.buying_power)

            if not proposals:
                logger.debug("No proposals this cycle. No trade is acceptable.")
            else:
                logger.info(f"{len(proposals)} proposal(s) to evaluate")

            # ── Risk check + order execution ──────────────────────────────
            for proposal in proposals:
                # Re-check account state (may have changed after earlier fills)
                account_state.open_positions = len(_broker.get_all_positions())
                account_state.daily_trade_count = _session.daily_trade_count
                account_state.consecutive_losses = _session.consecutive_losses
                account_state.daily_realized_pnl = _session.daily_realized_pnl
                (
                    account_state.tracked_crypto_exposure_usd,
                    account_state.broker_recovered_crypto_exposure_usd,
                ) = calculate_crypto_exposure(_session.open_positions)
                (
                    account_state.manual_review_crypto_position_count,
                    account_state.non_controllable_crypto_position_count,
                ) = calculate_crypto_entry_blockers(_session.open_positions)
                (
                    account_state.aggregate_exposure_known,
                    account_state.current_equity_position_exposure_usd,
                    account_state.pending_equity_order_exposure_usd,
                    account_state.recovered_equity_position_exposure_usd,
                    _aggregate_exposure_error,
                ) = calculate_alpaca_equity_exposure(
                    _broker.get_all_positions(),
                    _broker.get_open_orders(),
                    _session.open_positions,
                )
                if not account_state.aggregate_exposure_known:
                    logger.warning(
                        "ENTRY_BLOCKED reason=aggregate_exposure_unknown "
                        f"detail={_aggregate_exposure_error}"
                    )

                allowed, reason = risk_manager.check(proposal, account_state)
                cap_name = ""
                cap_value = 0.0
                current_exposure = 0.0
                projected_exposure = 0.0
                if proposal.asset_class == "crypto":
                    cap_name = "crypto.max_total_crypto_exposure_usd"
                    cap_value = float(get_cfg(
                        "crypto",
                        "max_total_crypto_exposure_usd",
                        default=4.0,
                    ))
                    current_exposure = account_state.tracked_crypto_exposure_usd
                    projected_exposure = current_exposure + proposal.notional
                elif proposal.asset_class in ("equity", "option", "short"):
                    cap_name = "global_risk.max_total_live_exposure_usd"
                    cap_value = float(get_cfg(
                        "global_risk",
                        "max_total_live_exposure_usd",
                        default=6.0,
                    ))
                    current_exposure = (
                        safe_float(account_state.current_equity_position_exposure_usd)
                        + safe_float(account_state.pending_equity_order_exposure_usd)
                        + safe_float(account_state.recovered_equity_position_exposure_usd)
                    )
                    projected_exposure = current_exposure + proposal.notional
                store.record_risk_decision(
                    allowed=allowed,
                    reason=reason,
                    broker=broker_name,
                    asset_class=proposal.asset_class,
                    strategy=proposal.strategy,
                    symbol=proposal.symbol,
                    requested_notional=proposal.notional,
                    current_exposure=current_exposure,
                    projected_exposure=projected_exposure,
                    cap_name=cap_name,
                    cap_value=cap_value,
                    daily_loss=_session.daily_realized_pnl,
                    consecutive_losses=_session.consecutive_losses,
                    payload={
                        "open_positions": account_state.open_positions,
                        "open_orders": account_state.open_orders,
                        "broker_recovered_crypto_exposure": (
                            account_state.broker_recovered_crypto_exposure_usd
                        ),
                        "manual_review_crypto_position_count": (
                            account_state.manual_review_crypto_position_count
                        ),
                        "non_controllable_crypto_position_count": (
                            account_state.non_controllable_crypto_position_count
                        ),
                        "current_equity_position_exposure": (
                            account_state.current_equity_position_exposure_usd
                        ),
                        "pending_equity_order_exposure": (
                            account_state.pending_equity_order_exposure_usd
                        ),
                        "recovered_equity_position_exposure": (
                            account_state.recovered_equity_position_exposure_usd
                        ),
                        "aggregate_exposure_known": (
                            account_state.aggregate_exposure_known
                        ),
                    },
                )

                if not allowed:
                    event_type = "order_blocked"
                    if (
                        proposal.asset_class == "crypto"
                        and account_state.broker_recovered_crypto_exposure_usd > 0
                        and "exposure" in reason.lower()
                    ):
                        event_type = "external_untradeable_exposure_block"
                    store.record_event(
                        event_type=event_type,
                        severity="warning",
                        broker=broker_name,
                        asset_class=proposal.asset_class,
                        strategy=proposal.strategy,
                        symbol=proposal.symbol,
                        payload={
                            "reason": reason,
                            "requested_notional": proposal.notional,
                            "current_exposure": current_exposure,
                            "projected_exposure": projected_exposure,
                            "broker_recovered_crypto_exposure": (
                                account_state.broker_recovered_crypto_exposure_usd
                            ),
                            "manual_review_crypto_position_count": (
                                account_state.manual_review_crypto_position_count
                            ),
                            "non_controllable_crypto_position_count": (
                                account_state.non_controllable_crypto_position_count
                            ),
                            "current_equity_position_exposure": (
                                account_state.current_equity_position_exposure_usd
                            ),
                            "pending_equity_order_exposure": (
                                account_state.pending_equity_order_exposure_usd
                            ),
                            "recovered_equity_position_exposure": (
                                account_state.recovered_equity_position_exposure_usd
                            ),
                            "aggregate_exposure_known": (
                                account_state.aggregate_exposure_known
                            ),
                        },
                        source_component="risk_manager",
                        source_file="risk_manager.py",
                    )
                    journal.log_skip(
                        symbol=proposal.symbol,
                        asset_class=proposal.asset_class,
                        strategy=proposal.strategy,
                        reason=reason,
                        action=proposal.side.upper(),
                        confidence=proposal.confidence,
                        price=proposal.price,
                        bid=proposal.bid,
                        ask=proposal.ask,
                        spread_pct=proposal.meta.get("spread_pct", 0.0),
                        notional=proposal.notional,
                        equity=permissions.equity,
                        buying_power=permissions.buying_power,
                        open_positions=account_state.open_positions,
                        daily_trade_count=_session.daily_trade_count,
                        consecutive_losses=_session.consecutive_losses,
                        mode=mode,
                    )
                    continue

                # Risk manager approved — execute
                order = order_manager.execute(
                    proposal=proposal,
                    session=_session,
                    account_equity=permissions.equity,
                    buying_power=permissions.buying_power,
                    open_positions=account_state.open_positions,
                )

                # After each order check halt state
                if _session.halted:
                    break

        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received in loop")
            _running = False
            break
        except Exception as e:
            _session.api_error_count += 1
            logger.error(f"Unexpected error in main loop cycle {cycle_count}: {e}", exc_info=True)
            _write_heartbeat(broker_name, mode, _session, permissions if 'permissions' in dir() else None, last_error=str(e))
        else:
            _write_heartbeat(broker_name, mode, _session, permissions)
            store.record_event(
                event_type="cycle_complete",
                severity="info",
                broker=broker_name,
                asset_class=args.asset_class,
                payload={
                    "cycle": cycle_count,
                    "open_positions": len(_session.open_positions) if _session else 0,
                    "daily_trade_count": _session.daily_trade_count if _session else 0,
                    "halted": bool(_session and _session.halted),
                },
                source_component="main",
                source_file="main.py",
            )

        if args.once:
            logger.info("--once flag set: exiting after single cycle")
            break

        _maybe_sleep(scan_interval, args.once)

    # ── 7. Graceful shutdown ──────────────────────────────────────────────
    logger.info("Shutting down...")

    # If halted due to critical issue, emergency-close positions
    if _session and _session.halted and _position_mgr:
        logger.critical(f"Session was halted: {_session.halt_reason}")
        open_pos = _broker.get_all_positions() if _broker else []
        if open_pos:
            logger.critical(
                f"HALT with {len(open_pos)} open position(s) — initiating emergency close"
            )
            _position_mgr.close_all_for_halt(_session)

    # Generate daily report
    try:
        ending_equity = 0.0
        unrealized_pnl = 0.0
        if _broker:
            final_account = _broker.get_account()
            if final_account:
                ending_equity = safe_float(getattr(final_account, "equity", starting_equity))
                unrealized_pnl = safe_float(getattr(final_account, "unrealized_pl", 0))

        if get_cfg("logging", "daily_report", default=True):
            reporter.generate_daily_report(
                starting_equity=starting_equity,
                ending_equity=ending_equity,
                unrealized_pnl=unrealized_pnl,
            )
    except Exception as e:
        logger.error(f"Failed to generate daily report: {e}")

    # Release process lock so next startup isn't blocked
    release_process_lock()
    store.record_event(
        event_type="shutdown",
        severity="info",
        broker=broker_name,
        asset_class=args.asset_class,
        payload={
            "halted": bool(_session and _session.halted),
            "halt_reason": _session.halt_reason if _session else "",
        },
        source_component="main",
        source_file="main.py",
    )
    store.finish_run(
        status="halted" if (_session and _session.halted) else "stopped",
        payload={"cycles": cycle_count},
    )
    logger.info("Bot shutdown complete.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _alpaca_non_crypto_symbol(symbol: str) -> bool:
    return bool(symbol) and "/" not in symbol


def _position_exposure_usd(pos: Any) -> float | None:
    market_value = abs(safe_float(getattr(pos, "market_value", 0.0)))
    if market_value > 0:
        return market_value

    qty = abs(safe_float(getattr(pos, "qty", 0.0)))
    current_price = safe_float(getattr(pos, "current_price", 0.0))
    if qty > 0 and current_price > 0:
        return qty * current_price

    avg_entry = safe_float(getattr(pos, "avg_entry_price", 0.0))
    if qty > 0 and avg_entry > 0:
        return qty * avg_entry

    return None


def _order_exposure_usd(order: Any) -> float | None:
    notional = abs(safe_float(getattr(order, "notional", 0.0)))
    if notional > 0:
        return notional

    qty = abs(safe_float(getattr(order, "qty", 0.0)))
    limit_price = safe_float(getattr(order, "limit_price", 0.0))
    if qty > 0 and limit_price > 0:
        return qty * limit_price

    price = safe_float(getattr(order, "price", 0.0))
    if qty > 0 and price > 0:
        return qty * price

    return None


def _tracked_position_exposure_usd(pos_data: dict) -> float | None:
    notional = abs(safe_float(pos_data.get("notional", 0.0)))
    if notional > 0:
        return notional

    qty = abs(safe_float(pos_data.get("qty", 0.0)))
    entry_price = safe_float(pos_data.get("entry_price", 0.0))
    if qty > 0 and entry_price > 0:
        return qty * entry_price

    return None


def calculate_alpaca_equity_exposure(
    open_positions: list[Any],
    open_orders: list[Any],
    tracked_positions: dict,
) -> tuple[bool, float, float, float, str]:
    """
    Aggregate non-crypto Alpaca exposure for the global live exposure cap.

    Counts current broker positions, pending buy/cover orders, and tracked
    broker-recovered/session positions not visible in the broker position list.
    Returns (known, current, pending, recovered, reason). If any exposure
    component cannot be valued, known=False and risk must fail closed.
    """
    current = 0.0
    pending = 0.0
    recovered = 0.0
    broker_symbols: set[str] = set()

    for pos in open_positions:
        sym = getattr(pos, "symbol", "")
        if not _alpaca_non_crypto_symbol(sym):
            continue
        broker_symbols.add(sym)
        exposure = _position_exposure_usd(pos)
        if exposure is None:
            return False, current, pending, recovered, f"unknown_position_exposure:{sym}"
        current += exposure

    for order in open_orders:
        sym = getattr(order, "symbol", "")
        if not _alpaca_non_crypto_symbol(sym):
            continue

        side = str(getattr(order, "side", "")).lower()
        if "sell" in side:
            continue
        if "buy" not in side and "cover" not in side:
            return False, current, pending, recovered, f"unknown_order_side:{sym}"

        exposure = _order_exposure_usd(order)
        if exposure is None:
            return False, current, pending, recovered, f"unknown_order_exposure:{sym}"
        pending += exposure

    for sym, pos_data in tracked_positions.items():
        if not _alpaca_non_crypto_symbol(sym):
            continue
        if sym in broker_symbols:
            continue
        asset_class = str(pos_data.get("asset_class", "equity")).lower()
        if asset_class not in ("equity", "option", "short"):
            continue

        exposure = _tracked_position_exposure_usd(pos_data)
        if exposure is None:
            return False, current, pending, recovered, f"unknown_tracked_exposure:{sym}"
        recovered += exposure

    return True, current, pending, recovered, ""

def _write_heartbeat(
    broker_name: str,
    mode: str,
    session: "SessionState | None",
    permissions: "AccountPermissions | None",
    last_error: str | None = None,
) -> None:
    """
    Write a heartbeat JSON file every loop cycle.

    The watchdog (and any external monitor) reads this to confirm the bot
    is alive and healthy.  Uses an atomic tmp→rename to prevent partial reads.
    """
    import json
    from zoneinfo import ZoneInfo

    try:
        RUNTIME_DIR.mkdir(exist_ok=True)
        hb_file = RUNTIME_DIR / f"{broker_name}_heartbeat.json"
        tz = ZoneInfo("America/Chicago")
        now_str = datetime.now(tz).isoformat()

        payload = {
            "bot": broker_name,
            "pid": os.getpid(),
            "status": "halted" if (session and session.halted) else "running",
            "mode": mode,
            "broker": broker_name,
            "last_loop_time": now_str,
            "open_positions": len(session.open_positions) if session else 0,
            "daily_pnl": round(session.daily_realized_pnl, 4) if session else 0.0,
            "trades_today": session.daily_trade_count if session else 0,
            "last_trade_at": session.last_trade_at if session and session.last_trade_at else None,
            "last_exit_at": session.last_exit_at if session and session.last_exit_at else None,
            "consecutive_losses": session.consecutive_losses if session else 0,
            "api_errors_this_session": session.api_error_count if session else 0,
            "equity": round(permissions.equity, 4) if permissions else 0.0,
            "buying_power": round(permissions.buying_power, 4) if permissions else 0.0,
            "kill_switch_present": kill_switch_active(),
            "risk_halt_active": bool(session and session.halted),
            "halt_reason": (session.halt_reason if session and session.halted else None),
            "last_error": last_error,
        }

        tmp = hb_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
        tmp.rename(hb_file)
    except Exception:
        pass  # heartbeat failure must never crash the bot


def _log_effective_risk_config(log: logging.Logger, mode: str) -> None:
    """
    Log every active risk limit at startup so stale env, launchd environment
    issues, or unintended config defaults are immediately visible.

    Two exposure tiers are printed explicitly:
      crypto_cap  — crypto.max_total_crypto_exposure_usd  (crypto-specific guard)
      global_cap  — global_risk.max_total_live_exposure_usd (cross-asset total)
    Both are real limits; the crypto guard fires first.
    """
    crypto_cap   = get_cfg("crypto",       "max_total_crypto_exposure_usd",  default=4.0)
    global_cap   = get_cfg("global_risk",  "max_total_live_exposure_usd",    default=6.0)
    max_trade    = get_cfg("crypto",       "max_trade_notional_usd",         default=3.0)
    max_loss     = get_cfg("global_risk",  "max_daily_loss_usd",             default=2.0)
    max_consec   = get_cfg("global_risk",  "stop_after_consecutive_losses",  default=2)
    max_trades   = get_cfg("global_risk",  "max_trades_per_day",             default=5)
    max_pos      = get_cfg("global_risk",  "max_open_positions",             default=2)
    equity_floor = get_cfg("account",      "disable_live_below_equity",      default=7.0)
    max_api_err  = get_cfg("global_risk",  "max_api_errors_before_halt",     default=10)
    cooldown_min = get_cfg("crypto",       "coinbase_probe_min_minutes_between_trades", default=60)

    log.info(
        "RISK_CONFIG effective:\n"
        f"  mode                          = {mode}\n"
        f"  max_trade_notional_crypto     = ${float(max_trade):.2f}  "
        f"[crypto.max_trade_notional_usd]\n"
        f"  crypto_exposure_cap           = ${float(crypto_cap):.2f}  "
        f"[crypto.max_total_crypto_exposure_usd]  ← primary crypto guard\n"
        f"  global_exposure_cap           = ${float(global_cap):.2f}  "
        f"[global_risk.max_total_live_exposure_usd]\n"
        f"  max_daily_loss                = ${float(max_loss):.2f}  "
        f"[global_risk.max_daily_loss_usd]\n"
        f"  max_consecutive_losses        = {int(max_consec)}  "
        f"[global_risk.stop_after_consecutive_losses]\n"
        f"  max_trades_per_day            = {int(max_trades)}  "
        f"[global_risk.max_trades_per_day]\n"
        f"  max_open_positions            = {int(max_pos)}  "
        f"[global_risk.max_open_positions]\n"
        f"  equity_floor                  = ${float(equity_floor):.2f}  "
        f"[account.disable_live_below_equity]\n"
        f"  max_api_errors_before_halt    = {int(max_api_err)}  "
        f"[global_risk.max_api_errors_before_halt]\n"
        f"  coinbase_probe_cooldown_min   = {int(cooldown_min)}  "
        f"[crypto.coinbase_probe_min_minutes_between_trades]"
    )


def _maybe_sleep(seconds: int, once: bool) -> None:
    """
    Sleep in 1-second ticks so Ctrl+C (SIGINT) exits within 1 second.

    Python 3.5+ (PEP 475) restarts interrupted system calls, which means a
    single time.sleep(60) call ignores SIGINT until the full 60 s elapse.
    Ticking 1 s at a time lets the loop check _running after each tick.
    """
    if once:
        return
    logger = logging.getLogger("main")
    logger.debug(f"Sleeping {seconds}s until next cycle...")
    for _ in range(seconds):
        if not _running:
            break
        time.sleep(1)


if __name__ == "__main__":
    main()
