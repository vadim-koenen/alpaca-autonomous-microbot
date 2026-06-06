"""Jesse strategy port of the current crypto rules."""
# This is a stub strategy for the bake-off.
# Real implementation would follow Jesse's class structure.

class JesseCryptoStrategy:
    def __init__(self):
        self.rsi_period = 14
        self.rsi_oversold = 35
        self.bb_period = 20
        self.bb_std = 2
        self.bb_lower_band_pct = 0.15
        self.max_hold_minutes = 90
        self.stop_loss_pct = 1.5
        self.take_profit_pct = 3.0

    def should_long(self, candles) -> bool:
        # RSI < 35 AND Price < BB Lower Band
        return False

    def should_cancel_long(self, candles) -> bool:
        return False
