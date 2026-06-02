"""
risk_manager.py — Authoritative, deterministic risk layer.

The risk manager CANNOT be bypassed. Every trade proposal must pass
all checks before an order is submitted. If any single check fails,
the trade is rejected with a logged reason.

Design contract:
  check(proposal, state) -> (allowed: bool, reason: str)

The strategy layer may only propose. This layer decides.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from coinbase_fee_aware_pilot import (
    DEFAULT_ABSOLUTE_HARD_TRADE_CAP_USD,
    DEFAULT_ALLOWED_SYMBOLS,
    DEFAULT_EXCLUDED_SYMBOLS,
    DEFAULT_MIN_TRADE_NOTIONAL_USD,
    decimal_or_none,
    resolve_balance_relative_pilot_sizing,
)
from utils import (
    data_is_stale,
    get_cfg,
    get_mode,
    is_live_trading_enabled,
    now_local,
    now_utc,
    safe_float,
    spread_pct as calc_spread_pct,
)

logger = logging.getLogger("risk_manager")


# ---------------------------------------------------------------------------
# Trade proposal — passed from strategy to risk manager
# ---------------------------------------------------------------------------

@dataclass
class TradeProposal:
    symbol: str
    asset_class: str           # "crypto" | "equity" | "option" | "short"
    strategy: str
    side: str                  # "buy" | "sell" | "short" | "cover"
    order_type: str            # "limit" | "market"
    notional: float            # USD notional requested
    qty: float = 0.0           # alternative to notional; 0 = use notional
    limit_price: float = 0.0
    confidence: float = 0.0    # 0..1 from strategy
    bid: float = 0.0
    ask: float = 0.0
    price: float = 0.0         # mid or last
    quote_time: Optional[datetime] = None  # UTC datetime of the quote
    stop_loss_price: float = 0.0
    take_profit_price: float = 0.0
    options_strategy: str = ""  # e.g. "long_call"
    meta: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Account state — snapshot passed alongside the proposal
# ---------------------------------------------------------------------------

@dataclass
class AccountState:
    equity: float = 0.0
    buying_power: float = 0.0
    open_positions: int = 0
    open_position_symbols: list[str] = field(default_factory=list)
    open_orders: int = 0
    open_order_symbols: list[str] = field(default_factory=list)
    daily_realized_pnl: float = 0.0   # negative = loss
    daily_trade_count: int = 0
    consecutive_losses: int = 0
    crypto_enabled: bool = False
    options_enabled: bool = False
    options_level: int = 0
    margin_enabled: bool = False
    short_selling_enabled: bool = False
    account_blocked: bool = False
    trading_blocked: bool = False
    api_error_count: int = 0
    # Total USD notional of ALL tracked crypto positions (bot-placed + recovered).
    # Populated from session.open_positions in main.py so the exposure guard
    # can block new entries when recovered positions eat into the cap.
    tracked_crypto_exposure_usd: float = 0.0
    # Breakdown: how much of the above is broker_recovered (consumer wallet,
    # not API-controllable) vs bot-placed (strategy-opened, API-controllable).
    # Used for structured ENTRY_BLOCKED logging so the user can see exactly
    # which portion is blocking new entries.
    broker_recovered_crypto_exposure_usd: float = 0.0
    # Manual-review/non-controllable crypto positions block new entries even
    # when exposure remains below cap. These are populated from local state.
    manual_review_crypto_position_count: int = 0
    non_controllable_crypto_position_count: int = 0
    # Non-crypto aggregate exposure guard. Main populates these from broker
    # positions, open/pending orders, and recovered/tracked state before every
    # risk check. Unknown exposure fails closed.
    aggregate_exposure_known: bool = True
    current_equity_position_exposure_usd: Optional[float] = 0.0
    pending_equity_order_exposure_usd: Optional[float] = 0.0
    recovered_equity_position_exposure_usd: Optional[float] = 0.0


# ---------------------------------------------------------------------------
# Risk manager
# ---------------------------------------------------------------------------

class RiskManager:
    def __init__(self) -> None:
        self._cfg = {}  # lazy-loaded

    def _c(self, *keys, default=None):
        return get_cfg(*keys, default=default)

    def check(
        self, proposal: TradeProposal, state: AccountState
    ) -> tuple[bool, str]:
        """
        Run all checks. Return (True, "ok") or (False, "reason").
        Checks are ordered from cheapest/most-likely-to-fail first.
        """
        mode = get_mode()
        checks = [
            # Fundamental eligibility — always check these first regardless of time
            self._check_account_health,
            self._check_live_trading_gate,
            self._check_equity_floor,
            self._check_asset_class_permitted,
            self._check_asset_live_permitted,
            self._check_short_specific,        # equity gate before time gate
            self._check_margin_specific,       # equity gate before time gate
            self._check_options_specific,      # broker approval before time gate
            self._check_crypto_specific,
            self._check_controlled_fee_aware_pilot,
            self._check_crypto_manual_review_gate,
            self._check_total_crypto_exposure,
            # Session limits
            self._check_daily_loss_limit,
            self._check_consecutive_losses,
            self._check_daily_trade_count,
            self._check_api_error_rate,
            self._check_no_new_trades_after_time,
            self._check_data_freshness,
            self._check_spread,
            self._check_duplicate_position,
            self._check_duplicate_order,
            self._check_max_open_positions,
            self._check_max_exposure,
            self._check_notional_bounds,
            self._check_buying_power,
            self._check_fee_hurdle,
            self._check_worst_case_edge,
            self._check_reward_risk,
            self._check_order_type,
            self._check_exit_plan,
            self._check_confidence,
        ]

        for fn in checks:
            allowed, reason = fn(proposal, state, mode)
            if not allowed:
                logger.debug(f"RISK BLOCK [{fn.__name__}]: {proposal.symbol} — {reason}")
                return False, reason

        return True, "ok"

    # -----------------------------------------------------------------------
    # Individual checks
    # -----------------------------------------------------------------------

    def _check_account_health(self, p, s, mode):
        if s.account_blocked:
            return False, "account is blocked by broker"
        if s.trading_blocked:
            return False, "trading is blocked by broker"
        return True, ""

    def _check_live_trading_gate(self, p, s, mode):
        if mode == "live":
            # Must have env flag
            if not is_live_trading_enabled():
                return False, "LIVE_TRADING env var is not true — master kill switch active"
            # Must have config flag
            if not self._c("live_trading", "enabled", default=False):
                return False, "live_trading.enabled is false in config"
        return True, ""

    def _check_equity_floor(self, p, s, mode):
        if mode == "live":
            floor = self._c("account", "disable_live_below_equity", default=7.0)
            if s.equity < floor:
                return False, f"equity ${s.equity:.2f} < floor ${floor:.2f} — live trading disabled"
        return True, ""

    def _check_daily_loss_limit(self, p, s, mode):
        max_loss = self._c("global_risk", "max_daily_loss_usd", default=2.0)
        if s.daily_realized_pnl <= -abs(max_loss):
            return False, f"daily loss limit hit: ${s.daily_realized_pnl:.2f}"
        return True, ""

    def _check_consecutive_losses(self, p, s, mode):
        limit = self._c("global_risk", "stop_after_consecutive_losses", default=2)
        if s.consecutive_losses >= limit:
            return False, f"consecutive loss limit hit: {s.consecutive_losses}"
        return True, ""

    def _check_daily_trade_count(self, p, s, mode):
        max_trades = self._c("global_risk", "max_trades_per_day", default=5)
        if s.daily_trade_count >= max_trades:
            return False, f"max trades/day reached: {s.daily_trade_count}/{max_trades}"
        return True, ""

    def _check_api_error_rate(self, p, s, mode):
        max_errors = self._c("global_risk", "max_api_errors_before_halt", default=10)
        if s.api_error_count >= max_errors:
            return False, f"API error count {s.api_error_count} >= halt threshold {max_errors}"
        return True, ""

    def _check_no_new_trades_after_time(self, p, s, mode):
        # Only applies to non-crypto (crypto is 24/7)
        if p.asset_class == "crypto":
            return True, ""
        cutoff_str = self._c("global_risk", "no_new_trades_after_market_time", default="14:45")
        try:
            local = now_local()
            h, m = map(int, cutoff_str.split(":"))
            cutoff = local.replace(hour=h, minute=m, second=0, microsecond=0)
            if local >= cutoff:
                return False, f"no new equity trades after {cutoff_str} (local time)"
        except Exception:
            pass
        return True, ""

    def _check_asset_class_permitted(self, p, s, mode):
        ac = p.asset_class.lower()
        if ac == "crypto":
            if not s.crypto_enabled:
                return False, "crypto not enabled by broker for this account"
        elif ac == "option":
            if not s.options_enabled:
                return False, "options not enabled by broker for this account"
        elif ac == "short":
            if not s.short_selling_enabled:
                return False, "short selling not enabled by broker for this account"
        elif ac == "equity":
            pass  # equities always gated by live_enabled in config
        else:
            return False, f"unknown asset class: {ac}"
        return True, ""

    def _check_asset_live_permitted(self, p, s, mode):
        if mode not in ("live",):
            return True, ""
        ac = p.asset_class.lower()
        if ac == "crypto":
            if not self._c("live_trading", "allow_crypto", default=False):
                return False, "live crypto not permitted in config"
            if not self._c("crypto", "live_enabled", default=False):
                return False, "crypto.live_enabled is false in config"
        elif ac == "equity":
            if not self._c("live_trading", "allow_equities", default=False):
                return False, "live equities not permitted in config"
            if not self._c("equities", "live_enabled", default=False):
                return False, "equities.live_enabled is false in config"
        elif ac == "option":
            if not self._c("live_trading", "allow_long_options", default=False):
                return False, "live options not permitted in config"
            if not self._c("options", "live_enabled", default=False):
                return False, "options.live_enabled is false in config"
        elif ac == "short":
            if not self._c("live_trading", "allow_short_selling", default=False):
                return False, "live short selling not permitted in config"
            if not self._c("short_selling", "live_enabled", default=False):
                return False, "short_selling.live_enabled is false in config"
        return True, ""

    def _check_crypto_specific(self, p, s, mode):
        if p.asset_class != "crypto":
            return True, ""
        allowed_symbols = self._c("crypto", "symbols", default=[])
        if p.symbol not in allowed_symbols:
            return False, f"{p.symbol} not in allowed crypto symbols list"
        return True, ""

    def _check_controlled_fee_aware_pilot(self, p, s, mode):
        if p.asset_class != "crypto":
            return True, ""
        if not self._c("crypto", "controlled_fee_aware_pilot_enabled", default=False):
            return True, ""

        allowed_symbols = set(self._c(
            "crypto",
            "fee_aware_pilot_symbols",
            default=list(DEFAULT_ALLOWED_SYMBOLS),
        ) or DEFAULT_ALLOWED_SYMBOLS)
        excluded_symbols = set(self._c(
            "crypto",
            "fee_aware_pilot_excluded_symbols",
            default=list(DEFAULT_EXCLUDED_SYMBOLS),
        ) or DEFAULT_EXCLUDED_SYMBOLS)
        max_trade = decimal_or_none(self._c(
            "crypto",
            "max_trade_notional_usd",
            default=str(DEFAULT_ABSOLUTE_HARD_TRADE_CAP_USD),
        )) or DEFAULT_ABSOLUTE_HARD_TRADE_CAP_USD
        absolute_cap = decimal_or_none(self._c(
            "crypto",
            "absolute_hard_trade_cap_usd",
            default=str(DEFAULT_ABSOLUTE_HARD_TRADE_CAP_USD),
        )) or DEFAULT_ABSOLUTE_HARD_TRADE_CAP_USD
        min_trade = decimal_or_none(self._c(
            "crypto",
            "min_trade_notional_usd",
            default=str(DEFAULT_MIN_TRADE_NOTIONAL_USD),
        )) or DEFAULT_MIN_TRADE_NOTIONAL_USD
        pilot_cap = min(max_trade, absolute_cap, DEFAULT_ABSOLUTE_HARD_TRADE_CAP_USD)

        if p.symbol in excluded_symbols:
            return False, "sol_external_staked_inventory_excluded"
        if p.symbol not in allowed_symbols:
            return False, f"{p.symbol} not in controlled fee-aware pilot symbols"
        if p.notional > float(pilot_cap):
            return False, f"notional ${p.notional:.2f} exceeds controlled pilot cap ${float(pilot_cap):.2f}"
        if p.notional < float(min_trade):
            return False, f"1usd_micro_trades_disabled; controlled pilot requires ${float(min_trade):.2f} minimum notional"

        sizing = resolve_balance_relative_pilot_sizing(
            equity=s.equity,
            buying_power=s.buying_power,
            pilot_trade_percent_of_balance=self._c(
                "crypto",
                "pilot_trade_percent_of_balance",
                default=0.10,
            ),
            min_trade_notional_usd=min_trade,
            max_trade_notional_usd=max_trade,
            absolute_hard_trade_cap_usd=absolute_cap,
            balance_basis=self._c(
                "crypto",
                "balance_basis",
                default="buying_power_then_equity",
            ),
        )
        if sizing.get("verdict") == "SIZING_PREVIEW_OK":
            resolved_notional = decimal_or_none(sizing.get("final_trade_notional"))
            if resolved_notional is not None and p.notional > float(resolved_notional):
                return (
                    False,
                    f"notional ${p.notional:.2f} exceeds balance-relative pilot size ${float(resolved_notional):.2f}",
                )
        elif s.equity > 0 or s.buying_power > 0:
            return False, str(sizing.get("reason", "balance_relative_sizing_blocked"))

        if self._c("crypto", "fee_drag_guard_enabled", default=True):
            expected = decimal_or_none(p.meta.get("fee_drag_expected_gross_move_rate"))
            required = decimal_or_none(p.meta.get("fee_drag_required_gross_move_rate"))
            if expected is None or required is None:
                return False, "fee_drag_expected_edge_missing"
            if expected <= required:
                return False, "fee_drag_expected_edge_too_small"

        return True, ""

    def _check_total_crypto_exposure(self, p, s, mode):
        """
        Block new crypto entries when total tracked exposure (bot-placed +
        broker-recovered) already meets or exceeds the configured cap.

        This ensures recovered consumer-wallet positions (ALGO, ETH held
        outside Advanced Trade) count toward the cap and prevent new trades
        from pushing total exposure above the limit.
        """
        if p.asset_class != "crypto":
            return True, ""
        cap = self._c("crypto", "max_total_crypto_exposure_usd", default=8.0)
        current = s.tracked_crypto_exposure_usd
        recovered = s.broker_recovered_crypto_exposure_usd
        bot_placed = current - recovered
        if current >= cap:
            action = (
                "Transfer broker-recovered position(s) from consumer wallet "
                "to Advanced Trade, or manually clear state after user approval."
                if recovered > 0
                else "Close or reduce bot-placed positions to free exposure."
            )
            logger.warning(
                f"ENTRY_BLOCKED strategy={p.strategy} symbol={p.symbol} "
                f"reason=exposure_cap_exceeded\n"
                f"  requested_notional          = ${p.notional:.4f}\n"
                f"  bot_placed_exposure         = ${bot_placed:.4f}\n"
                f"  external_untradeable_exp    = ${recovered:.4f}  "
                f"← broker_recovered (consumer wallet)\n"
                f"  total_counted_exposure      = ${current:.4f}\n"
                f"  crypto_exposure_cap         = ${cap:.2f}  "
                f"[crypto.max_total_crypto_exposure_usd]\n"
                f"  projected_if_allowed        = ${current + p.notional:.4f}\n"
                f"  action_required             = {action}"
            )
            return False, (
                f"total crypto exposure ${current:.4f} >= cap ${cap:.2f} "
                f"(${recovered:.4f} external/untradeable; ${bot_placed:.4f} bot-placed)"
            )
        return True, ""

    def _check_crypto_manual_review_gate(self, p, s, mode):
        """
        Block unattended Coinbase crypto entries while any tracked crypto
        position still needs manual review or cannot be safely exited.
        """
        if p.asset_class != "crypto":
            return True, ""

        manual_count = int(s.manual_review_crypto_position_count or 0)
        non_controllable_count = int(s.non_controllable_crypto_position_count or 0)

        if manual_count > 0:
            logger.warning(
                f"ENTRY_BLOCKED reason=manual_review_position_open "
                f"strategy={p.strategy} symbol={p.symbol} "
                f"manual_review_open_count={manual_count} "
                f"non_controllable_open_count={non_controllable_count}"
            )
            return False, "ENTRY_BLOCKED reason=manual_review_position_open"

        if non_controllable_count > 0:
            logger.warning(
                f"ENTRY_BLOCKED reason=non_controllable_position_open "
                f"strategy={p.strategy} symbol={p.symbol} "
                f"manual_review_open_count={manual_count} "
                f"non_controllable_open_count={non_controllable_count}"
            )
            return False, "ENTRY_BLOCKED reason=non_controllable_position_open"

        return True, ""

    def _check_options_specific(self, p, s, mode):
        if p.asset_class != "option":
            return True, ""
        # Must have broker approval
        if self._c("options", "require_broker_options_approval", default=True):
            if not s.options_enabled:
                return False, "options require broker approval — not approved"
        # No disallowed strategies
        disallowed = self._c("options", "disallowed_strategies", default=[])
        if p.options_strategy in disallowed:
            return False, f"options strategy '{p.options_strategy}' is disallowed"
        # Must be in allowed live strategies
        if mode == "live":
            allowed = self._c("options", "allowed_live_strategies", default=[])
            if p.options_strategy not in allowed:
                return False, f"options strategy '{p.options_strategy}' not in allowed live list"
        # Premium bounds
        max_premium = self._c("options", "max_premium_per_trade_usd", default=5.0)
        if p.notional > max_premium:
            return False, f"options premium ${p.notional:.2f} > max ${max_premium:.2f}"
        return True, ""

    def _check_short_specific(self, p, s, mode):
        if p.asset_class != "short" and p.side != "short":
            return True, ""
        min_equity = self._c("short_selling", "minimum_equity_required_usd", default=2000.0)
        if s.equity < min_equity:
            return False, (
                f"short selling requires equity ${min_equity:.2f}, "
                f"current ${s.equity:.2f}"
            )
        if not s.short_selling_enabled:
            return False, "short selling not enabled by broker"
        return True, ""

    def _check_margin_specific(self, p, s, mode):
        # Margin is implicit in short selling; this catches explicit margin trades
        if p.asset_class != "margin":
            return True, ""
        min_equity = self._c("margin", "minimum_equity_required_usd", default=2000.0)
        if s.equity < min_equity:
            return False, (
                f"margin requires equity ${min_equity:.2f}, current ${s.equity:.2f}"
            )
        if not s.margin_enabled:
            return False, "margin not enabled by broker"
        return True, ""

    def _check_data_freshness(self, p, s, mode):
        if p.quote_time is None:
            return False, "quote_time is None — no market data"
        ac = p.asset_class.lower()
        if ac == "crypto":
            max_sec = self._c("crypto", "stale_data_seconds", default=15)
        else:
            max_sec = self._c("equities", "stale_data_seconds", default=15)
        if data_is_stale(p.quote_time, max_sec):
            age = (now_utc() - p.quote_time).total_seconds() if p.quote_time else 9999
            return False, f"stale data: quote is {age:.0f}s old (max {max_sec}s)"
        return True, ""

    def _check_spread(self, p, s, mode):
        if p.bid <= 0 or p.ask <= 0:
            return False, f"invalid bid/ask: bid={p.bid} ask={p.ask}"
        sp = calc_spread_pct(p.bid, p.ask)
        ac = p.asset_class.lower()
        if ac == "crypto":
            # Check per-symbol limit first, then fall back to global crypto limit
            per_sym = self._c("crypto", "max_spread_pct_per_symbol", default={})
            if isinstance(per_sym, dict) and p.symbol in per_sym:
                max_sp = per_sym[p.symbol]
            else:
                max_sp = self._c("crypto", "max_spread_pct", default=0.35)
        else:
            max_sp = self._c("equities", "max_spread_pct", default=0.25)
        if sp > max_sp:
            return False, f"spread {sp:.3f}% > max {max_sp:.3f}% for {p.symbol}"
        return True, ""

    def _check_duplicate_position(self, p, s, mode):
        if p.symbol in s.open_position_symbols:
            return False, f"already have open position in {p.symbol}"
        return True, ""

    def _check_duplicate_order(self, p, s, mode):
        if p.symbol in s.open_order_symbols:
            return False, f"already have open order for {p.symbol}"
        return True, ""

    def _check_max_open_positions(self, p, s, mode):
        max_pos = self._c("global_risk", "max_open_positions", default=3)
        if s.open_positions >= max_pos:
            return False, f"max open positions {max_pos} reached"
        return True, ""

    def _check_max_exposure(self, p, s, mode):
        max_exp = self._c("global_risk", "max_total_live_exposure_usd", default=8.0)
        if p.asset_class in ("equity", "option", "short"):
            parts = (
                s.current_equity_position_exposure_usd,
                s.pending_equity_order_exposure_usd,
                s.recovered_equity_position_exposure_usd,
            )
            if not s.aggregate_exposure_known or any(v is None for v in parts):
                return False, "ENTRY_BLOCKED reason=aggregate_exposure_unknown"

            current = safe_float(s.current_equity_position_exposure_usd)
            pending = safe_float(s.pending_equity_order_exposure_usd)
            recovered = safe_float(s.recovered_equity_position_exposure_usd)
            counted = current + pending + recovered
            projected = counted + p.notional
            if projected > max_exp:
                return False, (
                    "ENTRY_BLOCKED reason=global_exposure_cap_exceeded "
                    f"current=${current:.2f} pending=${pending:.2f} "
                    f"recovered=${recovered:.2f} proposed=${p.notional:.2f} "
                    f"projected=${projected:.2f} cap=${max_exp:.2f}"
                )

            return True, ""

        # Crypto keeps its crypto-specific aggregate guard above; this fallback
        # preserves the historical per-proposal global cap behavior.
        if p.notional > max_exp:
            return False, f"notional ${p.notional:.2f} exceeds max exposure ${max_exp:.2f}"
        return True, ""

    def _check_notional_bounds(self, p, s, mode):
        ac = p.asset_class.lower()
        if ac == "crypto":
            max_n = self._c("crypto", "max_trade_notional_usd", default=3.0)
            min_n = self._c("crypto", "min_trade_notional_usd", default=1.0)
        elif ac == "option":
            max_n = self._c("options", "max_premium_per_trade_usd", default=5.0)
            min_n = 0.01
        else:
            max_n = self._c("equities", "max_trade_notional_usd", default=3.0)
            min_n = self._c("equities", "min_trade_notional_usd", default=1.0)
        if p.notional < min_n:
            return False, f"notional ${p.notional:.2f} < min ${min_n:.2f}"
        if p.notional > max_n:
            return False, f"notional ${p.notional:.2f} > max ${max_n:.2f}"
        return True, ""

    def _check_buying_power(self, p, s, mode):
        """
        Reject if notional exceeds available buying power.
        Applies a safety buffer so we don't attempt to spend every last cent.
        The strategy already pre-sized with the buffer; this is a belt-and-suspenders
        check using the live buying_power from the current account snapshot.
        """
        buf = self._c("crypto", "buying_power_safety_buffer", default=0.85)
        safe_bp = s.buying_power * buf if p.asset_class == "crypto" else s.buying_power
        if p.notional > safe_bp:
            return False, (
                f"insufficient buying power (with {buf*100:.0f}% buffer): "
                f"need ${p.notional:.2f}, safe_bp=${safe_bp:.2f} "
                f"(raw_bp=${s.buying_power:.2f})"
            )
        return True, ""

    def _check_fee_hurdle(self, p, s, mode):
        """
        Reject if the strategy's own fee-aware edge estimate is negative.

        The strategy attaches net_expected_edge_pct to proposal.meta when it
        computes fee metadata.  We only block if the field is present AND
        negative — so strategies that don't compute fee metadata still pass.

        This keeps a tight guard without requiring every strategy to implement
        fee awareness before the check can exist.
        """
        if p.asset_class != "crypto":
            return True, ""   # only crypto uses this metadata right now

        net_edge = p.meta.get("net_expected_edge_pct")
        if net_edge is None:
            return True, ""   # metadata absent — don't block, just log

        # require_expected_edge_pct stored as decimal (0.006 = 0.6%); convert to %
        min_net_edge = self._c("fees", "require_expected_edge_pct", default=0.006) * 100.0
        if net_edge <= min_net_edge:
            rt_fee = safe_float(p.meta.get("round_trip_fee_pct", 0))
            sp = safe_float(p.meta.get("spread_cost_pct", 0))
            exp = safe_float(p.meta.get("expected_edge_pct", 0))
            return False, (
                f"fee hurdle not met: net_edge={net_edge:.2f}% "
                f"(expected={exp:.2f}% - fees={rt_fee:.2f}% - spread={sp:.2f}%) "
                f"<= min {min_net_edge:.2f}%"
            )
        return True, ""

    def _check_order_type(self, p, s, mode):
        ac = p.asset_class.lower()
        if p.order_type == "market":
            if ac == "crypto" and not self._c("crypto", "allow_market_orders", default=False):
                return False, "market orders not allowed for crypto (config)"
        if p.order_type == "limit" and p.limit_price <= 0:
            return False, "limit order requested but limit_price <= 0"
        return True, ""

    def _check_exit_plan(self, p, s, mode):
        """Both stop-loss AND take-profit are required. Validate price ordering."""
        if p.side not in ("buy", "short"):
            return True, ""
        require_stop = self._c("risk", "require_stop_loss", default=True)
        require_tp = self._c("risk", "require_take_profit", default=True)
        if require_stop and p.stop_loss_price <= 0:
            return False, "no exit plan: stop_loss_price is required but not set"
        if require_tp and p.take_profit_price <= 0:
            return False, "no exit plan: take_profit_price is required but not set"
        # Validate directional ordering when entry price is known
        entry = p.price if p.price > 0 else p.limit_price
        if entry > 0 and p.side == "buy":
            if p.stop_loss_price > 0 and p.stop_loss_price >= entry:
                return False, (
                    f"invalid exit plan: stop_loss {p.stop_loss_price:.4f} "
                    f">= entry {entry:.4f}"
                )
            if p.take_profit_price > 0 and p.take_profit_price <= entry:
                return False, (
                    f"invalid exit plan: take_profit {p.take_profit_price:.4f} "
                    f"<= entry {entry:.4f}"
                )
        return True, ""

    def _check_reward_risk(self, p, s, mode):
        """Reject proposals whose reward:risk ratio is below the configured minimum."""
        if p.asset_class != "crypto":
            return True, ""
        rr = p.meta.get("reward_risk_ratio")
        if rr is None:
            return True, ""  # non-blocking when strategy doesn't provide it
        min_rr = self._c("risk", "min_reward_risk_ratio", default=1.4)
        if rr < min_rr:
            return False, f"reward/risk {rr:.2f} < minimum {min_rr:.2f}"
        return True, ""

    def _check_worst_case_edge(self, p, s, mode):
        """Reject proposals that lose money even under best-case (maker) fee assumptions."""
        if p.asset_class != "crypto":
            return True, ""
        wce = p.meta.get("worst_case_edge_pct")
        if wce is None:
            return True, ""  # non-blocking when strategy doesn't provide it
        require = self._c("fees", "require_worst_case_edge_positive", default=True)
        if require and wce <= 0.0:
            return False, f"worst-case edge is negative ({wce:.3f}%) — taker fees wipe the trade"
        return True, ""

    def _check_confidence(self, p, s, mode):
        # Confidence gate.
        #
        # Prefer per-strategy thresholds when configured:
        #   strategy_thresholds:
        #     confidence_threshold:
        #       coinbase_probe: 0.60
        #
        # Fall back to the global strategy.min_confidence_score for all
        # normal strategies. This keeps the main Coinbase strategies strict
        # while allowing explicitly opt-in probe mode to use its own floor.
        default_min_conf = float(self._c("strategy", "min_confidence_score", default=0.65))
        min_conf = default_min_conf

        try:
            thresholds = self._c("strategy_thresholds", "confidence_threshold", default={}) or {}
            if isinstance(thresholds, dict) and p.strategy in thresholds:
                min_conf = float(thresholds[p.strategy])
        except Exception:
            min_conf = default_min_conf

        if p.confidence < min_conf:
            return False, f"confidence {p.confidence:.2f} < min {min_conf:.2f}"
        return True, ""
