import pytes
from datetime import datetime, timezone
import pandas as pd
from unittest.mock import MagicMock, patch

from risk_manager import RiskManager, TradeProposal, AccountState
from strategy_crypto import CryptoStrategy
from market_data import MarketData, Quote
from profit_thesis_ev_contract import ProfitThesisDecision, ProfitThesisStatus, profit_thesis_to_dic

@pytest.fixture
def crypto_strategy():
    md = MagicMock(spec=MarketData)
    return CryptoStrategy(market_data=md)

@pytest.fixture
def risk_manager():
    rm = RiskManager()
    rm._c = MagicMock(return_value=0.0) # avoid config crashes during isolated tests
    return rm

# ---------------------------------------------------------
# 1. Strategy EV Gate Constraint Tests
# ---------------------------------------------------------

def test_strategy_ev_gate_rejects_missing_entry_price(crypto_strategy):
    quote = Quote(symbol="BTC/USD", bid=100000, ask=100010, mid=100005, spread_pct=0.01, timestamp=datetime.now(timezone.utc), is_stale=False)
    p = TradeProposal(
        symbol="BTC/USD", asset_class="crypto", strategy="momentum_breakout",
        side="buy", order_type="limit", notional=10, limit_price=0, price=0,
        take_profit_price=105000, stop_loss_price=95000, confidence=1.0
    )
    result = crypto_strategy._enforce_ev_gate(p, quote, "uptrend")
    assert result is None

def test_strategy_ev_gate_rejects_missing_take_profit(crypto_strategy):
    quote = Quote(symbol="BTC/USD", bid=100000, ask=100010, mid=100005, spread_pct=0.01, timestamp=datetime.now(timezone.utc), is_stale=False)
    p = TradeProposal(
        symbol="BTC/USD", asset_class="crypto", strategy="momentum_breakout",
        side="buy", order_type="limit", notional=10, limit_price=100000,
        take_profit_price=0, stop_loss_price=95000, confidence=1.0
    )
    result = crypto_strategy._enforce_ev_gate(p, quote, "uptrend")
    assert result is None

@patch("strategy_crypto.get_cfg")
def test_strategy_ev_gate_rejects_negative_net_ev(mock_get_cfg, crypto_strategy):
    # Enforce heavy costs so a 1% move fails EV
    def mock_cfg(section, key, default=None):
        if key == "taker_fee_pct": return 0.05  # 5% fee!
        if key == "slippage_estimate_pct": return 0.05
        return defaul
    mock_get_cfg.side_effect = mock_cfg

    quote = Quote(symbol="BTC/USD", bid=100000, ask=100010, mid=100005, spread_pct=0.01, timestamp=datetime.now(timezone.utc), is_stale=False)
    p = TradeProposal(
        symbol="BTC/USD", asset_class="crypto", strategy="momentum_breakout",
        side="buy", order_type="limit", notional=10, limit_price=100000,
        take_profit_price=101000, stop_loss_price=99000, confidence=1.0
    )
    # Expected move is 1%, fee is 10% round trip. Should reject.
    result = crypto_strategy._enforce_ev_gate(p, quote, "uptrend")
    assert result is None

@patch("strategy_crypto.get_cfg")
def test_strategy_ev_gate_approves_positive_net_ev_and_attaches_meta(mock_get_cfg, crypto_strategy):
    def mock_cfg(section, key, default=None):
        if key == "taker_fee_pct": return 0.0025
        if key == "slippage_estimate_pct": return 0.05
        return defaul
    mock_get_cfg.side_effect = mock_cfg

    quote = Quote(symbol="BTC/USD", bid=100000, ask=100010, mid=100005, spread_pct=0.01, timestamp=datetime.now(timezone.utc), is_stale=False)
    p = TradeProposal(
        symbol="BTC/USD", asset_class="crypto", strategy="momentum_breakout",
        side="buy", order_type="limit", notional=10, limit_price=100000,
        take_profit_price=105000, stop_loss_price=99000, confidence=1.0
    )
    # Expected move 5%, costs approx 0.5% + spread + slippage + hurdle. Should pass.
    result = crypto_strategy._enforce_ev_gate(p, quote, "uptrend")

    assert result is not None
    assert getattr(result, "meta", None) is not None
    assert "profit_thesis" in result.meta
    assert result.meta["profit_thesis"]["status"] == "APPROVED"

# ---------------------------------------------------------
# 2. Risk Manager Gate Enforcement Tests
# ---------------------------------------------------------

def test_risk_manager_blocks_missing_metadata(risk_manager):
    p = TradeProposal(
        symbol="BTC/USD", asset_class="crypto", strategy="momentum",
        side="buy", order_type="limit", notional=10
    )
    s = AccountState()
    allowed, reason = risk_manager._check_profit_thesis_ev_gate(p, s, "live")
    assert allowed is False
    assert "lacks profit_thesis metadata" in reason

def test_risk_manager_blocks_rejected_metadata(risk_manager):
    p = TradeProposal(
        symbol="BTC/USD", asset_class="crypto", strategy="momentum",
        side="buy", order_type="limit", notional=10,
        meta={"profit_thesis": {"status": "REJECTED", "reject_reasons": ["INSUFFICIENT_EDGE"]}}
    )
    s = AccountState()
    allowed, reason = risk_manager._check_profit_thesis_ev_gate(p, s, "live")
    assert allowed is False
    assert "INSUFFICIENT_EDGE" in reason

