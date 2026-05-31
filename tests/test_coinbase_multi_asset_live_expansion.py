"""
P2-012C tests for opt-in micro-size multi-asset Coinbase spot live expansion.

Covers:
- default (disabled) keeps exactly the current 3 symbols, zero behavior change
- enabled + explicit allowlist adds only safe spot symbols
- allowlist is required and respected (nothing outside it is ever returned for live)
- perps/futures/gold/silver/commodity/linked/leverage/disabled/bad-quote are never live-enabled
- high spread / other filters respected
- expanded symbols still emit prediction telemetry (via the resolver)
- notional/exposure/TP/SL/hold-time caps are not increased by the new config section
- no references to append_coinbase_fill_row or coinbase_fills.csv
- ACTIVE_HANDOFF.md untouched (enforced at test time via git diff)
"""

import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from coinbase_market_universe import CoinbaseMarketUniverse
from utils import get_cfg


def _mixed_payload():
    return [
        {"product_id": "BTC-USD", "base_currency": "BTC", "quote_currency": "USD", "product_type": "spot", "status": "online"},
        {"product_id": "ETH-USD", "base_currency": "ETH", "quote_currency": "USD", "product_type": "spot"},
        {"product_id": "SOL-USD", "base_currency": "SOL", "quote_currency": "USD", "product_type": "spot"},
        {"product_id": "ADA-USD", "base_currency": "ADA", "quote_currency": "USD", "product_type": "spot"},
        {"product_id": "AVAX-USD", "base_currency": "AVAX", "quote_currency": "USD", "product_type": "spot"},
        {"product_id": "BTC-PERP", "base_currency": "BTC", "quote_currency": "USD", "contract_type": "perpetual"},
        {"product_id": "GOLD-PERP", "base_currency": "GOLD", "quote_currency": "USD", "contract_type": "perpetual"},
        {"product_id": "SILVER-PERP", "base_currency": "SILVER", "quote_currency": "USD"},
        {"product_id": "XAU-USD", "base_currency": "XAU", "quote_currency": "USD"},
        {"product_id": "DISABLED-USD", "base_currency": "XXX", "quote_currency": "USD", "trading_disabled": True},
        {"product_id": "LEVERAGED-USD", "base_currency": "FOO", "quote_currency": "USD", "leverage_enabled": True, "max_leverage": 3},
    ]


def test_default_disabled_returns_exactly_current_live_symbols_and_no_change():
    """Default behavior (the critical safety invariant)."""
    u = CoinbaseMarketUniverse()
    u.ingest_products(_mixed_payload())

    base = ["BTC/USD", "ETH/USD", "SOL/USD"]
    multi_cfg = {"enabled": False}

    effective, report = u.resolve_live_crypto_symbols(base, multi_cfg)

    assert effective == base, "disabled must return exactly the input live_symbols"
    assert report["mode"] == "disabled"
    assert report["selected_new_count"] == 0
    assert "BTC/ETH/SOL behavior 100% unchanged" in report.get("note", "")


def test_enabled_with_allowlist_adds_only_safe_spot_and_respects_allowlist():
    u = CoinbaseMarketUniverse()
    u.ingest_products(_mixed_payload())

    base = ["BTC/USD", "ETH/USD", "SOL/USD"]
    multi_cfg = {
        "enabled": True,
        "max_symbols": 6,
        "allowed_quote_currencies": ["USD", "USDC"],
        "exclude_product_types": ["perpetual_future", "expiring_future", "commodity_linked_derivative", "unknown"],
        "max_spread_bps": 50,
        "allow_live_trading_symbols": ["ADA/USD", "AVAX/USD"],  # explicit
        "max_new_symbols_per_day": 2,
    }

    effective, report = u.resolve_live_crypto_symbols(base, multi_cfg)

    eff_norm = {s.replace("/", "-").upper() for s in effective}
    assert eff_norm >= {"BTC-USD", "ETH-USD", "SOL-USD", "ADA-USD", "AVAX-USD"}
    for bad in ["BTC-PERP", "GOLD-PERP", "SILVER-PERP", "XAU-USD", "DISABLED-USD", "LEVERAGED-USD"]:
        assert bad.replace("/", "-").upper() not in eff_norm

    assert report["mode"] == "enabled"
    new_norm = {s.replace("/", "-").upper() for s in report.get("newly_selected", [])}
    assert new_norm == {"ADA-USD", "AVAX-USD"}
    assert report["selected_new_count"] <= 2


