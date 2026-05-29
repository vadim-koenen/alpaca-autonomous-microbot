import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shadow_learner.evaluate import (
    EDGE_INSUFFICIENT,
    EDGE_INSUFFICIENT_PROSPECTIVE,
    EDGE_NO_EVIDENCE,
    RANDOM_BASELINE_MODEL,
    build_advisory_evaluation,
)
from shadow_learner.feature_snapshot import FeatureSnapshot, record_feature_snapshot
from shadow_learner.outcome_labeler import write_outcome
from shadow_learner.prediction_journal import record_prediction
from shadow_learner.schema import connect, init_db

ROOT = Path(__file__).resolve().parents[1]


def _snapshot(**overrides):
    data = dict(
        broker="coinbase",
        asset_class="crypto",
        symbol="BTC/USD",
        strategy="coinbase_probe",
        price=100.0,
        bid=99.9,
        ask=100.1,
        spread_pct=0.1,
        quote_age_seconds=1.0,
        bars_available=20,
        market_data_status="valid",
        created_at_utc="2020-01-01T00:00:00Z",
        features={"momentum_pct": 0.2},
    )
    data.update(overrides)
    return FeatureSnapshot(**data)


def _prediction(
    db,
    *,
    model_name="retrospective_momentum_v0",
    model_version="0.1.0",
    probability=0.6,
    future_return_pct=1.0,
    status="labeled",
    retrospective=True,
    prospective=False,
    symbol="BTC/USD",
    broker="coinbase",
    horizon=15,
    live_trade_taken=False,
):
    snapshot_id = record_feature_snapshot(
        _snapshot(symbol=symbol, broker=broker, created_at_utc="2020-01-01T00:00:00Z"),
        db_path=db,
    )
    pred_id = record_prediction(
        snapshot_id,
        {
            "prediction_type": f"return_direction_{horizon}m",
            "prediction_value": probability,
            "confidence": abs(probability - 0.5) * 2,
            "horizon_minutes": horizon,
            "model_name": model_name,
            "model_version": model_version,
            "feature_version": "test",
            "reason": {
                "retrospective_generated": retrospective,
                "prospective_shadow_generated": prospective,
                "uses_only_t0_or_prior_data": True,
            },
        },
        db_path=db,
        live_trade_taken=live_trade_taken,
    )
    write_outcome(
        prediction_id=pred_id,
        horizon_minutes=horizon,
        outcome_status=status,
        future_return_pct=future_return_pct if status == "labeled" else None,
        max_favorable_excursion_pct=2.0 if status == "labeled" else None,
        max_adverse_excursion_pct=-0.5 if status == "labeled" else None,
        market_data_available=status == "labeled",
        outcome_json={},
        db_path=db,
    )
    return pred_id


def _by_model(report, model_name):
    return next(row for row in report["by_model"] if row["model_name"] == model_name)


