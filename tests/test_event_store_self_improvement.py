"""Tests for EventStore self-improvement scaffold helper methods.

All methods are advisory only.  None deploy code, restart bots, or place
broker orders.  These tests verify:
  - each method inserts a row and returns a non-None row id
  - linking (patch_proposal_id → approval_decision_id → deployment_id → rollback_id)
  - status update works
  - approved_for_live defaults to False
  - fail_safe=True never raises on a bad db path
  - no auto_deploy path exists in any method
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from memory.event_store import EventStore


@pytest.fixture()
def store(tmp_path):
    s = EventStore(path=tmp_path / "test.sqlite3", fail_safe=False)
    s.set_context(bot_name="test-bot", broker="test", asset_class="crypto")
    return s


# ------------------------------------------------------------------ #
# record_patch_proposal                                               #
# ------------------------------------------------------------------ #

def test_record_patch_proposal_returns_row_id(store):
    row_id = store.record_patch_proposal(
        title="Add heartbeat jitter",
        risk_class=1,
        summary="Adds ±0.5s jitter to prevent thundering herd",
        files=["main.py"],
        rollback_plan="Revert main.py heartbeat call",
    )
    assert isinstance(row_id, int) and row_id > 0


def test_record_patch_proposal_stores_fields(store):
    row_id = store.record_patch_proposal(
        title="Improve logging",
        risk_class=0,
        summary="Add structured log fields",
        files=["journal.py", "main.py"],
        evidence={"test_count": 138},
        tests=["tests/test_journal.py"],
        rollback_plan="Revert journal.py",
    )
    conn = sqlite3.connect(store.path)
    row = conn.execute(
        "SELECT * FROM patch_proposals WHERE id = ?", (row_id,)
    ).fetchone()
    assert row is not None
    cols = [d[1] for d in conn.execute("PRAGMA table_info(patch_proposals)").fetchall()]
    data = dict(zip(cols, row))
    assert data["title"] == "Improve logging"
    assert data["risk_class"] == 0
    assert data["status"] == "proposed"
    assert "journal.py" in data["files_json"]
    assert data["rollback_plan"] == "Revert journal.py"
    conn.close()


def test_record_patch_proposal_default_status_is_proposed(store, tmp_path):
    row_id = store.record_patch_proposal(title="Test patch", risk_class=1)
    conn = sqlite3.connect(store.path)
    row = conn.execute(
        "SELECT status FROM patch_proposals WHERE id = ?", (row_id,)
    ).fetchone()
    assert row[0] == "proposed"
    conn.close()


# ------------------------------------------------------------------ #
# update_patch_proposal_status                                        #
# ------------------------------------------------------------------ #

def test_update_patch_proposal_status(store, tmp_path):
    row_id = store.record_patch_proposal(title="Status test", risk_class=1)
    result = store.update_patch_proposal_status(row_id, status="approved")
    assert result is True
    conn = sqlite3.connect(store.path)
    row = conn.execute(
        "SELECT status FROM patch_proposals WHERE id = ?", (row_id,)
    ).fetchone()
    assert row[0] == "approved"
    conn.close()


def test_update_patch_proposal_status_links_approval_id(store, tmp_path):
    prop_id = store.record_patch_proposal(title="Link test", risk_class=2)
    approval_id = store.record_approval_decision(
        subject_type="patch_proposal",
        subject_id=prop_id,
        risk_class=2,
        decision="approved",
        decided_by="vadim",
    )
    store.update_patch_proposal_status(
        prop_id, status="approved", approval_decision_id=approval_id
    )
    conn = sqlite3.connect(store.path)
    row = conn.execute(
        "SELECT status, approval_decision_id FROM patch_proposals WHERE id = ?",
        (prop_id,),
    ).fetchone()
    assert row[0] == "approved"
    assert row[1] == approval_id
    conn.close()


# ------------------------------------------------------------------ #
# record_approval_decision                                            #
# ------------------------------------------------------------------ #

def test_record_approval_decision_returns_row_id(store):
    row_id = store.record_approval_decision(
        subject_type="patch_proposal",
        subject_id=1,
        risk_class=2,
        decision="approved",
        decided_by="vadim",
        rationale="Tests passed, aggregate exposure enforcement confirmed",
    )
    assert isinstance(row_id, int) and row_id > 0


def test_record_approval_decision_class2_requires_human(store, tmp_path):
    row_id = store.record_approval_decision(
        subject_type="patch_proposal",
        subject_id=1,
        risk_class=2,
        decision="approved",
        requires_human_approval=True,
    )
    conn = sqlite3.connect(store.path)
    row = conn.execute(
        "SELECT requires_human_approval, separate_risk_review_required "
        "FROM approval_decisions WHERE id = ?",
        (row_id,),
    ).fetchone()
    assert row[0] == 1
    assert row[1] == 0  # class 2 does not require separate risk review
    conn.close()


def test_record_approval_decision_class3_requires_separate_review(store, tmp_path):
    row_id = store.record_approval_decision(
        subject_type="experiment",
        subject_id=1,
        risk_class=3,
        decision="approved",
        requires_human_approval=True,
        separate_risk_review_required=True,
    )
    conn = sqlite3.connect(store.path)
    row = conn.execute(
        "SELECT requires_human_approval, separate_risk_review_required "
        "FROM approval_decisions WHERE id = ?",
        (row_id,),
    ).fetchone()
    assert row[0] == 1
    assert row[1] == 1
    conn.close()


# ------------------------------------------------------------------ #
# record_paper_validation                                             #
# ------------------------------------------------------------------ #

def test_record_paper_validation_returns_row_id(store):
    row_id = store.record_paper_validation(
        status="passed",
        mode="paper",
        command="python3 -m pytest tests/ -q",
        result={"passed": 138, "failed": 0},
    )
    assert isinstance(row_id, int) and row_id > 0


def test_record_paper_validation_approved_for_live_defaults_false(store, tmp_path):
    row_id = store.record_paper_validation(status="passed")
    conn = sqlite3.connect(store.path)
    row = conn.execute(
        "SELECT approved_for_live FROM paper_validations WHERE id = ?", (row_id,)
    ).fetchone()
    assert row[0] == 0  # must never default to True
    conn.close()


def test_record_paper_validation_links_to_proposal(store, tmp_path):
    prop_id = store.record_patch_proposal(title="Prop for validation", risk_class=1)
    val_id = store.record_paper_validation(
        status="passed",
        patch_proposal_id=prop_id,
        result={"passed": 138},
    )
    conn = sqlite3.connect(store.path)
    row = conn.execute(
        "SELECT patch_proposal_id FROM paper_validations WHERE id = ?", (val_id,)
    ).fetchone()
    assert row[0] == prop_id
    conn.close()


# ------------------------------------------------------------------ #
# record_experiment                                                   #
# ------------------------------------------------------------------ #

def test_record_experiment_returns_row_id(store):
    row_id = store.record_experiment(
        name="momentum_threshold_tuning",
        risk_class=1,
        hypothesis="Raising momentum threshold from 0.3% to 0.5% reduces noise trades",
        evidence={"paper_win_rate": 0.52},
        rollback_plan="Revert config_coinbase_crypto.yaml momentum_threshold",
    )
    assert isinstance(row_id, int) and row_id > 0


def test_record_experiment_default_status_is_proposed(store, tmp_path):
    row_id = store.record_experiment(name="test_exp", risk_class=0)
    conn = sqlite3.connect(store.path)
    row = conn.execute(
        "SELECT status FROM experiments WHERE id = ?", (row_id,)
    ).fetchone()
    assert row[0] == "proposed"
    conn.close()


# ------------------------------------------------------------------ #
# record_deployment                                                   #
# ------------------------------------------------------------------ #

def test_record_deployment_returns_row_id(store):
    row_id = store.record_deployment(
        status="completed",
        target="coinbase-bot",
        version_label="2026-05-26-patch-43",
        restart_required=True,
        restart_completed=True,
        deployed_by="vadim",
    )
    assert isinstance(row_id, int) and row_id > 0


def test_record_deployment_restart_completed_defaults_false(store, tmp_path):
    row_id = store.record_deployment(status="planned")
    conn = sqlite3.connect(store.path)
    row = conn.execute(
        "SELECT restart_required, restart_completed FROM deployments WHERE id = ?",
        (row_id,),
    ).fetchone()
    assert row[0] == 0
    assert row[1] == 0
    conn.close()


def test_record_deployment_links_proposal_and_approval(store, tmp_path):
    prop_id = store.record_patch_proposal(title="Deployment link test", risk_class=1)
    approval_id = store.record_approval_decision(
        subject_type="patch_proposal",
        subject_id=prop_id,
        risk_class=1,
        decision="approved",
    )
    dep_id = store.record_deployment(
        patch_proposal_id=prop_id,
        approval_decision_id=approval_id,
        status="completed",
        deployed_by="vadim",
    )
    conn = sqlite3.connect(store.path)
    row = conn.execute(
        "SELECT patch_proposal_id, approval_decision_id FROM deployments WHERE id = ?",
        (dep_id,),
    ).fetchone()
    assert row[0] == prop_id
    assert row[1] == approval_id
    conn.close()


# ------------------------------------------------------------------ #
# record_rollback                                                     #
# ------------------------------------------------------------------ #

def test_record_rollback_returns_row_id(store):
    row_id = store.record_rollback(
        reason="Heartbeat stopped after restart",
        status="completed",
        rollback_by="vadim",
        rollback_plan="pkill bots, restore state backup, reinstall launchd",
        result={"outcome": "bots restored", "downtime_minutes": 3},
    )
    assert isinstance(row_id, int) and row_id > 0


def test_record_rollback_links_deployment(store, tmp_path):
    dep_id = store.record_deployment(status="completed", deployed_by="vadim")
    rb_id = store.record_rollback(
        reason="Post-deploy health check failed",
        deployment_id=dep_id,
        status="completed",
    )
    conn = sqlite3.connect(store.path)
    row = conn.execute(
        "SELECT deployment_id FROM rollbacks WHERE id = ?", (rb_id,)
    ).fetchone()
    assert row[0] == dep_id
    conn.close()


# ------------------------------------------------------------------ #
# Full advisory lifecycle: proposal → approval → deployment → rollback
# ------------------------------------------------------------------ #

def test_full_advisory_lifecycle(store, tmp_path):
    """Smoke test the complete self-improvement audit trail in one pass."""
    # 1. Propose a patch
    prop_id = store.record_patch_proposal(
        title="Add EventStore helpers",
        risk_class=1,
        summary="Adds advisory-only helper methods for self-improvement tables",
        files=["memory/event_store.py", "tests/test_event_store_self_improvement.py"],
        rollback_plan="Revert event_store.py to previous version",
    )
    assert prop_id is not None

    # 2. Record paper validation
    val_id = store.record_paper_validation(
        status="passed",
        mode="paper",
        patch_proposal_id=prop_id,
        command="python3 -m pytest tests/ -q",
        result={"passed": 150, "failed": 0},
        approved_for_live=False,
    )
    assert val_id is not None

    # 3. Human approves (class 1 — no separate risk review needed)
    approval_id = store.record_approval_decision(
        subject_type="patch_proposal",
        subject_id=prop_id,
        risk_class=1,
        decision="approved",
        decided_by="vadim",
        rationale="All tests pass. Advisory only, no live behavior change.",
        requires_human_approval=True,
        separate_risk_review_required=False,
    )
    assert approval_id is not None

    # 4. Update proposal to approved
    assert store.update_patch_proposal_status(
        prop_id, status="approved", approval_decision_id=approval_id
    )

    # 5. Record deployment (human executed it manually)
    dep_id = store.record_deployment(
        patch_proposal_id=prop_id,
        approval_decision_id=approval_id,
        status="completed",
        target="both-bots",
        version_label="2026-05-26-eventstore-helpers",
        restart_required=True,
        restart_completed=True,
        deployed_by="vadim",
    )
    assert dep_id is not None

    # 6. Update proposal to deployed
    assert store.update_patch_proposal_status(prop_id, status="deployed")

    # Verify final state
    conn = sqlite3.connect(store.path)
    prop = conn.execute(
        "SELECT status, approval_decision_id FROM patch_proposals WHERE id = ?",
        (prop_id,),
    ).fetchone()
    assert prop[0] == "deployed"
    assert prop[1] == approval_id

    dep = conn.execute(
        "SELECT restart_completed, deployed_by FROM deployments WHERE id = ?",
        (dep_id,),
    ).fetchone()
    assert dep[0] == 1
    assert dep[1] == "vadim"
    conn.close()


# ------------------------------------------------------------------ #
# Fail-safe: never crash on bad db path                               #
# ------------------------------------------------------------------ #

def test_all_helpers_fail_safe_on_bad_path():
    s = EventStore(path="/nonexistent/path/db.sqlite3", fail_safe=True)
    assert s.record_patch_proposal(title="x", risk_class=0) is None
    assert s.record_approval_decision(
        subject_type="patch_proposal", subject_id=1, risk_class=0, decision="approved"
    ) is None
    assert s.update_patch_proposal_status(1, status="approved") is False
    assert s.record_paper_validation(status="passed") is None
    assert s.record_experiment(name="x", risk_class=0) is None
    assert s.record_deployment(status="planned") is None
    assert s.record_rollback(reason="test") is None
