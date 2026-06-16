"""P2-046C — news risk monitor tests (advisory + circuit-breaker, never a signal)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import news_risk_monitor as nrm


def test_classify_critical():
    c = nrm.classify_headline("Major exchange HACKED, funds drained")
    assert c["severity"] == nrm.RISK_ALERT and c["matched"] in ("hack", "hacked", "drained")


def test_classify_elevated():
    c = nrm.classify_headline("Regulator opens investigation into firm")
    assert c["severity"] == nrm.WATCH and c["matched"] == "investigation"


def test_classify_benign_is_advisory():
    c = nrm.classify_headline("Company announces quarterly update")
    assert c["severity"] == nrm.ADVISORY and c["matched"] is None


def test_scan_flags_risk_and_recommends_pause():
    items = [
        {"date": "2026-06-16", "symbol": "BTC/USD", "headline": "Bridge exploit drains $100M"},
        {"date": "2026-06-16", "symbol": "SPY", "headline": "Markets drift higher"},
    ]
    scan = nrm.scan_news(items)
    assert scan["n_risk_alerts"] == 1
    assert scan["should_pause_recommended"] is True
    assert scan["alerts_by_symbol"].get("BTC") == 1
    assert scan["authorizes_live"] is False


def test_scan_no_alerts_no_pause():
    items = [{"date": "2026-06-16", "symbol": "GLD", "headline": "Gold steady ahead of data"}]
    scan = nrm.scan_news(items)
    assert scan["n_risk_alerts"] == 0 and scan["should_pause_recommended"] is False


def test_watch_symbols_filter_limits_alerts():
    items = [{"date": "2026-06-16", "symbol": "DOGE/USD", "headline": "DOGE exchange hacked"}]
    # DOGE not in the watched basket -> not a basket risk alert
    scan = nrm.scan_news(items, watch_symbols=["BTC", "SPY", "GLD", "SLV", "QQQ"])
    assert scan["n_risk_alerts"] == 0


def test_watch_symbols_includes_held_asset():
    items = [{"date": "2026-06-16", "symbol": "BTC/USD", "headline": "BTC custodian insolvency fears"}]
    scan = nrm.scan_news(items, watch_symbols=["BTC", "SPY"])
    assert scan["n_risk_alerts"] == 1


def test_never_emits_buy_or_sell():
    items = [{"date": "2026-06-16", "symbol": "BTC/USD", "headline": "BTC surges to record high"}]
    scan = nrm.scan_news(items)
    blob = str(scan).lower()
    # a bullish headline must NOT become a buy signal; it's just advisory
    assert scan["n_risk_alerts"] == 0
    assert "buy" not in scan and "side" not in scan  # no order fields anywhere


def test_render_text_runs():
    items = [{"date": "2026-06-16", "symbol": "BTC/USD", "headline": "Exchange exploit reported"}]
    txt = nrm.render_text(nrm.scan_news(items))
    assert "RISK_ALERT" in txt


def test_empty_input():
    scan = nrm.scan_news([])
    assert scan["n_scanned"] == 0 and scan["should_pause_recommended"] is False