def test_allowlist_is_required_nothing_gets_through_without_it():
    u = CoinbaseMarketUniverse()
    u.ingest_products(_mixed_payload())

    base = ["BTC/USD", "ETH/USD", "SOL/USD"]
    multi_cfg = {
        "enabled": True,
        "allow_live_trading_symbols": [],  # empty — nothing new allowed
    }

    effective, report = u.resolve_live_crypto_symbols(base, multi_cfg)

    assert effective == base
    assert report["selected_new_count"] == 0
    # the good candidates (ADA etc) should be excluded because not allowlisted
    reasons = [e.get("reason", "") for e in report.get("excluded", [])]
    assert "not_in_explicit_allowlist_excluded" in reasons


def test_hard_filters_never_let_perps_gold_silver_leverage_through_even_if_allowlisted():
    u = CoinbaseMarketUniverse()
    u.ingest_products(_mixed_payload())

    base = ["BTC/USD"]
    # malicious allowlist that tries to sneak bad products
    multi_cfg = {
        "enabled": True,
        "allow_live_trading_symbols": ["BTC-PERP", "GOLD-PERP", "XAU-USD", "LEVERAGED-USD", "DISABLED-USD"],
    }

    effective, report = u.resolve_live_crypto_symbols(base, multi_cfg)

    eff_norm = {s.replace("/", "-").upper() for s in effective}
    for bad in ["BTC-PERP", "GOLD-PERP", "XAU-USD", "LEVERAGED-USD", "DISABLED-USD"]:
        assert bad.replace("/", "-").upper() not in eff_norm

    # they must appear in excluded with the exact preferred deterministic reasons
    reasons = {e.get("reason", "") for e in report.get("excluded", [])}
    assert "derivative_or_perpetual_excluded" in reasons
    assert "commodity_linked_or_gold_silver_excluded" in reasons
    assert "leverage_or_margin_excluded" in reasons
    assert "trading_disabled_excluded" in reasons


def test_expanded_symbols_still_emit_prediction_telemetry(tmp_path, monkeypatch):
    """P2-012C resolver must emit telemetry rows (candidate or skipped)."""
    out = tmp_path / "pred.jsonl"
    monkeypatch.setattr("prediction_telemetry.TELEMETRY_FILE", out)
    monkeypatch.setattr("prediction_telemetry.TELEMETRY_DIR", tmp_path)

    u = CoinbaseMarketUniverse()
    u.ingest_products(_mixed_payload())

    base = ["BTC/USD"]
    multi_cfg = {"enabled": True, "allow_live_trading_symbols": ["ADA/USD"]}

    effective, report = u.resolve_live_crypto_symbols(base, multi_cfg)

    assert out.exists()
    content = out.read_text()
    assert "MULTI_ASSET" in content or "ADA-USD" in content or "multi_asset_selector" in content
    assert "candidate" in content or "skipped" in content or "decision_status" in content


def test_no_increase_to_notionals_exposure_tp_sl_hold_time():
    """The new config section must not raise any live risk numbers."""
    # Current known micro caps from the Coinbase crypto config (P2-012C must not have increased them)
    cfg_max = get_cfg("crypto", "max_trade_notional_usd", default=0)
    cfg_total = get_cfg("crypto", "max_total_crypto_exposure_usd", default=0)
    sl = get_cfg("crypto", "stop_loss_pct", default=0)
    tp = get_cfg("crypto", "take_profit_pct", default=0)
    hold = get_cfg("crypto", "max_position_minutes", default=0)

    # Must still be the safe micro values (P2-012C addition did not raise them)
    assert 0 < float(cfg_max) <= 3.0   # safe micro (P2-012C did not increase)
    assert 0 < float(cfg_total) <= 6.0
    assert 0 < float(sl) <= 2.0
    assert 0 < float(tp) <= 4.0      # safe micro range (probe 3.25 or main 3.00)
    assert 0 < float(hold) <= 120

    # The new multi_asset_spot section itself must not have introduced any higher notional keys
    multi = get_cfg("crypto", "multi_asset_spot", default={})
    for k in ["max_trade_notional_usd", "max_single_trade_notional_usd", "max_notional_usd"]:
        if k in multi:
            assert float(multi[k]) <= cfg_max, "P2-012C must not increase notional via new fields"


