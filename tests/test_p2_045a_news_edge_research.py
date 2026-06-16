"""
tests/test_p2_045a_news_edge_research.py — P2-045A tests.
Pure stdlib + pytest. No broker, no network. Deterministic.
Synthetic data validates MECHANICS only; not a profitability claim.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import news_edge_research as ne
import equities_swing_backtest_gate as gate


def _bars_from_closes(closes):
    bars, day = [], datetime(2024, 1, 1)
    for c in closes:
        bars.append(gate.Bar(day.strftime("%Y-%m-%d"), c, c + 0.1, c - 0.1, c, 1e6))
        day += timedelta(days=1)
    return bars


def test_lexicon_sentiment_signs():
    assert ne.lexicon_sentiment("Bitcoin ETF approval sparks rally") > 0
    assert ne.lexicon_sentiment("Exchange hack triggers selloff and lawsuit") < 0
    assert ne.lexicon_sentiment("Bitcoin trades sideways today") == 0.0


def test_load_news_jsonl_and_csv(tmp_path):
    j = tmp_path / "n.jsonl"
    j.write_text('{"date":"2024-01-02","symbol":"BTC/USD","sentiment":0.8,"headline":"rally"}\n')
    c = tmp_path / "n.csv"
    c.write_text("date,symbol,sentiment,headline\n2024-01-03,ETH/USD,-0.5,crash\n")
    assert ne.load_news(j)[0].sentiment == pytest.approx(0.8)
    assert ne.load_news(c)[0].sentiment == pytest.approx(-0.5)


def test_insufficient_data_verdict():
    bars = _bars_from_closes([100 + i for i in range(20)])
    events = [ne.NewsEvent("2024-01-02", "BTC/USD", 0.9)]
    r = ne.research(bars, events, horizon_days=3)
    assert r["verdict"] == "INSUFFICIENT_DATA"
    assert r["authorizes_live"] is False


def test_detects_real_signal_when_positive_news_precedes_up_moves():
    # Construct prices that JUMP up shortly after each positive-news date.
    closes = [100.0] * 200
    events = []
    day0 = datetime(2024, 1, 1)
    for k in range(40):
        idx = 3 + k * 4
        # positive news at idx; price 3 bars later is higher
        for j in range(idx + 1, len(closes)):
            closes[j] += 5.0  # persistent up-shift after the event
        ev_date = (day0 + timedelta(days=idx)).strftime("%Y-%m-%d")
        events.append(ne.NewsEvent(ev_date, "BTC/USD", 0.9))
    bars = _bars_from_closes(closes)
    r = ne.research(bars, events, horizon_days=3, min_events=30,
                    costs=gate.CostModel(commission_bps_per_side=0.0, spread_bps=1.0, slippage_bps_per_side=1.0))
    assert r["verdict"] == "NEWS_EDGE_SIGNAL"
    assert r["oos"]["mean_net_fwd_return_bps"] > 0


def test_no_edge_when_news_uncorrelated_with_returns():
    # Flat prices => no forward return; positive news can't manufacture edge.
    closes = [100.0] * 200
    events = []
    day0 = datetime(2024, 1, 1)
    for k in range(50):
        idx = 2 + k * 3
        events.append(ne.NewsEvent((day0 + timedelta(days=idx)).strftime("%Y-%m-%d"), "BTC/USD", 0.9))
    bars = _bars_from_closes(closes)
    r = ne.research(bars, events, horizon_days=3, min_events=30)
    assert r["verdict"] == "NO_NEWS_EDGE"


def test_main_writes_outputs(tmp_path):
    prices = tmp_path / "p.csv"
    rows = ["date,open,high,low,close,volume"]
    day = datetime(2024, 1, 1)
    for i in range(120):
        c = 100 + i
        rows.append(f"{day.strftime('%Y-%m-%d')},{c},{c+1},{c-1},{c},1000")
        day += timedelta(days=1)
    prices.write_text("\n".join(rows) + "\n")
    news = tmp_path / "n.jsonl"
    nlines = []
    day = datetime(2024, 1, 1)
    for k in range(40):
        d = (day + timedelta(days=2 + k * 2)).strftime("%Y-%m-%d")
        nlines.append(json.dumps({"date": d, "symbol": "BTC/USD", "sentiment": 0.9}))
    news.write_text("\n".join(nlines) + "\n")
    rc = ne.main(["--prices", str(prices), "--news", str(news), "--out-dir", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "p2_045a_news_edge_research.json").exists()