def test_risk_manager_allows_approved_metadata(risk_manager):
    p = TradeProposal(
        symbol="BTC/USD", asset_class="crypto", strategy="momentum",
        side="buy", order_type="limit", notional=10,
        meta={"profit_thesis": {"status": "APPROVED"}}
    )
    s = AccountState()
    allowed, reason = risk_manager._check_profit_thesis_ev_gate(p, s, "live")
    assert allowed is True

def test_risk_manager_ignores_non_crypto(risk_manager):
    p = TradeProposal(
        symbol="AAPL", asset_class="equity", strategy="momentum",
        side="buy", order_type="limit", notional=10
    )
    s = AccountState()
    allowed, reason = risk_manager._check_profit_thesis_ev_gate(p, s, "live")
    assert allowed is True

# ---------------------------------------------------------
# 3. Path Wiring Tests
# ---------------------------------------------------------

@patch.object(CryptoStrategy, '_enforce_ev_gate')
def test_generate_proposals_gates_exploration(mock_enforce, crypto_strategy):
    df = pd.DataFrame({"o": [1]*100, "h": [1]*100, "l": [1]*100, "c": [1]*100, "v": [1]*100, "ema_9": [1]*100, "ema_21": [1]*100, "atr_pct": [0.0]*100, "bb_upper": [1]*100, "bb_lower": [1]*100, "bb_mid": [1]*100})
    df.index = pd.date_range("2026-01-01", periods=100)
    quote = Quote(symbol="BTC/USD", bid=100000, ask=100010, mid=100005, spread_pct=0.01, timestamp=datetime.now(timezone.utc), is_stale=False)

    crypto_strategy._md.get_crypto_quote.return_value = quote
    crypto_strategy._md.get_crypto_bars_df.return_value = df

    # Force strategy logic down exploration fallback path
    p = TradeProposal(symbol="BTC/USD", asset_class="crypto", strategy="coinbase_exploration", side="buy", order_type="limit", notional=1)
    crypto_strategy._coinbase_exploration = MagicMock(return_value=p)

    mock_enforce.return_value = p
    crypto_strategy.generate_proposals("BTC/USD", 10.0)

    mock_enforce.assert_called_once()
    assert mock_enforce.call_args[0][0].strategy == "coinbase_exploration"

@patch.object(CryptoStrategy, '_enforce_ev_gate')
def test_generate_proposals_gates_probe(mock_enforce, crypto_strategy):
    df = pd.DataFrame({"o": [1]*100, "h": [1]*100, "l": [1]*100, "c": [1]*100, "v": [1]*100, "ema_9": [1]*100, "ema_21": [1]*100, "atr_pct": [0.0]*100, "bb_upper": [1]*100, "bb_lower": [1]*100, "bb_mid": [1]*100})
    df.index = pd.date_range("2026-01-01", periods=100)
    quote = Quote(symbol="BTC/USD", bid=100000, ask=100010, mid=100005, spread_pct=0.01, timestamp=datetime.now(timezone.utc), is_stale=False)

    crypto_strategy._md.get_crypto_quote.return_value = quote
    crypto_strategy._md.get_crypto_bars_df.return_value = df

    # Force down probe fallback path
    crypto_strategy._coinbase_exploration = MagicMock(return_value=None)
    p = TradeProposal(symbol="BTC/USD", asset_class="crypto", strategy="coinbase_probe", side="buy", order_type="limit", notional=1)
    crypto_strategy._coinbase_probe = MagicMock(return_value=p)

    mock_enforce.return_value = p
    crypto_strategy.generate_proposals("BTC/USD", 10.0)

    mock_enforce.assert_called_once()
    assert mock_enforce.call_args[0][0].strategy == "coinbase_probe"

@patch.object(CryptoStrategy, '_enforce_ev_gate')
@patch("strategy_crypto.classify_regime")
def test_generate_proposals_gates_standard(mock_classify, mock_enforce, crypto_strategy):
    mock_classify.return_value = "uptrend"
    df = pd.DataFrame({"o": [1]*100, "h": [1]*100, "l": [1]*100, "c": [1]*100, "v": [1]*100})
    df.index = pd.date_range("2026-01-01", periods=100)
    quote = Quote(symbol="BTC/USD", bid=100000, ask=100010, mid=100005, spread_pct=0.01, timestamp=datetime.now(timezone.utc), is_stale=False)

    crypto_strategy._md.get_crypto_quote.return_value = quote
    crypto_strategy._md.get_crypto_bars_df.return_value = df

    # Standard path via momentum_breakou
    p = TradeProposal(symbol="BTC/USD", asset_class="crypto", strategy="momentum_breakout", side="buy", order_type="limit", notional=1)
    crypto_strategy._momentum_breakout = MagicMock(return_value=p)
    crypto_strategy._ema_crossover = MagicMock(return_value=None)

    mock_enforce.return_value = p
    crypto_strategy.generate_proposals("BTC/USD", 10.0)

    mock_enforce.assert_called_once()
    assert mock_enforce.call_args[0][0].strategy == "momentum_breakout"

# ---------------------------------------------------------
# 4. Status Serialization Integrity Tes
# ---------------------------------------------------------

def test_status_serialization():
    decision = ProfitThesisDecision(
        status=ProfitThesisStatus.APPROVED,
        reject_reasons=[],
        thesis=None
    )
    d = profit_thesis_to_dict(decision)
    # Proves the Risk Manager `thesis_dict.get("status") == "APPROVED"` check is exac
    assert d["status"] == "APPROVED"