def test_no_append_coinbase_fill_row_or_fills_csv_references():
    """P2-012C changes must never touch the blocked fill logger path."""
    import re
    from pathlib import Path as Pth

    # Check the two files we touched for the selector + integration
    for fname in ["coinbase_market_universe.py", "strategy_router.py"]:
        src = Pth(fname).read_text()
        cleaned = re.sub(r'""".*?"""', '', src, flags=re.DOTALL)
        cleaned = re.sub(r"'''.*?'''", '', cleaned, flags=re.DOTALL)
        cleaned = re.sub(r'#.*', '', cleaned)
        assert "append_coinbase_fill_row" not in cleaned, f"{fname} must not reference fill logger"
        assert "coinbase_fills.csv" not in cleaned


def test_active_handoff_unchanged():
    """Enforced at test time (git must show zero diff)."""
    result = subprocess.run(
        ["git", "diff", "main", "--", "docs/ACTIVE_HANDOFF.md"],
        capture_output=True, text=True, cwd="."
    )
    diff_lines = result.stdout.strip().splitlines() if result.stdout else []
    assert len(diff_lines) == 0, "ACTIVE_HANDOFF.md must remain completely unchanged for P2-012D"


def test_p2_012d_config_enables_multi_asset_with_explicit_allowlist_and_safe_caps():
    """P2-012D: config turns the gate on with non-empty explicit allowlist and conservative caps."""
    import yaml
    cfg_path = Path("config_coinbase_crypto.yaml")
    cfg = yaml.safe_load(cfg_path.read_text()) if cfg_path.exists() else {}

    crypto = cfg.get("crypto", {})
    multi = crypto.get("multi_asset_spot", {})
    assert multi.get("enabled") is True, "P2-012D requires multi_asset_spot.enabled=true"
    allowlist = multi.get("allow_live_trading_symbols", [])
    assert len(allowlist) > 0, "P2-012D requires explicit non-empty allow_live_trading_symbols"

    # Base symbols still present
    base_live = crypto.get("live_symbols", [])
    assert set(base_live) >= {"BTC/USD", "ETH/USD", "SOL/USD"}

    # Caps per P2-012D allowance (notional <=2, exposure<=8, daily loss<=4)
    assert crypto.get("max_trade_notional_usd", 0) <= 2.0
    assert crypto.get("max_total_crypto_exposure_usd", 0) <= 8.0
    global_risk = cfg.get("global_risk", {})
    assert global_risk.get("max_daily_loss_usd", 0) <= 4.0
    assert global_risk.get("max_open_positions", 0) <= 3
    assert multi.get("max_new_symbols_per_day", 0) <= 2

    # Prediction telemetry still referenced/available
    import prediction_telemetry as pt
    assert hasattr(pt, "safe_log_prediction_telemetry")


def test_symbol_normalization_consistency():
    """P2-012E: ADA/USD vs ADA-USD etc. must normalize to the same identity."""
    from coinbase_market_universe import normalize_product_id, normalize_to_hyphen

    assert normalize_product_id("ADA-USD") == "ADA/USD"
    assert normalize_product_id("ada/usd") == "ADA/USD"
    assert normalize_product_id("AVAX-USD") == "AVAX/USD"

    assert normalize_to_hyphen("ADA/USD") == "ADA-USD"
    assert normalize_to_hyphen("AVAX/USD") == "AVAX-USD"

    # Round-trip
    assert normalize_product_id(normalize_to_hyphen("ADA/USD")) == "ADA/USD"


def test_fallback_allows_allowlisted_spot_without_full_metadata(tmp_path, monkeypatch):
    """P2-012E: when no product metadata, allowlisted configured spot symbols still join if they pass ID filters."""
    from coinbase_market_universe import CoinbaseMarketUniverse

    u = CoinbaseMarketUniverse()  # deliberately empty — no ingest
    base = ["BTC/USD", "ETH/USD", "SOL/USD"]
    multi_cfg = {
        "enabled": True,
        "allow_live_trading_symbols": ["ADA/USD", "AVAX/USD"],
        "max_symbols": 8,
        "allowed_quote_currencies": ["USD", "USDC"],
    }

    effective, report = u.resolve_live_crypto_symbols(base, multi_cfg)

    eff_norm = {s.replace("/", "-").upper() for s in effective}
    assert eff_norm >= {"BTC-USD", "ETH-USD", "SOL-USD", "ADA-USD", "AVAX-USD"}
    assert report["selected_new_count"] >= 2
    assert "ADA-USD" in report.get("newly_selected", []) or any("ADA" in str(x) for x in report.get("newly_selected", []))
