"""
strategy_crypto.py — Crypto trading strategies.

Three strategies, all long-only (Coinbase/Alpaca Crypto does not support shorts):
  1. momentum_breakout — price breaks above N-bar high with volume + EMA confirmation
  2. mean_reversion    — RSI oversold at lower Bollinger Band; bullish reversal bar required
  3. ema_crossover     — fresh EMA9 > EMA21 crossover in healthy RSI zone

Key improvements over v1:
  - ATR-based dynamic stop/target (replaces static 1.5%/2.5%)
  - Regime detection (classify_regime) routes the right strategy to the right market
  - Best-proposal selection: all regime-allowed strategies run; highest (edge, conf, r:r) wins
  - Passive limit entry at best bid to target maker fills
  - Correct Alpaca fee model (0.15% maker / 0.25% taker)
  - worst_case_edge_pct computed (taker both sides) and exposed to risk manager
  - Once-per-closed-bar evaluation (skips re-scanning the same 5-min candle)
  - 100-bar fetch with 75-bar minimum for stable indicators

The strategy NEVER places orders. It only proposes.
"""

from __future__ import annotations

import csv
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from market_data import MarketData, Quote, add_indicators
from risk_manager import TradeProposal
from utils import (
    get_cfg,
    is_external_inventory_excluded_symbol,
    load_external_inventory_excluded_symbols,
    load_saved_positions,
    now_utc,
    safe_float,
    spread_pct as calc_spread,
)

# P2-012B: prediction telemetry integration (live scan decisions).
# Safe import + no-op fallbacks so telemetry can never break strategy loading or execution.
try:
    from prediction_telemetry import (
        compute_derivative_features,
        safe_log_proposal_candidate,
        safe_log_skipped_proposal,
    )

    _HAS_PREDICTION_TELEMETRY = True
except Exception:
    _HAS_PREDICTION_TELEMETRY = False

    def compute_derivative_features(*args, **kwargs):  # type: ignore
        return {}

    def safe_log_proposal_candidate(*args, **kwargs):  # type: ignore
        return {}

    def safe_log_skipped_proposal(*args, **kwargs):  # type: ignore
        return {}


logger = logging.getLogger("strategy.crypto")

ROOT = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Regime detection
# ---------------------------------------------------------------------------

# Which strategies are allowed to fire in each regime.
# Downtrend and dead_chop produce no proposals — staying out IS the trade.
REGIME_STRATEGIES: dict[str, list[str]] = {
    "uptrend":        ["momentum_breakout", "ema_crossover"],
    "range":          ["mean_reversion"],
    "volatile_range": ["mean_reversion", "momentum_breakout"],
    "downtrend":      [],
    "dead_chop":      [],
}


def classify_regime(df: pd.DataFrame) -> str:
    """
    Classify the current market regime from indicator state on the latest bar.

    Returns one of: "uptrend" | "downtrend" | "range" | "volatile_range" | "dead_chop"

    Thresholds are intentionally conservative — it is better to label "range"
    when unsure than to force a trending label.
    """
    if len(df) < 10:
        return "range"  # safe default — not enough data

    latest = df.iloc[-1]

    ema9 = safe_float(latest.get("ema_9"))
    ema21 = safe_float(latest.get("ema_21"))
    close = safe_float(latest.get("c", 1))
    atr_pct = safe_float(latest.get("atr_pct"))        # fraction (e.g. 0.012 = 1.2%)
    bb_upper = safe_float(latest.get("bb_upper"))
    bb_lower = safe_float(latest.get("bb_lower"))
    bb_mid = safe_float(latest.get("bb_mid", 1))

    if ema9 <= 0 or ema21 <= 0 or bb_mid <= 0:
        return "range"

    ema_gap_pct = abs(ema9 - ema21) / close if close > 0 else 0.0

    # EMA21 slope over last 6 bars (5-min bars = ~30 min window)
    ema21_series = df["ema_21"].dropna()
    if len(ema21_series) >= 6:
        ema_slope = (
            float(ema21_series.iloc[-1]) - float(ema21_series.iloc[-6])
        ) / float(ema21_series.iloc[-6])
    else:
        ema_slope = 0.0

    bb_width = (bb_upper - bb_lower) / bb_mid if bb_mid > 0 else 0.0

    # Regime flags
    trending = ema_gap_pct > 0.003 and abs(ema_slope) > 0.002
    high_vol = atr_pct > 0.015 or bb_width > 0.04
    compressed = atr_pct < 0.004 and bb_width < 0.015

    if compressed:
        return "dead_chop"
    if trending and ema9 > ema21:
        return "uptrend"
    if trending and ema9 < ema21:
        return "downtrend"
    if high_vol:
        return "volatile_range"
    return "range"


# ---------------------------------------------------------------------------
# CryptoStrategy
# ---------------------------------------------------------------------------