def test_evaluator_computes_accuracy_correctly(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    _prediction(db, probability=0.7, future_return_pct=1.0)
    _prediction(db, probability=0.3, future_return_pct=-1.0)
    _prediction(db, probability=0.8, future_return_pct=-0.5)
    _prediction(db, probability=0.2, future_return_pct=0.5)

    report = build_advisory_evaluation(db_path=db, since="2020-01-01")

    assert report["overall"]["labeled_count"] == 4
    assert report["overall"]["accuracy"] == pytest.approx(0.5)
    assert report["overall"]["actual_up_count"] == 2
    assert report["overall"]["actual_down_count"] == 2


def test_evaluator_computes_brier_score_correctly(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    _prediction(db, probability=0.8, future_return_pct=1.0)
    _prediction(db, probability=0.2, future_return_pct=-1.0)

    report = build_advisory_evaluation(db_path=db, since="2020-01-01")

    assert report["overall"]["brier_score"] == pytest.approx(0.04)


def test_evaluator_separates_retrospective_generated_true_false(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    _prediction(db, retrospective=True)
    _prediction(db, retrospective=False)

    report = build_advisory_evaluation(db_path=db, since="2020-01-01")
    split = {row["retrospective_generated"]: row["sample_count"] for row in report["by_retrospective_generated"]}

    assert split["true"] == 1
    assert split["false"] == 1


def test_evaluator_separates_prospective_shadow_generated_true_false(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    _prediction(db, retrospective=False, prospective=True, model_name="prospective_momentum_v0")
    _prediction(db, retrospective=True, prospective=False)

    report = build_advisory_evaluation(db_path=db, since="2020-01-01")
    split = {
        row["prospective_shadow_generated"]: row["sample_count"]
        for row in report["by_prospective_shadow_generated"]
    }

    assert split["true"] == 1
    assert split["false"] == 1


def test_evaluator_separates_model_name_and_version(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    _prediction(db, model_name="retrospective_momentum_v0", model_version="0.1.0")
    _prediction(db, model_name="retrospective_momentum_v0", model_version="0.2.0")

    report = build_advisory_evaluation(db_path=db, since="2020-01-01")
    versions = {(row["model_name"], row["model_version"]) for row in report["by_model"]}

    assert ("retrospective_momentum_v0", "0.1.0") in versions
    assert ("retrospective_momentum_v0", "0.2.0") in versions


def test_evaluator_compares_against_random_baseline(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    _prediction(db, model_name="retrospective_momentum_v0", probability=0.8, future_return_pct=1.0)
    _prediction(db, model_name="retrospective_momentum_v0", probability=0.2, future_return_pct=-1.0)
    _prediction(db, model_name=RANDOM_BASELINE_MODEL, probability=0.5, future_return_pct=1.0)
    _prediction(db, model_name=RANDOM_BASELINE_MODEL, probability=0.5, future_return_pct=-1.0)

    report = build_advisory_evaluation(db_path=db, since="2020-01-01")
    momentum = _by_model(report, "retrospective_momentum_v0")

    assert momentum["accuracy_delta_vs_random"] == pytest.approx(0.5)
    assert momentum["brier_improvement_vs_random"] > 0


def test_evaluator_handles_missing_and_insufficient_outcomes(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    _prediction(db, status="missing_data")
    _prediction(db, status="insufficient_price_history")

    report = build_advisory_evaluation(db_path=db, since="2020-01-01")

    assert report["overall"]["missing_data_count"] == 1
    assert report["overall"]["insufficient_price_history_count"] == 1
    assert report["overall"]["labeled_count"] == 0


def test_evaluator_handles_empty_db_safely(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    init_db(db)

    report = build_advisory_evaluation(db_path=db, since="2020-01-01")

    assert report["overall"]["sample_count"] == 0
    assert report["evidence"]["status"] == "DATA_QUALITY_FAILURE"


def test_one_symbol_only_data_does_not_overclaim(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    _prediction(db, symbol="BTC/USD")

    report = build_advisory_evaluation(db_path=db, since="2020-01-01")

    assert report["evidence"]["status"] == EDGE_INSUFFICIENT
    assert any("Crypto-only labeled samples" in warning for warning in report["warnings"])


def test_prospective_only_filter_excludes_retrospective_rows(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    _prediction(db, model_name="prospective_momentum_v0", retrospective=False, prospective=True)
    _prediction(db, model_name="retrospective_momentum_v0", retrospective=True, prospective=False)

    report = build_advisory_evaluation(
        db_path=db,
        since="2020-01-01",
        prospective_only=True,
    )

    assert report["prospective_only"] is True
    assert report["overall"]["sample_count"] == 1
    assert report["by_model"][0]["model_name"] == "prospective_momentum_v0"


def test_prospective_only_returns_insufficient_when_sample_count_is_small(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    _prediction(db, model_name="prospective_momentum_v0", retrospective=False, prospective=True)
    _prediction(
        db,
        model_name="prospective_random_baseline_v0",
        probability=0.5,
        retrospective=False,
        prospective=True,
    )

    report = build_advisory_evaluation(
        db_path=db,
        since="2020-01-01",
        prospective_only=True,
    )

    assert report["evidence"]["status"] == EDGE_INSUFFICIENT_PROSPECTIVE
    assert any("labeled prospective directional outcomes" in reason for reason in report["evidence"]["reasons"])
    assert any("prospective collection days" in reason for reason in report["evidence"]["reasons"])


def test_no_evidence_when_random_performs_similarly(tmp_path, monkeypatch):
    db = tmp_path / "shadow.sqlite3"
    import shadow_learner.evaluate as evaluation

    monkeypatch.setattr(evaluation, "MIN_DIRECTIONAL_LABELS_FOR_EVALUATION", 2)
    monkeypatch.setattr(evaluation, "MIN_SYMBOL_HORIZON_LABELS_FOR_EVALUATION", 1)
    _prediction(db, model_name="retrospective_momentum_v0", probability=0.5, future_return_pct=1.0)
    _prediction(db, model_name="retrospective_momentum_v0", probability=0.5, future_return_pct=-1.0)
    _prediction(db, model_name=RANDOM_BASELINE_MODEL, probability=0.5, future_return_pct=1.0)
    _prediction(db, model_name=RANDOM_BASELINE_MODEL, probability=0.5, future_return_pct=-1.0)

    report = evaluation.build_advisory_evaluation(db_path=db, since="2020-01-01")

    assert report["evidence"]["status"] == EDGE_NO_EVIDENCE


def test_evaluator_cli_reports_warnings_and_advisory_only(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    _prediction(db)

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "shadow_evaluate_predictions.py"),
            "--since",
            "2020-01-01",
            "--db",
            str(db),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "Retrospective predictions are advisory backfilled predictions" in result.stdout
    assert "Approved for live trading: NO" in result.stdout
    assert "Recommendation: advisory only; not used for live trading" in result.stdout


def test_evaluator_cli_supports_prospective_only_filter(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    _prediction(db, model_name="prospective_momentum_v0", retrospective=False, prospective=True)

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "shadow_evaluate_predictions.py"),
            "--since",
            "2020-01-01",
            "--prospective-only",
            "--db",
            str(db),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "Prospective only: YES" in result.stdout
    assert EDGE_INSUFFICIENT_PROSPECTIVE in result.stdout
    assert "Approved for live trading: NO" in result.stdout


def test_evaluator_cli_output_redacts_secret_like_values(tmp_path, monkeypatch):
    db = tmp_path / "shadow.sqlite3"
    monkeypatch.setenv("ALPACA_SECRET_KEY", "DO_NOT_PRINT_ME")

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "shadow_evaluate_predictions.py"),
            "--since",
            "2020-01-01",
            "--db",
            str(db),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "DO_NOT_PRINT_ME" not in result.stdout
    assert "ALPACA_SECRET_KEY" not in result.stdout


def test_evaluator_preserves_symbols_prices_and_timestamps(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    _prediction(db, symbol="BTC/USD", probability=0.7, future_return_pct=1.25)

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "shadow_evaluate_predictions.py"),
            "--since",
            "2020-01-01",
            "--symbol",
            "BTC/USD",
            "--db",
            str(db),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "BTC/USD" in result.stdout
    assert "2020-01-01T00:00:00Z" in result.stdout
    assert "avg_ret_up=1.250" in result.stdout


def test_evaluator_script_does_not_modify_state_files(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    _prediction(db)
    state_file = tmp_path / "open_positions.json"
    state_file.write_text(json.dumps({"BTC/USD": {"notional": 0.5}}))
    before = state_file.read_text()

    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "shadow_evaluate_predictions.py"),
            "--since",
            "2020-01-01",
            "--db",
            str(db),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert state_file.read_text() == before


def test_evaluator_does_not_change_strategy_config_or_risk_files(tmp_path):
    db = tmp_path / "shadow.sqlite3"
    watched = [
        ROOT / "risk_manager.py",
        ROOT / "order_manager.py",
        ROOT / "main.py",
        ROOT / "config_coinbase_crypto.yaml",
        ROOT / "strategy_crypto.py",
    ]
    before = {path: path.read_bytes() for path in watched}

    _prediction(db)
    build_advisory_evaluation(db_path=db, since="2020-01-01")

    assert {path: path.read_bytes() for path in watched} == before


def test_evaluator_does_not_import_execution_modules():
    combined = "\n".join(
        [
            (ROOT / "scripts" / "shadow_evaluate_predictions.py").read_text(),
            (ROOT / "shadow_learner" / "evaluate.py").read_text(),
        ]
    )

    assert "risk_manager" not in combined
    assert "order_manager" not in combined
    assert "broker_alpaca" not in combined
    assert "broker_coinbase" not in combined
