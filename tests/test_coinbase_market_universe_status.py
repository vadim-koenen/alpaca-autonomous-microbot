"""
P2-012A tests for the market universe status script (read-only).
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from scripts import coinbase_market_universe_status as status_mod


def test_status_script_runs_without_file(tmp_path, monkeypatch, capsys):
    """Should not crash even with no data."""
    with patch("sys.argv", ["prog"]):
        try:
            status_mod.main()
        except SystemExit:
            pass
    out = capsys.readouterr().out
    assert "Market Universe Status" in out or "Scaffold only" in out or "Total products" in out


def test_status_script_with_file(tmp_path, capsys):
    data = {
        "products": [
            {"product_id": "BTC-USD", "base_currency": "BTC", "quote_currency": "USD", "product_type": "spot_crypto"},
            {"product_id": "GOLD-PERP", "base_currency": "GOLD", "quote_currency": "USD", "contract_type": "perpetual"},
        ]
    }
    f = tmp_path / "universe.json"
    f.write_text(json.dumps(data))

    with patch("sys.argv", ["prog", "--file", str(f), "--json"]):
        try:
            status_mod.main()
        except SystemExit:
            pass

    out = capsys.readouterr().out
    assert "GOLD-PERP" in out or "commodity" in out.lower() or "gold" in out.lower()
