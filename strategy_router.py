"""
strategy_router.py — Routes market scanning to the appropriate strategy modules.

The router:
  1. Iterates over configured symbols per asset class
  2. Calls the relevant strategy module to generate proposals
  3. Returns proposals to main.py — it does NOT place orders
  4. Logs when a module is skipped due to permissions/config

The router has no access to order_manager.
It only produces TradeProposal objects.
"""

from __future__ import annotations

import logging
from typing import Optional

from market_data import MarketData
from permissions import AccountPermissions
from risk_manager import TradeProposal
from strategy_crypto import CryptoStrategy
from strategy_equities import EquitiesStrategy
from strategy_options import OptionsStrategy
from strategy_shorts import ShortsStrategy
from utils import get_cfg, get_mode

logger = logging.getLogger("strategy_router")


class StrategyRouter:
    def __init__(self, broker, market_data: MarketData) -> None:
        self._broker = broker
        self._md = market_data

        # Strategy modules — instantiated once, reused every scan cycle
        self._crypto = CryptoStrategy(market_data)
        self._equities = EquitiesStrategy(market_data)
        self._options = OptionsStrategy(market_data, broker)
        self._shorts = ShortsStrategy(market_data, broker)

    def scan(
        self,
        permissions: AccountPermissions,
        buying_power: float | None = None,
    ) -> list[TradeProposal]:
        """
        Scan all configured symbols and return all valid proposals.
        The caller (main.py) will pass each proposal through the risk manager.

        buying_power — live account buying power from the last permissions refresh.
        Forwarded into crypto strategy so notional is capped at actual available cash.

        Proposals are returned in priority order:
          crypto first (primary live asset class), then equities, then shorts.
        Options are currently skipped (no live proposals for $10 account).
        """
        all_proposals: list[TradeProposal] = []
        mode = get_mode()
        bp = buying_power if buying_power is not None else permissions.buying_power

        # ── Crypto ─────────────────────────────────────────────────────────
        if get_cfg("crypto", "enabled", default=True):
            # live_symbols: generate proposals; watch_only_symbols: scan only (no proposals)
            live_syms = get_cfg("crypto", "live_symbols", default=[])
            watch_only = set(get_cfg("crypto", "watch_only_symbols", default=[]))

            # Fall back to full symbol list if live_symbols not configured
            if not live_syms:
                all_syms = get_cfg("crypto", "symbols", default=[])
                live_syms = [s for s in all_syms if s not in watch_only]

            if watch_only:
                logger.debug(
                    f"Crypto watch-only (no live proposals): {sorted(watch_only)}"
                )

            # P2-012E: controlled multi-asset spot expansion (reads same config as status via shared get_cfg)
            multi_cfg = get_cfg("crypto", "multi_asset_spot", default={"enabled": False})
            if multi_cfg.get("enabled"):
                try:
                    from coinbase_market_universe import CoinbaseMarketUniverse
                    u = CoinbaseMarketUniverse()
                    # product_payload optional; runtime now has fallback for allowlisted configured spot symbols
                    effective, rpt = u.resolve_live_crypto_symbols(live_syms, multi_cfg)
                    if effective != live_syms:
                        logger.info(
                            f"P2-012E multi-asset spot expansion active: {len(effective)} symbols "
                            f"(base {len(live_syms)} + {rpt.get('selected_new_count', 0)} new from allowlist+filters)"
                        )
                        logger.info(f"  effective live scan symbols: {effective}")
                        if rpt.get("newly_selected"):
                            logger.info(f"  newly selected this cycle: {rpt['newly_selected']}")
                    else:
                        logger.info("P2-012E multi-asset spot enabled but no additional symbols passed allowlist+filters (or no metadata + no fallback match)")
                    if rpt.get("excluded"):
                        logger.info(f"Multi-asset excluded this cycle: {len(rpt['excluded'])} (sample reasons: {rpt.get('excluded_reasons', [])[:4]})")
                    live_syms = effective
                except Exception as e:
                    logger.warning(f"P2-012E multi-asset resolution error (non-fatal, using base live_symbols): {e}")
            else:
                logger.debug("Multi-asset spot expansion disabled (crypto.multi_asset_spot.enabled=false). Only base live_symbols used.")

            for symbol in live_syms:
                try:
                    proposals = self._crypto.generate_proposals(symbol, buying_power=bp)
                    if proposals:
                        logger.debug(f"Crypto {symbol}: {len(proposals)} proposal(s)")
                    all_proposals.extend(proposals)
                except Exception as e:
                    logger.error(f"CryptoStrategy error for {symbol}: {e}")
        else:
            logger.debug("Crypto strategy disabled in config")

        # ── Equities ───────────────────────────────────────────────────────
        if get_cfg("equities", "enabled", default=True):
            symbols = get_cfg("equities", "symbols", default=[])
            for symbol in symbols:
                try:
                    proposals = self._equities.generate_proposals(symbol)
                    if proposals:
                        logger.debug(f"Equity {symbol}: {len(proposals)} proposal(s)")
                    all_proposals.extend(proposals)
                except Exception as e:
                    logger.error(f"EquitiesStrategy error for {symbol}: {e}")
        else:
            logger.debug("Equities strategy disabled in config")

        # ── Options (gated behind approval) ────────────────────────────────
        if get_cfg("options", "enabled", default=True) and permissions.options_enabled:
            symbols = get_cfg("equities", "symbols", default=[])  # options on equity symbols
            for symbol in symbols:
                try:
                    proposals = self._options.generate_proposals(symbol, permissions)
                    all_proposals.extend(proposals)
                except Exception as e:
                    logger.error(f"OptionsStrategy error for {symbol}: {e}")
        else:
            logger.debug("Options skipped: not enabled or no broker approval")

        # ── Short selling (gated behind $2k equity) ─────────────────────────
        if (
            get_cfg("short_selling", "enabled", default=True)
            and permissions.short_selling_enabled
            and permissions.equity >= 2000.0
        ):
            symbols = get_cfg("equities", "symbols", default=[])
            for symbol in symbols:
                try:
                    proposals = self._shorts.generate_proposals(symbol, permissions)
                    all_proposals.extend(proposals)
                except Exception as e:
                    logger.error(f"ShortsStrategy error for {symbol}: {e}")
        else:
            logger.debug(
                f"Shorts skipped: enabled={get_cfg('short_selling','enabled',default=True)} "
                f"short_selling_enabled={permissions.short_selling_enabled} "
                f"equity=${permissions.equity:.2f}"
            )

        logger.info(
            f"Strategy scan complete: {len(all_proposals)} proposal(s) across all asset classes"
        )
        return all_proposals
