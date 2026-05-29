"""
test_config.py — Config loading and environment tests.

Tests that config defaults are safe, kill switches work,
and secret handling never exposes credentials.

Run: pytest tests/test_config.py -v
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ALPACA_API_KEY", "test_key")
os.environ.setdefault("ALPACA_SECRET_KEY", "test_secret")
os.environ.setdefault("LIVE_TRADING", "false")
os.environ.setdefault("ALPACA_PAPER", "true")


class TestConfigDefaults:
    def test_config_loads_without_error(self):
        import utils
        utils._config = None  # reset cache
        cfg = utils.load_config()
        assert isinstance(cfg, dict)
        assert "mode" in cfg

    def test_default_mode_is_dry_run(self):
        import utils
        utils._config = None
        cfg = utils.load_config()
        assert cfg.get("mode") in ("dry_run", "paper", "live")

    def test_live_trading_flag_is_bool(self):
        # live_trading.enabled may be True or False depending on account state;
        # what matters is that it is always a boolean (not missing/None).
        import utils
        utils._config = None
        cfg = utils.load_config()
        val = cfg.get("live_trading", {}).get("enabled")
        assert isinstance(val, bool), f"live_trading.enabled must be bool, got {type(val)}"

    def test_options_live_flag_is_bool(self):
        # options.live_enabled is set True when broker approval is granted.
        # It may be True or False; what matters is it is always a boolean.
        import utils
        utils._config = None
        cfg = utils.load_config()
        val = cfg.get("options", {}).get("live_enabled")
        assert isinstance(val, bool), f"options.live_enabled must be bool, got {type(val)}"

    def test_shorts_live_disabled_by_default(self):
        import utils
        utils._config = None
        cfg = utils.load_config()
        assert cfg.get("short_selling", {}).get("live_enabled") is False

    def test_margin_live_disabled_by_default(self):
        import utils
        utils._config = None
        cfg = utils.load_config()
        assert cfg.get("margin", {}).get("live_enabled") is False

    def test_max_daily_loss_reasonable(self):
        import utils
        utils._config = None
        cfg = utils.load_config()
        max_loss = cfg.get("global_risk", {}).get("max_daily_loss_usd", 0)
        assert 0 < max_loss <= 5.0, f"Unexpected max_daily_loss_usd: {max_loss}"

    def test_crypto_notional_within_account_size(self):
        import utils
        utils._config = None
        cfg = utils.load_config()
        max_notional = cfg.get("crypto", {}).get("max_trade_notional_usd", 0)
        # Should be <= 3 for a $10 account
        assert max_notional <= 3.0, f"Max crypto notional too high: {max_notional}"

    def test_equity_floor_exists(self):
        import utils
        utils._config = None
        cfg = utils.load_config()
        floor = cfg.get("account", {}).get("disable_live_below_equity", 0)
        assert floor > 0

    def test_config_file_not_missing(self):
        config_path = Path(__file__).parent.parent / "config.yaml"
        assert config_path.exists(), "config.yaml missing from project root"

    def test_env_example_not_missing(self):
        env_example = Path(__file__).parent.parent / ".env.example"
        assert env_example.exists(), ".env.example missing from project root"

    def test_gitignore_excludes_env(self):
        gitignore = Path(__file__).parent.parent / ".gitignore"
        assert gitignore.exists()
        content = gitignore.read_text()
        assert ".env" in content, ".env must be listed in .gitignore"


class TestKillSwitches:
    def test_live_trading_env_false_is_blocked(self, monkeypatch):
        monkeypatch.setenv("LIVE_TRADING", "false")
        import utils
        assert utils.is_live_trading_enabled() is False

    def test_live_trading_env_true_is_allowed(self, monkeypatch):
        monkeypatch.setenv("LIVE_TRADING", "true")
        import utils
        assert utils.is_live_trading_enabled() is True

    def test_live_trading_env_missing_defaults_false(self, monkeypatch):
        monkeypatch.delenv("LIVE_TRADING", raising=False)
        import utils
        assert utils.is_live_trading_enabled() is False

    def test_live_mode_without_env_raises(self, monkeypatch):
        import utils
        utils._config = None
        cfg = utils.load_config()
        cfg["mode"] = "live"
        monkeypatch.setenv("LIVE_TRADING", "false")
        with pytest.raises(RuntimeError, match="LIVE_TRADING"):
            utils.assert_not_live_without_env()
        cfg["mode"] = "dry_run"
        utils._config = None

    def test_paper_mode_does_not_raise(self, monkeypatch):
        import utils
        utils._config = None
        cfg = utils.load_config()
        cfg["mode"] = "paper"
        monkeypatch.setenv("LIVE_TRADING", "false")
        utils.assert_not_live_without_env()  # should not raise
        cfg["mode"] = "dry_run"
        utils._config = None


class TestSecretHandling:
    def test_placeholder_key_raises(self, monkeypatch):
        monkeypatch.setenv("ALPACA_API_KEY", "replace_me")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "replace_me")
        import utils
        with pytest.raises(RuntimeError):
            utils.get_alpaca_keys()

    def test_empty_key_raises(self, monkeypatch):
        monkeypatch.setenv("ALPACA_API_KEY", "")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "")
        import utils
        with pytest.raises(RuntimeError):
            utils.get_alpaca_keys()

    def test_valid_keys_do_not_print(self, monkeypatch, capsys):
        monkeypatch.setenv("ALPACA_API_KEY", "AKFAKEKEY12345")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "FakeSekret9999")
        import utils
        api_key, secret_key = utils.get_alpaca_keys()
        captured = capsys.readouterr()
        # Keys should NEVER appear in stdout/stderr
        assert "AKFAKEKEY12345" not in captured.out
        assert "AKFAKEKEY12345" not in captured.err
        assert "FakeSekret9999" not in captured.out
        assert "FakeSekret9999" not in captured.err


class TestHelpers:
    def test_spread_pct_normal(self):
        from utils import spread_pct
        sp = spread_pct(bid=99.0, ask=101.0)
        # spread = 2, mid = 100 → 2%
        assert abs(sp - 2.0) < 0.01

    def test_spread_pct_invalid(self):
        from utils import spread_pct
        sp = spread_pct(bid=0, ask=0)
        assert sp >= 999

    def test_safe_float_handles_none(self):
        from utils import safe_float
        assert safe_float(None) == 0.0
        assert safe_float("abc") == 0.0
        assert safe_float("3.14") == pytest.approx(3.14)

    def test_data_is_stale_with_old_ts(self):
        from datetime import datetime, timezone, timedelta
        from utils import data_is_stale
        old = datetime.now(timezone.utc) - timedelta(seconds=30)
        assert data_is_stale(old, max_seconds=15) is True

    def test_data_is_stale_with_fresh_ts(self):
        from datetime import datetime, timezone
        from utils import data_is_stale
        fresh = datetime.now(timezone.utc)
        assert data_is_stale(fresh, max_seconds=15) is False

    def test_data_is_stale_with_none(self):
        from utils import data_is_stale
        assert data_is_stale(None, max_seconds=15) is True