class CryptoStrategy:
    def __init__(self, market_data: MarketData) -> None:
        self._md = market_data
        # Once-per-closed-bar tracker: symbol -> last bar timestamp string
        self._last_bar_ts: dict[str, str] = {}
        # Controlled Exploration state (P2-001B) — now recovered from journal/state on demand
        self._exploration_proposed_this_cycle: bool = False
        # Runtime equity from the bot loop (P2-004). Preferred when set.
        self.current_equity: float | None = None

    # -----------------------------------------------------------------------
    # Dynamic Position Sizing (P2-004) — Coinbase exploration only
    # -----------------------------------------------------------------------

    def _resolve_equity_for_sizing(self) -> float | None:
        """
        Equity for P2-004 sizing on Coinbase controlled exploration only.

        Prefers ``self.current_equity`` when the runtime has set it (live cycle).
        Otherwise falls back to journal-derived equity, which may be stale — it
        reflects the last logged row, not a fresh broker balance.
        """
        if self.current_equity is not None and self.current_equity > 0:
            return float(self.current_equity)
        return self._get_journal_equity()

    def _get_journal_equity(self) -> float | None:
        """
        Fallback equity from the most recent journal row (may be stale).
        """
        try:
            logging_cfg = get_cfg("logging", default={})
            if not logging_cfg:
                return None
            
            journal_file = logging_cfg.get("journal_file", "journal_coinbase_crypto.csv")
            journal_path = ROOT / journal_file
            
            if not journal_path.exists():
                return None
            
            # Read journal and get equity from most recent row
            with open(journal_path, "r", newline="") as f:
                rows = list(csv.DictReader(f))
                if not rows:
                    return None
                
                # Iterate from end backwards to find first non-zero equity
                for row in reversed(rows):
                    equity_str = row.get("equity", "").strip()
                    if equity_str and equity_str != "0.0":
                        try:
                            equity = float(equity_str)
                            if equity > 0:
                                return equity
                        except (ValueError, TypeError):
                            continue
            
            return None
        except Exception as e:
            logger.debug(f"Error retrieving current equity from journal: {e}")
            return None

    # -----------------------------------------------------------------------
    # Controlled Exploration Helpers (P2-001B)
    # -----------------------------------------------------------------------

    def _load_exploration_history(self) -> dict[str, datetime]:
        """
        Load recent exploration history from journal.
        Returns: {symbol: last_timestamp} for all exploration entries in past 24h.
        """
        history: dict[str, datetime] = {}
        try:
            logging_cfg = get_cfg("logging", default={})
            if not logging_cfg:
                return history
                
            journal_file = logging_cfg.get("journal_file", "journal_coinbase_crypto.csv")
            journal_path = ROOT / journal_file
            
            if not journal_path.exists():
                return history
            
            now = now_utc()
            with open(journal_path, "r", newline="") as f:
                rows = list(csv.DictReader(f))
                for row in reversed(rows):  # Most recent first
                    if row.get("strategy") != "coinbase_exploration":
                        continue
                    
                    raw_ts = row.get("timestamp", "")
                    symbol = row.get("symbol", "")
                    
                    if not symbol:
                        continue
                    
                    try:
                        ts = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=timezone.utc)
                        
                        # Only keep entries from last 24 hours
                        if (now - ts).total_seconds() < 24 * 3600:
                            if symbol not in history:
                                history[symbol] = ts
                    except (ValueError, AttributeError):
                        continue
        except Exception as e:
            logger.debug(f"Error loading exploration history: {e}")
        
        return history

    def _get_exploration_entries_today(self) -> dict[str, int]:
        """
        Count exploration entries per symbol in the last 24 hours.
        Returns: {symbol: count_of_entries}
        """
        counts: dict[str, int] = {}
        try:
            logging_cfg = get_cfg("logging", default={})
            if not logging_cfg:
                return counts
                
            journal_file = logging_cfg.get("journal_file", "journal_coinbase_crypto.csv")
            journal_path = ROOT / journal_file
            
            if not journal_path.exists():
                return counts
            
            now = now_utc()
            with open(journal_path, "r", newline="") as f:
                rows = list(csv.DictReader(f))
                for row in rows:
                    if row.get("strategy") != "coinbase_exploration":
                        continue
                    
                    raw_ts = row.get("timestamp", "")
                    symbol = row.get("symbol", "")
                    decision = row.get("decision", "")
                    
                    if not symbol:
                        continue
                    
                    try:
                        ts = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=timezone.utc)
                        
                        # Only count entries from last 24 hours
                        if (now - ts).total_seconds() < 24 * 3600:
                            # Count both FILLED and PLACED (not SKIPPED)
                            if decision in ("FILLED", "PLACED"):
                                counts[symbol] = counts.get(symbol, 0) + 1
                    except (ValueError, AttributeError):
                        continue
        except Exception as e:
            logger.debug(f"Error counting exploration entries: {e}")
        
        return counts

    def _get_open_symbol_positions(self) -> set[str]:
        """
        Load open positions from saved state.
        Returns: set of symbols that have open positions.
        """
        try:
            positions = load_saved_positions()
            return set(positions.keys())
        except Exception as e:
            logger.debug(f"Error loading open positions: {e}")
            return set()

    def _select_exploration_symbol(self, approved_symbols: list[str]) -> Optional[str]:
        """
        Intelligently select the next exploration symbol based on:
        1. Avoid symbols with open positions
        2. Avoid symbols on per-symbol cooldown
        3. Avoid symbols at max entries per day
        4. Prefer least-recently-selected symbol
        
        Returns: symbol name, or None if no eligible symbol found.
        """
        if not approved_symbols:
            return None
        
        cfg = get_cfg("crypto", "controlled_exploration", default={})
        cooldown_min = float(cfg.get("per_symbol_cooldown_minutes", 30))
        max_entries_per_day = float(cfg.get("max_entries_per_symbol_per_day", 4))
        avoid_repeat = cfg.get("avoid_same_symbol_repeat", True)
        
        history = self._load_exploration_history()
        entries_today = self._get_exploration_entries_today()
        open_positions = self._get_open_symbol_positions()
        external_inventory_excluded = load_external_inventory_excluded_symbols()
        now = now_utc()
        
        # Filter: eligible symbols
        eligible = []
        reject_reasons: dict[str, str] = {}
        
        for symbol in approved_symbols:
            if is_external_inventory_excluded_symbol(
                symbol,
                excluded_symbols=external_inventory_excluded,
            ):
                reject_reasons[symbol] = "external_inventory_symbol_excluded"
                continue

            # 1. Has open position?
            if symbol in open_positions:
                reject_reasons[symbol] = "already_has_open_position"
                continue
            
            # 2. On cooldown?
            if symbol in history:
                last_ts = history[symbol]
                age_min = (now - last_ts).total_seconds() / 60.0
                if age_min < cooldown_min:
                    reject_reasons[symbol] = f"cooldown({age_min:.0f}m<{cooldown_min:.0f}m)"
                    continue
            
            # 3. At max entries today?
            count_today = entries_today.get(symbol, 0)
            if count_today >= max_entries_per_day:
                reject_reasons[symbol] = f"max_entries_per_day({count_today:.0f}>={max_entries_per_day:.0f})"
                continue
            
            # Eligible!
            eligible.append((symbol, history.get(symbol)))
        
        # Log rejections
        for symbol, reason in reject_reasons.items():
            logger.debug(f"EXPLORE {symbol} | ineligible: {reason}")
        
        if not eligible:
            return None
        
        # If avoid_repeat is enabled, sort by least-recently-selected
        # (None timestamps = never selected, go first)
        eligible.sort(key=lambda x: (x[1] is not None, x[1]))
        
        selected = eligible[0][0]
        last_ts = eligible[0][1]
        if last_ts:
            age_min = (now - last_ts).total_seconds() / 60.0
            logger.info(f"EXPLORE selected {selected} | least-recently-used({age_min:.0f}m ago)")
        else:
            logger.info(f"EXPLORE selected {selected} | never-selected-before")
        
        return selected

    # -----------------------------------------------------------------------
    # Notional sizing — capped by actual buying power with safety buffer
    # -----------------------------------------------------------------------

    def _compute_notional(self, buying_power: float | None) -> float | None:
        """
        Return safe order notional, or None if below exchange minimum.

        Logic:
          1. Start with config max_trade_notional_usd
          2. Cap at buying_power * buying_power_safety_buffer  (if buying_power known)
          3. If result < min_trade_notional_usd → return None (skip trade)
        """
        max_trade = get_cfg("crypto", "max_trade_notional_usd", default=2.0)
        min_notional = get_cfg("crypto", "min_trade_notional_usd", default=0.50)
        buf = get_cfg("crypto", "buying_power_safety_buffer", default=0.85)

        notional = max_trade
        if buying_power is not None and buying_power > 0:
            safe_bp = buying_power * buf
            notional = min(notional, safe_bp)

        if notional < min_notional:
            return None  # below exchange/config minimum — skip
        return notional

    def _exploration_hard_trade_cap_usd(self) -> float:
        exp_cfg = get_cfg("crypto", "controlled_exploration", default={}) or {}
        return float(exp_cfg.get("max_single_trade_notional_usd", 1.00))

    def _compute_equity_scaled_notional(self, equity: float) -> float:
        """
        Equity-percent notional before Class 2 hard caps (exploration path only).

        Clamped to dynamic_sizing min/max band only; caller applies trade caps.
        """
        ds_cfg = get_cfg("crypto", "dynamic_sizing", default={}) or {}
        min_notional = float(ds_cfg.get("min_notional_usd", 1.00))
        max_notional = float(ds_cfg.get("max_notional_usd", 25.00))
        threshold = float(ds_cfg.get("scaling_threshold_usd", 20.00))
        size_pct = float(ds_cfg.get("position_size_pct", 2.5))

        if equity < threshold:
            return min_notional

        notional = equity * (size_pct / 100.0)
        return max(min_notional, min(notional, max_notional))

    def _resolve_exploration_notional(self, buying_power: float | None) -> float:
        """
        Final Coinbase exploration notional with all hard caps applied (P2-004).

        When dynamic sizing is off or equity is missing/invalid, uses the legacy
        exploration path: ``_compute_notional`` capped by
        ``controlled_exploration.max_single_trade_notional_usd``.

        Otherwise::

            min(
                equity_scaled_notional,
                dynamic_sizing.max_notional_usd,
                controlled_exploration.max_single_trade_notional_usd,
                buying_power * buying_power_safety_buffer  (if buying_power > 0),
            )
        """
        hard_trade_cap = self._exploration_hard_trade_cap_usd()
        ds_cfg = get_cfg("crypto", "dynamic_sizing", default={}) or {}
        if not ds_cfg.get("enabled", False):
            notional = self._compute_notional(buying_power) or 0.50
            return round(min(notional, hard_trade_cap), 2)

        equity = self._resolve_equity_for_sizing()
        if equity is None or equity <= 0:
            notional = self._compute_notional(buying_power) or 0.50
            return round(min(notional, hard_trade_cap), 2)

        try:
            dynamic = self._compute_equity_scaled_notional(equity)
            ds_max = float(ds_cfg.get("max_notional_usd", 25.00))
            buf = float(get_cfg("crypto", "buying_power_safety_buffer", default=0.85))
            caps = [dynamic, ds_max, hard_trade_cap]
            if buying_power is not None and buying_power > 0:
                caps.append(buying_power * buf)
            return round(min(caps), 2)
        except Exception:
            notional = self._compute_notional(buying_power) or 0.50
            return round(min(notional, hard_trade_cap), 2)

    def get_dynamic_daily_stop_loss(self) -> float | None:
        """
        ADVISORY ONLY (P2-004): not wired to risk_manager live gates.

        Returns min(equity * daily_stop_loss_pct, controlled_exploration.daily_stop_loss_usd)
        when dynamic sizing is enabled and equity is available.
        """
        try:
            ds_cfg = get_cfg("crypto", "dynamic_sizing", default={}) or {}
            if not ds_cfg.get("enabled", False):
                return None

            equity = self._resolve_equity_for_sizing()
            if equity is None or equity <= 0:
                return None

            exp_cfg = get_cfg("crypto", "controlled_exploration", default={}) or {}
            absolute_cap = float(exp_cfg.get("daily_stop_loss_usd", 3.00))
            daily_stop_loss_pct = float(ds_cfg.get("daily_stop_loss_pct", 7.5))
            dynamic = equity * (daily_stop_loss_pct / 100.0)
            return round(min(dynamic, absolute_cap), 2)
        except Exception:
            return None

    def get_dynamic_max_exposure(self) -> float | None:
        """
        ADVISORY ONLY (P2-004): not wired to risk_manager live gates.

        Returns min(equity * max_exposure_pct, controlled_exploration.max_total_exploration_exposure_usd)
        when dynamic sizing is enabled and equity is available.
        """
        try:
            ds_cfg = get_cfg("crypto", "dynamic_sizing", default={}) or {}
            if not ds_cfg.get("enabled", False):
                return None

            equity = self._resolve_equity_for_sizing()
            if equity is None or equity <= 0:
                return None

            exp_cfg = get_cfg("crypto", "controlled_exploration", default={}) or {}
            absolute_cap = float(exp_cfg.get("max_total_exploration_exposure_usd", 6.00))
            max_exposure_pct = float(ds_cfg.get("max_exposure_pct", 15.0))
            dynamic = equity * (max_exposure_pct / 100.0)
            return round(min(dynamic, absolute_cap), 2)
        except Exception:
            return None

    def _build_dynamic_exit(
        self,
        entry_price: float,
        atr_pct: float,           # ATR as fraction of price (e.g. 0.012 = 1.2%)
        spread_pct_val: float,    # spread in % (e.g. 0.12)
        strategy: str,
    ) -> tuple[float, float, float, float]:
        """
        Compute dynamic stop and target based on ATR and fee costs.

        Returns (stop_price, target_price, stop_pct, target_pct) where
        stop_pct and target_pct are percentages (e.g. 1.2 means 1.2%).

        Falls back to static config values when ATR is unavailable.
        """
        use_atr = get_cfg("crypto", "use_atr_exits", default=True)
        static_sl = get_cfg("crypto", "stop_loss_pct", default=1.5)
        static_tp = get_cfg("crypto", "take_profit_pct", default=2.5)

        if not use_atr or atr_pct <= 0:
            stop_price = entry_price * (1 - static_sl / 100.0)
            target_price = entry_price * (1 + static_tp / 100.0)
            return stop_price, target_price, static_sl, static_tp

        # Fees: worst-case (taker both sides) to ensure target clears even on bad fills
        taker_fee = get_cfg("fees", "taker_fee_pct", default=0.0025)
        worst_rt_fee_pct = taker_fee * 2 * 100.0        # e.g. 0.50%
        slippage_pct = get_cfg("crypto", "slippage_estimate_pct", default=0.05)
        required_edge = get_cfg("fees", "require_expected_edge_pct", default=0.006) * 100.0

        # Minimum target must clear all costs plus required net edge
        min_target_pct = worst_rt_fee_pct + spread_pct_val + slippage_pct + required_edge

        def _clamp(v: float, lo: float, hi: float) -> float:
            return max(lo, min(hi, v))

        atr_as_pct = atr_pct * 100.0  # convert fraction to %

        if strategy == "momentum_breakout":
            stop_pct = _clamp(1.25 * atr_as_pct, 0.80, 3.00)
            target_pct = max(1.8 * stop_pct, min_target_pct)

        elif strategy == "ema_crossover":
            stop_pct = _clamp(1.10 * atr_as_pct, 0.75, 2.50)
            target_pct = max(1.6 * stop_pct, min_target_pct)

        elif strategy == "mean_reversion":
            stop_pct = _clamp(1.00 * atr_as_pct, 0.60, 2.20)
            target_pct = max(1.25 * atr_as_pct, min_target_pct)

        else:
            stop_pct = _clamp(atr_as_pct, 0.80, 2.50)
            target_pct = max(1.5 * stop_pct, min_target_pct)

        stop_price = entry_price * (1 - stop_pct / 100.0)
        target_price = entry_price * (1 + target_pct / 100.0)
        return stop_price, target_price, stop_pct, target_pct

    # -----------------------------------------------------------------------
    # Fee-aware edge metadata — attached to every proposal's meta dict
    # -----------------------------------------------------------------------

    def _fee_meta(
        self,
        spread_pct_val: float,
        tp_pct: float,     # in % (e.g. 2.5)
        sl_pct: float,     # in % (e.g. 1.5)
    ) -> dict:
        """
        Compute expected and worst-case edge vs. round-trip fees and spread.

        Uses Alpaca Crypto fee model (0.15% maker / 0.25% taker).
        Expected edge assumes maker fills on both legs (passive limit orders).
        Worst-case edge assumes taker fills on both legs (marketable fills).
        """
        maker_fee = get_cfg("fees", "maker_fee_pct", default=0.0015)
        taker_fee = get_cfg("fees", "taker_fee_pct", default=0.0025)
        slippage = get_cfg("crypto", "slippage_estimate_pct", default=0.05)

        round_trip_fee_pct = (maker_fee + maker_fee) * 100.0   # best case: maker both sides
        worst_rt_fee_pct = taker_fee * 2 * 100.0               # worst case: taker both sides

        spread_cost_pct = spread_pct_val
        expected_edge_pct = tp_pct                              # e.g. 2.5%
        net_expected_edge_pct = (
            expected_edge_pct - round_trip_fee_pct - spread_cost_pct - slippage
        )
        worst_case_edge_pct = (
            expected_edge_pct - worst_rt_fee_pct - spread_cost_pct - slippage
        )
        reward_risk_ratio = tp_pct / sl_pct if sl_pct > 0 else 0.0

        return {
            "entry_fee_pct": maker_fee * 100.0,
            "exit_fee_pct": maker_fee * 100.0,
            "round_trip_fee_pct": round_trip_fee_pct,
            "worst_case_rt_fee_pct": worst_rt_fee_pct,
            "spread_cost_pct": spread_cost_pct,
            "slippage_pct": slippage,
            "expected_edge_pct": expected_edge_pct,
            "net_expected_edge_pct": net_expected_edge_pct,
            "worst_case_edge_pct": worst_case_edge_pct,
            "reward_risk_ratio": reward_risk_ratio,
        }

    # -----------------------------------------------------------------------
    # Main entry point: generate proposals for a single symbol
    # -----------------------------------------------------------------------

    def generate_proposals(
        self, symbol: str, buying_power: float | None = None
    ) -> list[TradeProposal]:
        """
        Evaluate all regime-appropriate strategies for a symbol.

        Returns a list containing at most one proposal — the best by
        (net_expected_edge_pct, confidence, reward_risk_ratio).

        Implements once-per-closed-bar guard: if the latest bar timestamp
        hasn't changed since the last call, returns [] immediately so the
        main loop doesn't redundantly scan the same candle multiple times.
        """
        prefer_no_trade = get_cfg("strategy", "prefer_no_trade_when_unclear", default=True)

        # Fetch quote
        quote = self._md.get_crypto_quote(symbol)
        if not quote.valid:
            age_s = ""
            if quote.timestamp:
                age_s = f" (age={(now_utc()-quote.timestamp).total_seconds():.0f}s)"
            logger.info(
                f"SCAN {symbol}: invalid quote — "
                f"bid={quote.bid} ask={quote.ask} stale={quote.is_stale}{age_s}"
            )
            if _HAS_PREDICTION_TELEMETRY:
                safe_log_skipped_proposal(
                    {"symbol": symbol, "strategy": "none", "product_type": "spot_crypto"},
                    reason="invalid_quote",
                    regime=None,
                    source="strategy_crypto",
                    raw_payload={"scan_stage": "quote"},
                )
            return []

        bars_limit = get_cfg("crypto", "bars_limit", default=100)
        min_bars = get_cfg("crypto", "min_bars_required", default=75)
        lookback = get_cfg("strategy", "lookback_bars", default=20)
        df = self._md.get_crypto_bars_df(symbol, limit=bars_limit)
        if df.empty or len(df) < min_bars:
            logger.info(f"SCAN {symbol}: only {len(df)} bars (need {min_bars}), skipping")
            if _HAS_PREDICTION_TELEMETRY:
                safe_log_skipped_proposal(
                    {"symbol": symbol, "strategy": "none", "product_type": "spot_crypto"},
                    reason="insufficient_bars",
                    regime=None,
                    source="strategy_crypto",
                    raw_payload={"bars": len(df) if df is not None else 0, "min_required": min_bars},
                )
            return []

        # Once-per-closed-bar guard
        latest_bar_ts = str(df.index[-1]) if hasattr(df.index, '__getitem__') else ""
        if latest_bar_ts and self._last_bar_ts.get(symbol) == latest_bar_ts:
            logger.debug(f"SCAN {symbol}: same closed bar as last cycle, skipping entry scan")
            if _HAS_PREDICTION_TELEMETRY:
                safe_log_skipped_proposal(
                    {"symbol": symbol, "strategy": "none", "product_type": "spot_crypto"},
                    reason="same_closed_bar_guard",
                    regime=None,
                    source="strategy_crypto",
                    raw_payload={"last_bar_ts": latest_bar_ts},
                )
            return []
        self._last_bar_ts[symbol] = latest_bar_ts

        df = add_indicators(df)

        # Classify market regime to select appropriate strategies
        regime = classify_regime(df)
        allowed = REGIME_STRATEGIES.get(regime, [])
        logger.info(f"SCAN {symbol}: regime={regime} | allowed_strategies={allowed}")

        # P2-012B: live prediction telemetry for every scanned symbol (non-fatal, never blocks proposals)
        _scan_features: Dict[str, Any] = {}
        try:
            closes = [float(x) for x in df["c"].tolist()[-40:]] if len(df) > 0 and "c" in df.columns else []
            _scan_features = compute_derivative_features(
                closes, bid=quote.bid, ask=quote.ask, current_price=(quote.bid + quote.ask) / 2 if quote.bid and quote.ask else None
            )
        except Exception:
            _scan_features = {}
        _scan_raw = {"allowed_strategies": allowed, "regime": regime, "scan_source": "generate_proposals"}

        if not allowed:
            # 1. Controlled Exploration (P2-001)
            exploration = self._coinbase_exploration(symbol, quote, df, buying_power, regime)
            if exploration is not None:
                if _HAS_PREDICTION_TELEMETRY:
                    safe_log_proposal_candidate(
                        exploration, regime=regime, source="strategy_crypto", features=_scan_features, raw_payload=_scan_raw
                    )
                return [exploration]

            # 2. Legacy Probe
            probe = self._coinbase_probe(symbol, quote, df, prefer_no_trade, buying_power, regime)
            if probe is not None:
                if _HAS_PREDICTION_TELEMETRY:
                    safe_log_proposal_candidate(
                        probe, regime=regime, source="strategy_crypto", features=_scan_features, raw_payload=_scan_raw
                    )
                return [probe]

            logger.info(f"SCAN {symbol}: no strategies allowed in {regime} regime — sitting out")
            if _HAS_PREDICTION_TELEMETRY:
                safe_log_skipped_proposal(
                    {"symbol": symbol, "strategy": "none", "product_type": "spot_crypto"},
                    reason=f"no_strategies_allowed_in_{regime}_regime_sitting_out",
                    regime=regime,
                    source="strategy_crypto",
                    features=_scan_features,
                    raw_payload=_scan_raw,
                )
            return []

        # Run all regime-allowed strategies; collect proposals
        candidates: list[TradeProposal] = []
        for strat_name in allowed:
            p: Optional[TradeProposal] = None
            if strat_name == "momentum_breakout":
                p = self._momentum_breakout(symbol, quote, df, prefer_no_trade, buying_power, lookback, regime)
            elif strat_name == "mean_reversion":
                p = self._mean_reversion(symbol, quote, df, prefer_no_trade, buying_power, regime)
            elif strat_name == "ema_crossover":
                p = self._ema_crossover(symbol, quote, df, prefer_no_trade, buying_power, regime)
            if p is not None:
                candidates.append(p)

        if not candidates:
            # Main strategies sat out — try exploration/probe as fallbacks
            exploration = self._coinbase_exploration(symbol, quote, df, buying_power, regime)
            if exploration is not None:
                if _HAS_PREDICTION_TELEMETRY:
                    safe_log_proposal_candidate(
                        exploration, regime=regime, source="strategy_crypto", features=_scan_features, raw_payload=_scan_raw
                    )
                return [exploration]

            probe = self._coinbase_probe(symbol, quote, df, prefer_no_trade, buying_power, regime)
            if probe is not None:
                if _HAS_PREDICTION_TELEMETRY:
                    safe_log_proposal_candidate(
                        probe, regime=regime, source="strategy_crypto", features=_scan_features, raw_payload=_scan_raw
                    )
                return [probe]
            if _HAS_PREDICTION_TELEMETRY:
                safe_log_skipped_proposal(
                    {"symbol": symbol, "strategy": "none", "product_type": "spot_crypto"},
                    reason="no_valid_candidate_after_regime_strategies",
                    regime=regime,
                    source="strategy_crypto",
                    features=_scan_features,
                    raw_payload=_scan_raw,
                )
            return []

        # Select best proposal by (net_expected_edge_pct, confidence, reward_risk_ratio)
        def _score(p: TradeProposal) -> tuple:
            return (
                p.meta.get("net_expected_edge_pct", 0.0),
                p.confidence,
                p.meta.get("reward_risk_ratio", 0.0),
            )

        best = max(candidates, key=_score)
        if len(candidates) > 1:
            logger.info(
                f"SCAN {symbol}: {len(candidates)} candidates — "
                f"selected {best.strategy} "
                f"(edge={best.meta.get('net_expected_edge_pct', 0):.2f}% "
                f"conf={best.confidence:.2f} "
                f"r:r={best.meta.get('reward_risk_ratio', 0):.2f})"
            )
        if _HAS_PREDICTION_TELEMETRY:
            safe_log_proposal_candidate(
                best, regime=regime, source="strategy_crypto", features=_scan_features, raw_payload=_scan_raw
            )
        return [best]

    # -----------------------------------------------------------------------
    # Strategy 1: Momentum Breakout
    # -----------------------------------------------------------------------

    # -----------------------------------------------------------------------
    # Selection Logic: Controlled Exploration (P2-001)
    # -----------------------------------------------------------------------

    def _coinbase_exploration(
        self,
        symbol: str,
        quote: Quote,
        df: pd.DataFrame,
        buying_power: float | None,
        regime: str,
    ) -> Optional[TradeProposal]:
        """
        Controlled Coinbase exploration (P2-001B).
        
        Intelligently rotates across BTC, ETH, SOL to gather diverse live shadow data.
        Uses journal-based history to avoid open positions and respect cooldowns.
        """
        try:
            cfg = get_cfg("crypto", "controlled_exploration", default={})
            enabled = cfg.get("enabled", False)

            # Reset flag if we are at the start of a new scan cycle
            live_syms = get_cfg("crypto", "live_symbols", default=[])
            is_first_sym = live_syms and symbol == live_syms[0]
            
            if is_first_sym:
                self._exploration_proposed_this_cycle = False
                if not enabled:
                    logger.debug("EXPLORE | mode disabled in config")

            if not enabled:
                return None

            if self._exploration_proposed_this_cycle:
                return None

            approved_symbols = cfg.get("approved_symbols", ["BTC/USD", "ETH/USD", "SOL/USD"])
            
            # Only offer exploration if this symbol is in the approved list
            if symbol not in approved_symbols:
                logger.debug(f"EXPLORE {symbol} | not in approved_symbols")
                return None

            # Use intelligent symbol selection (P2-001B)
            # Select the best candidate among all approved symbols
            selected_symbol = self._select_exploration_symbol(approved_symbols)
            
            if selected_symbol is None:
                logger.debug("EXPLORE | no eligible symbols found")
                return None
            
            # Only propose if this is the selected symbol (prevent multiple proposals per cycle)
            if symbol != selected_symbol:
                logger.debug(f"EXPLORE {symbol} | not selected (target is {selected_symbol})")
                return None

            # Basic filters for quote validity
            bid = float(quote.bid)
            ask = float(quote.ask)
            mid = float(quote.mid)

            if bid <= 0 or ask <= 0 or mid <= 0:
                logger.warning(f"EXPLORE {selected_symbol} | rejected: invalid quote (bid={bid})")
                return None

            spread_pct_val = ((ask - bid) / mid) * 100.0
            max_spread = float(get_cfg("crypto", "coinbase_probe_max_spread_pct", default=0.10))
            if spread_pct_val > max_spread:
                logger.info(f"EXPLORE {selected_symbol} | rejected: spread {spread_pct_val:.3f}% > max {max_spread:.3f}%")
                return None

            # All good — Propose! (P2-004 sizing: single resolver, all hard caps)
            notional = self._resolve_exploration_notional(buying_power)

            sl_pct = 1.50
            tp_pct = 3.25
            
            meta = {
                "controlled_exploration_enabled": True,
                "exploration_candidate_symbols": approved_symbols,
                "exploration_selected_symbol": selected_symbol,
                "exploration_notional_usd": notional,
                "risk_caps_unchanged": True,
                "no_live_risk_bypass": True,
                "regime": regime,
                "spread_pct": spread_pct_val,
                "probe": True,
            }
            
            logger.info(
                f"SIGNAL coinbase_exploration {selected_symbol} | regime={regime} | "
                f"notional=${notional:.2f} conf=0.60"
            )
            
            self._exploration_proposed_this_cycle = True
            
            return TradeProposal(
                symbol=selected_symbol,
                asset_class="crypto",
                strategy="coinbase_exploration",
                side="buy",
                order_type="limit",
                notional=notional,
                limit_price=bid,
                confidence=0.60,
                bid=bid,
                ask=ask,
                price=mid,
                quote_time=quote.timestamp,
                stop_loss_price=mid * (1 - sl_pct/100.0),
                take_profit_price=mid * (1 + tp_pct/100.0),
                meta=meta
            )
        except Exception as e:
            logger.error(f"Exploration error for {symbol}: {e}")
            return None

    def _coinbase_probe(self, symbol, quote, df, prefer_no_trade, buying_power, regime):
        """
        Explicit opt-in Coinbase micro-probe.

        This does not alter REGIME_STRATEGIES. It only allows a tiny,
        risk-managed proposal when the main strategy would otherwise sit out.

        Design:
        - Coinbase crypto only
        - disabled unless crypto.coinbase_probe_enabled=true
        - symbols limited by crypto.coinbase_probe_symbols
        - regimes limited by crypto.coinbase_probe_regimes
        - returns TradeProposal only; order/risk layers still control execution
        """
        try:
            if not get_cfg("crypto", "coinbase_probe_enabled", default=False):
                return None

            # P2-001: Disable legacy probe if exploration is enabled and configured to disable legacy
            exp_cfg = get_cfg("crypto", "controlled_exploration", default={})
            if exp_cfg.get("enabled") and exp_cfg.get("disable_legacy_btc_probe_when_enabled"):
                return None

            probe_symbols = get_cfg("crypto", "coinbase_probe_symbols", default=["BTC/USD"])
            if symbol not in probe_symbols:
                logger.info(f"SCAN {symbol} probe | not in coinbase_probe_symbols — skipped")
                return None

            probe_regimes = get_cfg("crypto", "coinbase_probe_regimes", default=["dead_chop"])
            if regime not in probe_regimes:
                logger.info(f"SCAN {symbol} probe | regime={regime} not allowed for probe — skipped")
                return None

            if not hasattr(self, "_last_probe_at"):
                self._last_probe_at = {}

            from utils import now_utc
            now = now_utc()
            cooldown_min = float(get_cfg("crypto", "coinbase_probe_min_minutes_between_trades", default=60))
            last = self._last_probe_at.get(symbol)
            if last is not None:
                age_min = (now - last).total_seconds() / 60.0
                if age_min < cooldown_min:
                    logger.info(
                        f"SCAN {symbol} probe | cooldown {age_min:.1f}m < {cooldown_min:.1f}m — skipped"
                    )
                    return None

            bid = float(quote.bid)
            ask = float(quote.ask)
            mid = float(quote.mid)

            if bid <= 0 or ask <= 0 or mid <= 0:
                logger.info(f"SCAN {symbol} probe | invalid quote bid={bid} ask={ask} mid={mid} — skipped")
                return None

            spread_pct_val = ((ask - bid) / mid) * 100.0
            max_spread = float(get_cfg("crypto", "coinbase_probe_max_spread_pct", default=0.10))
            if spread_pct_val > max_spread:
                logger.info(
                    f"SCAN {symbol} probe | spread={spread_pct_val:.3f}% > max={max_spread:.3f}% — skipped"
                )
                return None

            probe_notional = float(get_cfg("crypto", "coinbase_probe_notional_usd", default=0.50))
            min_notional = float(get_cfg("crypto", "min_trade_notional_usd", default=0.50))
            max_trade = float(get_cfg("crypto", "max_trade_notional_usd", default=2.0))
            bp_buffer = float(get_cfg("crypto", "coinbase_probe_buying_power_buffer", default=0.80))

            available = max(0.0, float(buying_power or 0.0) * bp_buffer)
            notional = min(probe_notional, max_trade, available)

            if notional < min_notional:
                logger.info(
                    f"SCAN {symbol} probe | notional=${notional:.2f} < min=${min_notional:.2f} "
                    f"bp=${float(buying_power or 0):.2f} — skipped"
                )
                return None

            row = df.iloc[-1]
            rsi = float(row.get("rsi_14", 50))
            mom5 = float(row.get("mom_5", 0))

            # Basic no-falling-knife check. Still permissive enough to create movement.
            if rsi < 35 or rsi > 72:
                logger.info(f"SCAN {symbol} probe | rsi={rsi:.1f} outside 35-72 — skipped")
                return None

            if mom5 < -0.010:
                logger.info(f"SCAN {symbol} probe | mom5={mom5:.4f} too negative — skipped")
                return None

            sl_pct = float(get_cfg("crypto", "coinbase_probe_stop_loss_pct", default=1.50)) / 100.0
            tp_pct = float(get_cfg("crypto", "coinbase_probe_take_profit_pct", default=3.25)) / 100.0

            # Passive-style buy limit. Not guaranteed maker-only unless broker/order layer
            # supports post_only, but avoids intentionally crossing at ask.
            limit_price = bid

            confidence = 0.50
            if 42 <= rsi <= 62:
                confidence += 0.05
            if mom5 >= 0:
                confidence += 0.05
            if spread_pct_val <= max_spread * 0.5:
                confidence += 0.05

            logger.info(
                f"SIGNAL coinbase_probe {symbol} | regime={regime} "
                f"notional=${notional:.2f} limit={limit_price:.8f} "
                f"conf={confidence:.2f} spread={spread_pct_val:.3f}% rsi={rsi:.1f}"
            )

            self._last_probe_at[symbol] = now

            return TradeProposal(
                symbol=symbol,
                asset_class="crypto",
                strategy="coinbase_probe",
                side="buy",
                order_type="limit",
                notional=notional,
                limit_price=limit_price,
                confidence=confidence,
                bid=quote.bid,
                ask=quote.ask,
                price=quote.mid,
                quote_time=quote.timestamp,
                stop_loss_price=quote.mid * (1 - sl_pct),
                take_profit_price=quote.mid * (1 + tp_pct),
                meta={
                    "regime": regime,
                    "probe": True,
                    "rsi": rsi,
                    "mom_5": mom5,
                    "spread_pct": spread_pct_val,
                    "cooldown_min": cooldown_min,
                },
            )
        except Exception as e:
            logger.error(f"{symbol} coinbase_probe error: {e}")
            return None

    def _momentum_breakout(
        self,
        symbol: str,
        quote: Quote,
        df: pd.DataFrame,
        prefer_no_trade: bool,
        buying_power: float | None,
        lookback: int,
        regime: str,
    ) -> Optional[TradeProposal]:
        """
        Signal: price closes above the N-bar high (current candle excluded)
        with above-average volume, EMA9 > EMA21, and RSI not overbought.

        Entry: passive limit at best bid (maker-side to target 0.15% fee).
        Exit:  ATR-based dynamic stop and target.
        """
        try:
            row = df.iloc[-1]

            # Breakout high: explicitly exclude current candle
            recent_high = float(df["h"].iloc[-(lookback + 1):-1].max())
            recent_low = float(df["l"].iloc[-(lookback + 1):-1].min())
            current_close = float(row["c"])
            rel_vol = float(row.get("rel_volume", 0))
            avg_volume = float(row.get("vol_sma_10", 0))
            ema9 = float(row.get("ema_9", current_close))
            ema21 = float(row.get("ema_21", current_close))
            rsi = float(row.get("rsi_14", 50))
            atr_pct = float(row.get("atr_pct", 0))

            # Core conditions
            breakout = current_close > recent_high
            vol_confirm = rel_vol > 1.2 and avg_volume > 0
            trend_confirm = ema9 > ema21
            not_overbought = rsi < 80

            failed = []
            if not breakout:
                failed.append(f"no_breakout(close={current_close:.2f} vs high={recent_high:.2f})")
            if not vol_confirm:
                failed.append(f"low_vol(rel={rel_vol:.2f}<1.2 or avg={avg_volume:.0f})")
            if not trend_confirm:
                failed.append(f"bearish_trend(ema9={ema9:.2f}<ema21={ema21:.2f})")
            if not not_overbought:
                failed.append(f"overbought(rsi={rsi:.1f}>=80)")
            if failed:
                logger.info(
                    f"SCAN {symbol} momentum | regime={regime} | "
                    f"close={current_close:.2f} high{lookback}={recent_high:.2f} "
                    f"rsi={rsi:.1f} rel_vol={rel_vol:.2f} | BLOCKED: {', '.join(failed)}"
                )
                return None

            logger.info(
                f"SCAN {symbol} momentum | regime={regime} | "
                f"close={current_close:.2f} high{lookback}={recent_high:.2f} "
                f"rsi={rsi:.1f} rel_vol={rel_vol:.2f} ema9>ema21 | "
                f"ALL CONDITIONS MET — scoring confidence"
            )

            # Confidence scoring
            confidence = 0.25  # base: confirmed breakout above closed-bar high
            if rel_vol > 1.5:
                confidence += 0.20
            elif rel_vol > 1.2:
                confidence += 0.10
            if trend_confirm:
                confidence += 0.20
            if 50 < rsi < 75:
                confidence += 0.15
            if row.get("mom_5", 0) > 0:
                confidence += 0.10
            if row.get("bb_pct_b", 0.5) > 0.6:
                confidence += 0.10
            # Proportional bonus for breakout distance
            breakout_dist = (current_close - recent_high) / recent_high if recent_high > 0 else 0
            confidence += min(0.10, breakout_dist / 0.005 * 0.10)
            confidence = min(confidence, 1.0)

            min_conf = get_cfg(
                "strategy_thresholds", "confidence_threshold",
                default={}
            ).get("momentum_breakout",
                  get_cfg("strategy", "min_confidence_score", default=0.70))
            if prefer_no_trade and confidence < min_conf:
                logger.info(
                    f"SCAN {symbol} momentum | conf={confidence:.2f} < min {min_conf} — SKIPPED"
                )
                return None

            notional = self._compute_notional(buying_power)
            if notional is None:
                logger.info(
                    f"SCAN {symbol} momentum | BLOCKED: notional below minimum "
                    f"(buying_power={buying_power})"
                )
                return None

            # Passive limit entry at best bid (targets maker fee 0.15%)
            entry_price = quote.bid if quote.bid > 0 else quote.mid
            spread_pct_val = calc_spread(quote.bid, quote.ask)

            stop_price, target_price, stop_pct, tp_pct = self._build_dynamic_exit(
                entry_price, atr_pct, spread_pct_val, "momentum_breakout"
            )
            fee_m = self._fee_meta(spread_pct_val, tp_pct, stop_pct)

            logger.info(
                f"SIGNAL momentum_breakout {symbol} | regime={regime} | "
                f"conf={confidence:.2f} notional=${notional:.2f} | "
                f"rsi={rsi:.1f} rel_vol={rel_vol:.2f} atr={atr_pct*100:.2f}% | "
                f"entry={entry_price:.4f} sl={stop_price:.4f}(-{stop_pct:.2f}%) "
                f"tp={target_price:.4f}(+{tp_pct:.2f}%) r:r={fee_m['reward_risk_ratio']:.2f} | "
                f"net_edge={fee_m['net_expected_edge_pct']:.2f}% "
                f"worst={fee_m['worst_case_edge_pct']:.2f}%"
            )

            return TradeProposal(
                symbol=symbol,
                asset_class="crypto",
                strategy="momentum_breakout",
                side="buy",
                order_type="limit",
                notional=notional,
                limit_price=entry_price,
                confidence=confidence,
                bid=quote.bid,
                ask=quote.ask,
                price=quote.mid,
                quote_time=quote.timestamp,
                stop_loss_price=stop_price,
                take_profit_price=target_price,
                meta={
                    "regime": regime,
                    "rsi": rsi,
                    "rel_vol": rel_vol,
                    "recent_high": recent_high,
                    "recent_low": recent_low,
                    "atr_pct": atr_pct,
                    "stop_pct": stop_pct,
                    "target_pct": tp_pct,
                    "spread_pct": spread_pct_val,
                    **fee_m,
                },
            )

        except Exception as e:
            logger.error(f"{symbol} momentum_breakout error: {e}")
            return None

    # -----------------------------------------------------------------------
    # Strategy 2: Mean Reversion
    # -----------------------------------------------------------------------

    def _mean_reversion(
        self,
        symbol: str,
        quote: Quote,
        df: pd.DataFrame,
        prefer_no_trade: bool,
        buying_power: float | None,
        regime: str,
    ) -> Optional[TradeProposal]:
        """
        Signal: RSI < 35 + price at/below lower Bollinger Band + bullish reversal bar
        (current close > open AND current close > previous close).
        Not traded in strong downtrends.

        Entry: passive limit at best bid.
        Target: fee-aware; max(BB mid-band, minimum to clear all costs).
        """
        try:
            row = df.iloc[-1]
            prev_row = df.iloc[-2] if len(df) >= 2 else row

            current_close = float(row["c"])
            current_open = float(row["o"])
            prev_close = float(prev_row["c"])
            rsi = float(row.get("rsi_14", 50))
            bb_pct_b = float(row.get("bb_pct_b", 0.5))
            bb_lower = float(row.get("bb_lower", 0))
            bb_mid = float(row.get("bb_mid", current_close))
            ema9 = float(row.get("ema_9", current_close))
            ema21 = float(row.get("ema_21", current_close))
            atr_pct = float(row.get("atr_pct", 0))

            oversold = rsi < 35
            at_lower_band = bb_pct_b < 0.15
            # Require actual bullish reversal evidence on the current bar
            bullish_bar = current_close > current_open and current_close > prev_close

            mr_failed = []
            if not oversold:
                mr_failed.append(f"rsi_not_oversold({rsi:.1f}>=35)")
            if not at_lower_band:
                mr_failed.append(f"not_at_lower_band(bb_pct_b={bb_pct_b:.2f}>=0.15)")
            if not bullish_bar:
                mr_failed.append(
                    f"no_reversal_bar(close={current_close:.4f} open={current_open:.4f} "
                    f"prev_close={prev_close:.4f})"
                )
            if mr_failed:
                logger.info(
                    f"SCAN {symbol} mean_rev | regime={regime} | "
                    f"rsi={rsi:.1f} bb_pct_b={bb_pct_b:.2f} | "
                    f"BLOCKED: {', '.join(mr_failed)}"
                )
                return None

            # Don't trade mean reversion in a strong downtrend
            if ema9 < ema21 * 0.98:
                logger.info(
                    f"SCAN {symbol} mean_rev | regime={regime} | "
                    f"BLOCKED: strong_downtrend(ema9={ema9:.2f} < ema21={ema21:.2f}*0.98)"
                )
                return None

            confidence = 0.30  # base: oversold + lower band + bullish bar
            if rsi < 25:
                confidence += 0.20
            elif rsi < 30:
                confidence += 0.10
            if bb_pct_b < 0.05:
                confidence += 0.15
            if abs(ema9 - ema21) / ema21 < 0.005:
                confidence += 0.10  # EMAs converging
            # Stronger bullish bar (close near high of bar)
            bar_range = float(row.get("h", current_close)) - float(row.get("l", current_close))
            if bar_range > 0:
                close_position = (current_close - float(row.get("l", current_close))) / bar_range
                if close_position > 0.7:
                    confidence += 0.10
            confidence = min(confidence, 1.0)

            min_conf = get_cfg(
                "strategy_thresholds", "confidence_threshold",
                default={}
            ).get("mean_reversion",
                  get_cfg("strategy", "min_confidence_score", default=0.72))
            if prefer_no_trade and confidence < min_conf:
                logger.info(
                    f"SCAN {symbol} mean_rev | conf={confidence:.2f} < min {min_conf} — SKIPPED"
                )
                return None

            notional = self._compute_notional(buying_power)
            if notional is None:
                logger.info(
                    f"SCAN {symbol} mean_rev | BLOCKED: notional below minimum "
                    f"(buying_power={buying_power})"
                )
                return None

            entry_price = quote.bid if quote.bid > 0 else quote.mid
            spread_pct_val = calc_spread(quote.bid, quote.ask)

            stop_price, target_price, stop_pct, tp_pct = self._build_dynamic_exit(
                entry_price, atr_pct, spread_pct_val, "mean_reversion"
            )

            # Override target with BB mid-band if it gives a better reward
            maker_fee = get_cfg("fees", "maker_fee_pct", default=0.0015)
            taker_fee = get_cfg("fees", "taker_fee_pct", default=0.0025)
            slippage = get_cfg("crypto", "slippage_estimate_pct", default=0.05)
            req_edge = get_cfg("fees", "require_expected_edge_pct", default=0.006) * 100.0
            min_target_pct = taker_fee * 2 * 100.0 + spread_pct_val + slippage + req_edge

            if bb_mid > entry_price:
                bb_target_pct = (bb_mid - entry_price) / entry_price * 100.0
                if bb_target_pct > tp_pct:
                    tp_pct = bb_target_pct
                    target_price = entry_price * (1 + tp_pct / 100.0)

            # Ensure minimum is met even after BB override
            tp_pct = max(tp_pct, min_target_pct)
            target_price = entry_price * (1 + tp_pct / 100.0)

            fee_m = self._fee_meta(spread_pct_val, tp_pct, stop_pct)

            logger.info(
                f"SIGNAL mean_reversion {symbol} | regime={regime} | "
                f"conf={confidence:.2f} notional=${notional:.2f} | "
                f"rsi={rsi:.1f} bb_pct_b={bb_pct_b:.2f} atr={atr_pct*100:.2f}% | "
                f"entry={entry_price:.4f} sl={stop_price:.4f}(-{stop_pct:.2f}%) "
                f"tp={target_price:.4f}(+{tp_pct:.2f}%) r:r={fee_m['reward_risk_ratio']:.2f} | "
                f"net_edge={fee_m['net_expected_edge_pct']:.2f}% "
                f"worst={fee_m['worst_case_edge_pct']:.2f}%"
            )

            return TradeProposal(
                symbol=symbol,
                asset_class="crypto",
                strategy="mean_reversion",
                side="buy",
                order_type="limit",
                notional=notional,
                limit_price=entry_price,
                confidence=confidence,
                bid=quote.bid,
                ask=quote.ask,
                price=quote.mid,
                quote_time=quote.timestamp,
                stop_loss_price=stop_price,
                take_profit_price=target_price,
                meta={
                    "regime": regime,
                    "rsi": rsi,
                    "bb_pct_b": bb_pct_b,
                    "bb_lower": bb_lower,
                    "bb_mid": bb_mid,
                    "atr_pct": atr_pct,
                    "stop_pct": stop_pct,
                    "target_pct": tp_pct,
                    "spread_pct": spread_pct_val,
                    **fee_m,
                },
            )

        except Exception as e:
            logger.error(f"{symbol} mean_reversion error: {e}")
            return None

    # -----------------------------------------------------------------------
    # Strategy 3: EMA Crossover
    # -----------------------------------------------------------------------

    def _ema_crossover(
        self,
        symbol: str,
        quote: Quote,
        df: pd.DataFrame,
        prefer_no_trade: bool,
        buying_power: float | None,
        regime: str,
    ) -> Optional[TradeProposal]:
        """
        Signal: EMA9 freshly crosses above EMA21 (previous bar: EMA9 <= EMA21)
        with meaningful separation, RSI in healthy zone (40-72), and price above SMA20.

        Entry: passive limit at best bid.
        Exit:  ATR-based dynamic stop and target.
        """
        try:
            if len(df) < 3:
                return None

            row = df.iloc[-1]
            prev = df.iloc[-2]

            ema9 = float(row.get("ema_9", 0))
            ema21 = float(row.get("ema_21", 0))
            prev_ema9 = float(prev.get("ema_9", 0))
            prev_ema21 = float(prev.get("ema_21", 0))

            if ema9 == 0 or ema21 == 0 or prev_ema9 == 0 or prev_ema21 == 0:
                return None

            rsi = float(row.get("rsi_14", 50))
            sma20 = float(row.get("sma_20", 0))
            current_close = float(row["c"])
            mom_5 = float(row.get("mom_5", 0))
            atr_pct = float(row.get("atr_pct", 0))

            # Fresh crossover: prior bar EMA9 below EMA21, current bar above
            crossed_above = (prev_ema9 <= prev_ema21) and (ema9 > ema21)

            ema_sep_pct = (ema9 - ema21) / ema21 * 100.0 if ema21 > 0 else 0.0
            meaningful_sep = ema_sep_pct > 0.05
            rsi_ok = 40 < rsi < 72
            above_sma20 = (sma20 > 0) and (current_close > sma20)

            failed = []
            if not crossed_above:
                failed.append(
                    f"no_fresh_cross(prev_ema9{'>'if prev_ema9>prev_ema21 else '<='}prev_ema21 "
                    f"cur_ema9{'>'if ema9>ema21 else '<='}ema21)"
                )
            if not meaningful_sep:
                failed.append(f"thin_sep(sep={ema_sep_pct:.3f}%<0.05%)")
            if not rsi_ok:
                failed.append(f"rsi_out_of_range({rsi:.1f})")

            if failed:
                logger.info(
                    f"SCAN {symbol} ema_crossover | regime={regime} | "
                    f"sep={ema_sep_pct:.3f}% rsi={rsi:.1f} | "
                    f"BLOCKED: {', '.join(failed)}"
                )
                return None

            logger.info(
                f"SCAN {symbol} ema_crossover | regime={regime} | "
                f"sep={ema_sep_pct:.3f}% rsi={rsi:.1f} above_sma20={above_sma20} | "
                f"ALL CONDITIONS MET — scoring confidence"
            )

            # Confidence scoring
            confidence = 0.30  # base: fresh crossover
            if rsi_ok:
                confidence += 0.15
            if above_sma20:
                confidence += 0.15
            if mom_5 > 0:
                confidence += 0.10
            if ema_sep_pct > 0.15:
                confidence += 0.15
            elif ema_sep_pct > 0.05:
                confidence += 0.08
            if 50 < rsi < 65:
                confidence += 0.08
            confidence = min(confidence, 1.0)

            min_conf = get_cfg(
                "strategy_thresholds", "confidence_threshold",
                default={}
            ).get("ema_crossover",
                  get_cfg("strategy", "min_confidence_score", default=0.68))
            if prefer_no_trade and confidence < min_conf:
                logger.info(
                    f"SCAN {symbol} ema_crossover | conf={confidence:.2f} < min {min_conf} — SKIPPED"
                )
                return None

            notional = self._compute_notional(buying_power)
            if notional is None:
                logger.info(
                    f"SCAN {symbol} ema_crossover | BLOCKED: notional below minimum "
                    f"(buying_power={buying_power})"
                )
                return None

            entry_price = quote.bid if quote.bid > 0 else quote.mid
            spread_pct_val = calc_spread(quote.bid, quote.ask)

            stop_price, target_price, stop_pct, tp_pct = self._build_dynamic_exit(
                entry_price, atr_pct, spread_pct_val, "ema_crossover"
            )
            fee_m = self._fee_meta(spread_pct_val, tp_pct, stop_pct)

            logger.info(
                f"SIGNAL ema_crossover {symbol} | regime={regime} | "
                f"conf={confidence:.2f} notional=${notional:.2f} | "
                f"rsi={rsi:.1f} sep={ema_sep_pct:.3f}% atr={atr_pct*100:.2f}% | "
                f"entry={entry_price:.4f} sl={stop_price:.4f}(-{stop_pct:.2f}%) "
                f"tp={target_price:.4f}(+{tp_pct:.2f}%) r:r={fee_m['reward_risk_ratio']:.2f} | "
                f"net_edge={fee_m['net_expected_edge_pct']:.2f}% "
                f"worst={fee_m['worst_case_edge_pct']:.2f}%"
            )

            return TradeProposal(
                symbol=symbol,
                asset_class="crypto",
                strategy="ema_crossover",
                side="buy",
                order_type="limit",
                notional=notional,
                limit_price=entry_price,
                confidence=confidence,
                bid=quote.bid,
                ask=quote.ask,
                price=quote.mid,
                quote_time=quote.timestamp,
                stop_loss_price=stop_price,
                take_profit_price=target_price,
                meta={
                    "regime": regime,
                    "rsi": rsi,
                    "ema9": ema9,
                    "ema21": ema21,
                    "ema_sep_pct": ema_sep_pct,
                    "above_sma20": above_sma20,
                    "atr_pct": atr_pct,
                    "stop_pct": stop_pct,
                    "target_pct": tp_pct,
                    "spread_pct": spread_pct_val,
                    **fee_m,
                },
            )

        except Exception as e:
            logger.error(f"{symbol} ema_crossover error: {e}")
            return None
