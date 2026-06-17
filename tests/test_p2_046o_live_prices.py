"""P2-046O — live price provider (cache + fallback). No network: fetcher is injected."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from live_prices import LivePriceProvider


def test_returns_live_prices():
    p = LivePriceProvider(["SPY", "BTC"], {}, fetcher=lambda syms: {"SPY": 500.0, "BTC": 60000.0})
    assert p() == {"SPY": 500.0, "BTC": 60000.0}
    assert p.last_source == "live"


def test_caches_within_ttl():
    calls = []
    def fetch(syms):
        calls.append(1)
        return {"SPY": 500.0}
    t = [1000.0]
    p = LivePriceProvider(["SPY"], {}, fetcher=fetch, ttl_seconds=20, clock=lambda: t[0])
    p(); p()                       # second call within TTL -> cached
    assert len(calls) == 1
    t[0] += 25                      # advance past TTL
    p()
    assert len(calls) == 2


def test_falls_back_to_csv_on_failure(tmp_path):
    csv = tmp_path / "SPY.csv"
    csv.write_text("date,open,high,low,close,volume\n2024-01-01,1,1,1,432.10,1\n")
    def boom(syms):
        raise RuntimeError("network down")
    p = LivePriceProvider(["SPY"], {"SPY": str(csv)}, fetcher=boom)
    out = p()
    assert out["SPY"] == 432.10 and p.last_source == "csv_fallback"


def test_backfills_missing_symbol_from_csv(tmp_path):
    csv = tmp_path / "BND.csv"
    csv.write_text("date,open,high,low,close,volume\n2024-01-01,1,1,1,73.40,1\n")
    # live returns SPY only; BND should be backfilled from CSV
    p = LivePriceProvider(["SPY", "BND"], {"BND": str(csv)}, fetcher=lambda s: {"SPY": 500.0})
    out = p()
    assert out["SPY"] == 500.0 and out["BND"] == 73.40


def test_empty_live_and_no_csv_returns_empty():
    p = LivePriceProvider(["SPY"], {}, fetcher=lambda s: {})
    assert p() == {} and p.last_source == "csv_fallback"
