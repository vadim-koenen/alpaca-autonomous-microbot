import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shadow_learner.news_classifier import classify_news
from shadow_learner.news_context import NewsInput, record_news_items, redact_news_text
from shadow_learner.schema import init_db

ROOT = Path(__file__).resolve().parents[1]


def _news_tables(db):
    with sqlite3.connect(db) as conn:
        return {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }


def test_news_schema_tables_are_created(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    init_db(db)

    tables = _news_tables(db)

    assert "shadow_news_items" in tables
    assert "shadow_news_signal_links" in tables
    assert "shadow_news_outcomes" in tables


def test_classifier_maps_stellar_tokenization_to_xlm():
    result = classify_news(
        "Stellar surges amid Wall Street giant's tokenization plan",
        "DTCC announced connecting Stellar to its tokenized asset platform. XLM surged nearly 30%.",
    )

    assert "XLM" in result["symbols"]
    assert "tokenization" in result["themes"]
    assert "institutional_adoption" in result["themes"]
    assert "asset_specific_catalyst" in result["themes"]
    assert result["sentiment_score"] > 0


def test_classifier_maps_hype_etf_flows():
    result = classify_news(
        "HYPE ETFs gain inflows despite crypto downtrend",
        "Hyperliquid-linked ETF products gained inflows while the broader market remained weak.",
    )

    assert "HYPE" in result["symbols"]
    assert "etf_flow" in result["themes"]
    assert "market_downtrend" in result["themes"]


def test_classifier_maps_btc_below_threshold():
    result = classify_news(
        "BTC falls below $75,000 as macro risk rises",
        "Bitcoin slipped below the threshold during a broader crypto selloff.",
    )

    assert "BTC" in result["symbols"]
    assert "market_downtrend" in result["themes"]
    assert "macro_risk" in result["themes"]
    assert result["sentiment_score"] < 0


def test_classifier_maps_bnb_etf_launch():
    result = classify_news(
        "VanEck BNB ETF launch opens new institutional access",
        "BNB gained after the ETF launch announcement.",
    )

    assert "BNB" in result["symbols"]
    assert "etf_launch" in result["themes"]


def test_classifier_maps_stablecoin_payments():
    result = classify_news(
        "Stripe Tempo blockchain transaction growth accelerates",
        "Stablecoin payments and USDC transactions grew across payment corridors.",
    )

    assert "stablecoin_payments" in result["themes"]
    assert "chain_activity" in result["themes"]
    assert "USDC" in result["symbols"]


def test_news_deduplication_prevents_duplicate_inserts(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    item = NewsInput(
        source="Coinbase Market Briefing",
        title="Stellar surges amid Wall Street giant's tokenization plan",
        summary="DTCC announced connecting Stellar to tokenized assets. XLM surged.",
        published_at_utc="2026-05-28T15:26:00Z",
    )

    first = record_news_items([item], db_path=db, since_utc="2026-05-28T00:00:00Z")
    second = record_news_items([item], db_path=db, since_utc="2026-05-28T00:00:00Z")

    assert first["inserted"] == 1
    assert second["existing"] == 1
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM shadow_news_items").fetchone()[0] == 1


def test_manual_json_import_works(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    input_file = tmp_path / "manual_news.json"
    input_file.write_text(
        json.dumps(
            {
                "source": "Coinbase Market Briefing",
                "title": "Stellar surges amid Wall Street giant's tokenization plan",
                "summary": "DTCC announced connecting Stellar to its tokenized asset platform. XLM surged nearly 30%.",
                "published_at_utc": "2026-05-28T15:26:00Z",
            }
        )
    )

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "shadow_news_ingest.py"),
            "--since",
            "2026-05-28",
            "--input-file",
            str(input_file),
            "--skip-fetch",
            "--db",
            str(db),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "Inserted items: 1" in result.stdout
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM shadow_news_items").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM shadow_news_signal_links").fetchone()[0] > 0


def test_news_report_runs_with_empty_db(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "shadow_news_report.py"),
            "--since",
            "2026-05-28",
            "--db",
            str(db),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "Total news items: 0" in result.stdout
    assert "Recommendation: advisory only; not used for live trading" in result.stdout


def test_news_report_runs_with_sample_db(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    record_news_items(
        [
            NewsInput(
                source="Coinbase Market Briefing",
                title="VanEck BNB ETF launch opens new institutional access",
                summary="BNB gained after the ETF launch announcement.",
                published_at_utc="2026-05-28T15:00:00Z",
            )
        ],
        db_path=db,
        since_utc="2026-05-28T00:00:00Z",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "shadow_news_report.py"),
            "--since",
            "2026-05-28",
            "--db",
            str(db),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "Total news items: 1" in result.stdout
    assert "BNB: 1" in result.stdout
    assert "etf_launch: 1" in result.stdout


def test_news_redaction_removes_sensitive_values():
    text = "Account: 123456789 api_key=APCA1234567890ABCDE BTC below $75,000 at 2026-05-28T15:00:00Z"
    redacted = redact_news_text(text)

    assert "123456789" not in redacted
    assert "APCA1234567890ABCDE" not in redacted
    assert "BTC" in redacted
    assert "$75,000" in redacted
    assert "2026-05-28T15:00:00Z" in redacted


def test_news_symbols_prices_timestamps_are_not_redacted():
    redacted = redact_news_text("BTC ETH SOL XLM BNB HYPE price=$75000 time=2026-05-28T15:26:00Z")

    assert "BTC" in redacted
    assert "ETH" in redacted
    assert "SOL" in redacted
    assert "XLM" in redacted
    assert "BNB" in redacted
    assert "HYPE" in redacted
    assert "$75000" in redacted
    assert "2026-05-28T15:26:00Z" in redacted


def test_news_ingest_does_not_modify_state_files(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    state_dir = tmp_path / "state" / "coinbase"
    state_dir.mkdir(parents=True)
    state_file = state_dir / "open_positions.json"
    state_file.write_text('{"positions":{}}')
    before = state_file.read_text()

    record_news_items(
        [
            NewsInput(
                source="manual",
                title="BTC falls below $75,000",
                summary="Bitcoin downtrend continues.",
                published_at_utc="2026-05-28T15:00:00Z",
            )
        ],
        db_path=db,
        since_utc="2026-05-28T00:00:00Z",
    )

    assert state_file.read_text() == before


def test_news_scripts_do_not_import_live_execution_modules():
    combined = "\n".join(
        [
            (ROOT / "scripts" / "shadow_news_ingest.py").read_text(),
            (ROOT / "scripts" / "shadow_news_report.py").read_text(),
            (ROOT / "shadow_learner" / "news_context.py").read_text(),
            (ROOT / "shadow_learner" / "news_classifier.py").read_text(),
        ]
    )

    assert "risk_manager" not in combined
    assert "order_manager" not in combined
    assert "broker_alpaca" not in combined
    assert "broker_coinbase" not in combined
