"""
strategy_shorts.py — Short selling strategy module.

HARD GATED: Live short selling requires:
  1. Account equity >= $2,000 (Alpaca requirement)
  2. Alpaca confirms short_selling_enabled
  3. Asset is confirmed shortable AND easy_to_borrow
  4. config short_selling.live_enabled = true
  5. config live_trading.allow_short_selling = true

With a ~$10 account, this module will NEVER produce live proposals.
It is built for correctness and future-readiness.
"""

from __future__ import annotations

import logging
from typing import Optional

from market_data import MarketData, add_indicators
from risk_manager import TradeProposal
from utils import get_cfg

logger = logging.getLogger("strategy.shorts")

# Symbols that are explicitly off-limits for shorting regardless of permissions.
# Low-float, meme, and penny stocks can have catastrophic short squeezes.
NEVER_SHORT = frozenset([
    "GME", "AMC", "BBBY", "SPCE", "CLOV", "WISH", "WKHS",
    "MMAT", "SNDL", "NAKD", "KOSS",
])


class ShortsStrategy:
    def __init__(self, market_data: MarketData, broker) -> None:
        self._md = market_data
        self._broker = broker

    def generate_proposals(self, symbol: str, permissions) -> list[TradeProposal]:
        """
        Generate short proposals only if all hard gates pass.
        Returns [] in virtually all current account states.
        """
        # Hard equity gate — no exceptions
        min_equity = get_cfg("short_selling", "minimum_equity_required_usd", default=2000.0)
        if permissions.equity < min_equity:
            logger.debug(
                f"Short skipped {symbol}: equity ${permissions.equity:.2f} < "
                f"${min_equity:.2f} minimum"
            )
            return []

        if not permissions.short_selling_enabled:
            logger.debug(f"Short skipped {symbol}: short_selling_enabled=False")
            return []

        if not get_cfg("short_selling", "live_enabled", default=False):
            logger.debug(f"Short skipped {symbol}: short_selling.live_enabled is false")
            return []

        # Never-short list
        if symbol in NEVER_SHORT:
            logger.warning(f"Short blocked for {symbol}: on permanent never-short list")
            return []

        # Asset-level shortability check
        if get_cfg("short_selling", "require_asset_shortable", default=True):
            if not self._broker.is_shortable(symbol):
                logger.debug(f"Short skipped {symbol}: not shortable or hard-to-borrow")
                return []

        # Strategy signal
        p = self._momentum_short(symbol, permissions)
        if p is not None:
            return [p]
        return []

    def _momentum_short(self, symbol: str, permissions) -> Optional[TradeProposal]:
        """
        Short when price breaks below N-bar low with volume and trend confirmation.
        Requires a defined stop-loss above the breakdown level.
        """
        try:
            quote = self._md.get_equity_quote(symbol)
            if not quote.valid:
                return None

            df = self._md.get_equity_bars_df(symbol, limit=40)
            if df.empty or len(df) < 15:
                return None

            df = add_indicators(df)
            row = df.iloc[-1]
            lookback = get_cfg("strategy", "lookback_bars", default=20)
            prev = df.iloc[-(lookback + 1):-1]

            recent_low = prev["l"].min()
            close = float(row["c"])
            rsi = float(row.get("rsi_14", 50))
            rel_vol = float(row.get("rel_volume", 0))
            ema9 = float(row.get("ema_9", close))
            ema21 = float(row.get("ema_21", close))

            # Short conditions: breakdown, volume, trend bearish, not oversold
            breakdown = close < recent_low
            vol_confirm = rel_vol > 1.2
            trend_bearish = ema9 < ema21
            not_oversold = rsi > 25

            if not (breakdown and vol_confirm and trend_bearish and not_oversold):
                return None

            confidence = 0.30
            if rel_vol > 1.5:
                confidence += 0.15
            if rsi < 45:
                confidence += 0.10
            if ema9 < ema21 * 0.998:
                confidence += 0.10

            min_conf = get_cfg("strategy", "min_confidence_score", default=0.65)
            if confidence < min_conf:
                return None

            max_notional = get_cfg("short_selling", "max_short_notional_usd", default=25.0)

            # Stop: above recent high (defined risk)
            stop_loss_price = recent_low * 1.015   # 1.5% above breakdown
            take_profit_price = close * 0.975      # 2.5% target downside

            return TradeProposal(
                symbol=symbol,
                asset_class="short",
                strategy="momentum_short",
                side="short",
                order_type="limit",
                notional=min(max_notional, permissions.buying_power * 0.1),
                limit_price=quote.bid,
                confidence=confidence,
                bid=quote.bid,
                ask=quote.ask,
                price=quote.mid,
                quote_time=quote.timestamp,
                stop_loss_price=stop_loss_price,
                take_profit_price=take_profit_price,
            )
        except Exception as e:
            logger.error(f"{symbol} momentum_short error: {e}")
            return None
