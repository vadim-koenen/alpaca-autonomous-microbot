import sqlite3
from pathlib import Path

from self_update.change_classifier import classify_change


ROOT = Path(__file__).resolve().parents[1]


def test_schema_contains_self_improvement_tables():
    schema = (ROOT / "memory" / "schema.sql").read_text()
    db = sqlite3.connect(":memory:")
    db.executescript(schema)
    rows = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    tables = {row[0] for row in rows}

    expected = {
        "experiments",
        "patch_proposals",
        "paper_validations",
        "deployments",
        "rollbacks",
        "approval_decisions",
    }
    assert expected.issubset(tables)


def test_change_classifier_representative_paths_and_types():
    assert classify_change("docs/OPERATIONS.md", "docs").risk_class == 0
    assert classify_change("tests/test_risk_manager.py", "tests").risk_class == 0
    assert classify_change("scripts/status.sh", "heartbeat improvements").risk_class == 1
    assert classify_change("memory/schema.sql", "memory writes").risk_class == 1
    assert classify_change("risk_manager.py", "aggregate exposure").risk_class == 2
    assert classify_change("broker_coinbase.py", "broker adapter").risk_class == 2
    assert classify_change("strategy_equities.py", "new symbols").risk_class == 3
    assert classify_change("config.yaml", "increase notional").risk_class == 3


def test_class_2_and_3_require_human_approval():
    class_2 = classify_change("order_manager.py", "duplicate order guard")
    class_3 = classify_change("config.yaml", "enable options")

    assert class_2.risk_class == 2
    assert class_2.requires_human_approval is True
    assert class_2.separate_risk_review_required is False

    assert class_3.risk_class == 3
    assert class_3.requires_human_approval is True
    assert class_3.separate_risk_review_required is True


def test_no_auto_deploy_enabled_by_default():
    for change in [
        classify_change("docs/SELF_UPDATE_POLICY.md", "docs"),
        classify_change("scripts/reconcile.sh", "logging"),
        classify_change("risk_manager.py", "exposure calculation"),
        classify_change("strategy_crypto.py", "new strategy"),
    ]:
        assert change.auto_deploy_enabled is False


def test_self_update_policy_exists_and_forbids_self_modification():
    policy = (ROOT / "docs" / "SELF_UPDATE_POLICY.md").read_text().lower()
    assert "live trading process must never self-modify" in policy
    assert "may not auto-deploy trading, risk, broker, or strategy changes" in policy
    assert "no auto-deploy exists yet" in policy
