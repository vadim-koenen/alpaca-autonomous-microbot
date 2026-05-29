"""
SQLite-backed durable event store.

This is intentionally small and fail-safe: trading loop callers should never
crash because memory writes failed.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = ROOT / "memory" / "bot_memory.sqlite3"
SCHEMA_PATH = Path(__file__).with_name("schema.sql")

logger = logging.getLogger("event_store")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json(payload: dict[str, Any] | None) -> str:
    return json.dumps(payload or {}, sort_keys=True, default=str)


class EventStore:
    def __init__(self, path: str | Path | None = None, *, fail_safe: bool = True) -> None:
        self.path = Path(path) if path is not None else DEFAULT_DB_PATH
        self.fail_safe = fail_safe
        self.run_id = ""
        self.config_hash = ""
        self.bot_name = ""
        self.broker = ""
        self.asset_class = ""
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _handle_error(self, action: str, exc: Exception) -> bool:
        if not self.fail_safe:
            raise exc
        logger.warning(f"EventStore {action} failed: {exc}")
        return False

    def _ensure_schema(self) -> bool:
        try:
            schema = SCHEMA_PATH.read_text()
            with self._connect() as conn:
                conn.executescript(schema)
            return True
        except Exception as exc:
            return self._handle_error("schema init", exc)

    def set_context(
        self,
        *,
        run_id: str = "",
        config_hash: str = "",
        bot_name: str = "",
        broker: str = "",
        asset_class: str = "",
    ) -> None:
        if run_id:
            self.run_id = run_id
        if config_hash:
            self.config_hash = config_hash
        if bot_name:
            self.bot_name = bot_name
        if broker:
            self.broker = broker
        if asset_class:
            self.asset_class = asset_class

    def start_run(
        self,
        *,
        bot_name: str,
        broker: str,
        mode: str,
        asset_class: str,
        config_hash: str,
        payload: dict[str, Any] | None = None,
    ) -> str:
        run_id = uuid.uuid4().hex
        self.set_context(
            run_id=run_id,
            config_hash=config_hash,
            bot_name=bot_name,
            broker=broker,
            asset_class=asset_class,
        )
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO bot_runs (
                        id, created_at_utc, bot_name, broker, mode, asset_class,
                        status, config_hash, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        utc_now(),
                        bot_name,
                        broker,
                        mode,
                        asset_class,
                        "running",
                        config_hash,
                        _json(payload),
                    ),
                )
            return run_id
        except Exception as exc:
            self._handle_error("start_run", exc)
            return run_id

    def finish_run(self, *, status: str = "stopped", payload: dict[str, Any] | None = None) -> bool:
        if not self.run_id:
            return True
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE bot_runs
                    SET ended_at_utc = ?, status = ?, payload_json = ?
                    WHERE id = ?
                    """,
                    (utc_now(), status, _json(payload), self.run_id),
                )
            return True
        except Exception as exc:
            return self._handle_error("finish_run", exc)

    def record_event(
        self,
        *,
        event_type: str,
        severity: str = "info",
        broker: str = "",
        asset_class: str = "",
        strategy: str = "",
        symbol: str = "",
        payload: dict[str, Any] | None = None,
        source_component: str = "",
        source_file: str = "",
    ) -> bool:
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO events (
                        created_at_utc, bot_name, broker, asset_class, strategy,
                        symbol, event_type, severity, payload_json,
                        source_component, source_file, run_id, config_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        utc_now(),
                        self.bot_name,
                        broker or self.broker,
                        asset_class or self.asset_class,
                        strategy,
                        symbol,
                        event_type,
                        severity,
                        _json(payload),
                        source_component,
                        source_file,
                        self.run_id,
                        self.config_hash,
                    ),
                )
            return True
        except Exception as exc:
            return self._handle_error("record_event", exc)

    def record_order(
        self,
        *,
        status: str,
        client_order_id: str = "",
        broker_order_id: str = "",
        intent_key: str = "",
        broker: str = "",
        asset_class: str = "",
        strategy: str = "",
        symbol: str = "",
        side: str = "",
        purpose: str = "",
        notional: float = 0.0,
        qty: float = 0.0,
        payload: dict[str, Any] | None = None,
        event_type: str = "order",
        severity: str = "info",
        source_component: str = "",
        source_file: str = "",
    ) -> bool:
        now = utc_now()
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO orders (
                        created_at_utc, updated_at_utc, bot_name, broker,
                        asset_class, strategy, symbol, event_type, severity,
                        client_order_id, broker_order_id, intent_key, side,
                        purpose, notional, qty, status, payload_json,
                        source_component, source_file, run_id, config_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        now,
                        now,
                        self.bot_name,
                        broker or self.broker,
                        asset_class or self.asset_class,
                        strategy,
                        symbol,
                        event_type,
                        severity,
                        client_order_id,
                        broker_order_id,
                        intent_key,
                        side,
                        purpose,
                        notional,
                        qty,
                        status,
                        _json(payload),
                        source_component,
                        source_file,
                        self.run_id,
                        self.config_hash,
                    ),
                )
            return True
        except Exception as exc:
            return self._handle_error("record_order", exc)

    def record_risk_decision(
        self,
        *,
        allowed: bool,
        reason: str,
        broker: str = "",
        asset_class: str = "",
        strategy: str = "",
        symbol: str = "",
        requested_notional: float = 0.0,
        current_exposure: float = 0.0,
        projected_exposure: float = 0.0,
        cap_name: str = "",
        cap_value: float = 0.0,
        daily_loss: float = 0.0,
        consecutive_losses: int = 0,
        payload: dict[str, Any] | None = None,
    ) -> bool:
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO risk_decisions (
                        created_at_utc, bot_name, broker, asset_class, strategy,
                        symbol, allowed, reason, requested_notional,
                        current_exposure, projected_exposure, cap_name, cap_value,
                        daily_loss, consecutive_losses, payload_json,
                        source_component, source_file, run_id, config_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        utc_now(),
                        self.bot_name,
                        broker or self.broker,
                        asset_class or self.asset_class,
                        strategy,
                        symbol,
                        1 if allowed else 0,
                        reason,
                        requested_notional,
                        current_exposure,
                        projected_exposure,
                        cap_name,
                        cap_value,
                        daily_loss,
                        consecutive_losses,
                        _json(payload),
                        "risk_manager",
                        "risk_manager.py",
                        self.run_id,
                        self.config_hash,
                    ),
                )
            return True
        except Exception as exc:
            return self._handle_error("record_risk_decision", exc)

    def record_incident(
        self,
        *,
        severity: str,
        component: str,
        summary: str,
        details: dict[str, Any] | None = None,
        broker: str = "",
        asset_class: str = "",
        source_file: str = "",
    ) -> bool:
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO incidents (
                        created_at_utc, bot_name, broker, asset_class, severity,
                        component, summary, details_json, resolved, source_file,
                        run_id, config_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        utc_now(),
                        self.bot_name,
                        broker or self.broker,
                        asset_class or self.asset_class,
                        severity,
                        component,
                        summary,
                        _json(details),
                        0,
                        source_file,
                        self.run_id,
                        self.config_hash,
                    ),
                )
            return True
        except Exception as exc:
            return self._handle_error("record_incident", exc)

    def record_config_version(
        self,
        *,
        config_file: str,
        config_hash: str,
        mode: str,
        broker: str,
        asset_class: str,
        payload: dict[str, Any] | None = None,
    ) -> bool:
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO config_versions (
                        created_at_utc, bot_name, broker, mode, asset_class,
                        config_file, config_hash, payload_json, run_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        utc_now(),
                        self.bot_name,
                        broker,
                        mode,
                        asset_class,
                        config_file,
                        config_hash,
                        _json(payload),
                        self.run_id,
                    ),
                )
            return True
        except Exception as exc:
            return self._handle_error("record_config_version", exc)

    # ------------------------------------------------------------------ #
    # Self-improvement scaffold helpers — advisory only, no auto-deploy   #
    # ------------------------------------------------------------------ #

    def record_patch_proposal(
        self,
        *,
        title: str,
        risk_class: int,
        summary: str = "",
        files: list[str] | None = None,
        diff_path: str = "",
        evidence: dict[str, Any] | None = None,
        tests: list[str] | None = None,
        rollback_plan: str = "",
        payload: dict[str, Any] | None = None,
    ) -> int | None:
        """Record a proposed patch for advisory tracking.

        Returns the inserted row id so callers can link approval_decisions
        and deployments back to this proposal.  Advisory only — no auto-deploy.
        """
        now = utc_now()
        try:
            with self._connect() as conn:
                cur = conn.execute(
                    """
                    INSERT INTO patch_proposals (
                        created_at_utc, updated_at_utc, title, status, risk_class,
                        summary, files_json, diff_path, evidence_json, tests_json,
                        rollback_plan, payload_json, run_id, config_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        now, now, title, "proposed", risk_class,
                        summary,
                        json.dumps(files or [], sort_keys=True),
                        diff_path,
                        _json(evidence),
                        json.dumps(tests or [], sort_keys=True),
                        rollback_plan,
                        _json(payload),
                        self.run_id,
                        self.config_hash,
                    ),
                )
                return cur.lastrowid
        except Exception as exc:
            self._handle_error("record_patch_proposal", exc)
            return None

    def update_patch_proposal_status(
        self,
        proposal_id: int,
        *,
        status: str,
        approval_decision_id: int | None = None,
    ) -> bool:
        """Advance a patch proposal through its lifecycle states.

        Valid status values: proposed → approved / rejected → deployed / rolled_back.
        """
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE patch_proposals
                    SET updated_at_utc = ?,
                        status = ?,
                        approval_decision_id = COALESCE(?, approval_decision_id)
                    WHERE id = ?
                    """,
                    (utc_now(), status, approval_decision_id, proposal_id),
                )
            return True
        except Exception as exc:
            return self._handle_error("update_patch_proposal_status", exc)

    def record_approval_decision(
        self,
        *,
        subject_type: str,
        subject_id: int,
        risk_class: int,
        decision: str,
        decided_by: str = "human",
        rationale: str = "",
        requires_human_approval: bool = True,
        separate_risk_review_required: bool = False,
        payload: dict[str, Any] | None = None,
    ) -> int | None:
        """Record a human approval or rejection decision.

        Class 2 (trading safety) always requires_human_approval.
        Class 3 (strategy/risk expansion) also requires separate_risk_review.
        Returns the inserted row id for linking to deployments.
        """
        try:
            with self._connect() as conn:
                cur = conn.execute(
                    """
                    INSERT INTO approval_decisions (
                        created_at_utc, subject_type, subject_id, risk_class,
                        decision, decided_by, requires_human_approval,
                        separate_risk_review_required, rationale,
                        payload_json, run_id, config_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        utc_now(), subject_type, subject_id, risk_class,
                        decision, decided_by,
                        1 if requires_human_approval else 0,
                        1 if separate_risk_review_required else 0,
                        rationale,
                        _json(payload),
                        self.run_id,
                        self.config_hash,
                    ),
                )
                return cur.lastrowid
        except Exception as exc:
            self._handle_error("record_approval_decision", exc)
            return None

    def record_paper_validation(
        self,
        *,
        status: str,
        mode: str = "paper",
        patch_proposal_id: int | None = None,
        experiment_id: int | None = None,
        broker: str = "",
        asset_class: str = "",
        command: str = "",
        result: dict[str, Any] | None = None,
        approved_for_live: bool = False,
        payload: dict[str, Any] | None = None,
    ) -> int | None:
        """Record a paper or dry-run validation outcome.

        approved_for_live must be set explicitly and never defaults to True.
        Returns row id for linking back to experiments or patch proposals.
        """
        try:
            with self._connect() as conn:
                cur = conn.execute(
                    """
                    INSERT INTO paper_validations (
                        created_at_utc, patch_proposal_id, experiment_id, mode,
                        broker, asset_class, command, status, result_json,
                        approved_for_live, payload_json, run_id, config_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        utc_now(), patch_proposal_id, experiment_id, mode,
                        broker or self.broker,
                        asset_class or self.asset_class,
                        command, status,
                        _json(result),
                        1 if approved_for_live else 0,
                        _json(payload),
                        self.run_id,
                        self.config_hash,
                    ),
                )
                return cur.lastrowid
        except Exception as exc:
            self._handle_error("record_paper_validation", exc)
            return None

    def record_experiment(
        self,
        *,
        name: str,
        risk_class: int,
        hypothesis: str = "",
        evidence: dict[str, Any] | None = None,
        rollback_plan: str = "",
        payload: dict[str, Any] | None = None,
    ) -> int | None:
        """Record an experiment proposal.

        Experiments start in 'proposed' status and require human approval
        before any live action if risk_class >= 2.  Advisory only.
        """
        now = utc_now()
        try:
            with self._connect() as conn:
                cur = conn.execute(
                    """
                    INSERT INTO experiments (
                        created_at_utc, updated_at_utc, name, status, risk_class,
                        hypothesis, evidence_json, rollback_plan,
                        payload_json, run_id, config_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        now, now, name, "proposed", risk_class,
                        hypothesis,
                        _json(evidence),
                        rollback_plan,
                        _json(payload),
                        self.run_id,
                        self.config_hash,
                    ),
                )
                return cur.lastrowid
        except Exception as exc:
            self._handle_error("record_experiment", exc)
            return None

    def record_deployment(
        self,
        *,
        patch_proposal_id: int | None = None,
        approval_decision_id: int | None = None,
        status: str = "planned",
        target: str = "",
        version_label: str = "",
        restart_required: bool = False,
        restart_completed: bool = False,
        deployed_by: str = "human",
        payload: dict[str, Any] | None = None,
    ) -> int | None:
        """Record a deployment event for audit history.

        This is advisory — it records THAT a deployment happened (after a
        human approved and manually executed it).  It does NOT deploy code,
        restart bots, or place broker orders.
        """
        try:
            with self._connect() as conn:
                cur = conn.execute(
                    """
                    INSERT INTO deployments (
                        created_at_utc, patch_proposal_id, approval_decision_id,
                        deployed_by, status, target, version_label,
                        restart_required, restart_completed,
                        payload_json, run_id, config_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        utc_now(),
                        patch_proposal_id,
                        approval_decision_id,
                        deployed_by,
                        status,
                        target,
                        version_label,
                        1 if restart_required else 0,
                        1 if restart_completed else 0,
                        _json(payload),
                        self.run_id,
                        self.config_hash,
                    ),
                )
                return cur.lastrowid
        except Exception as exc:
            self._handle_error("record_deployment", exc)
            return None

    def record_rollback(
        self,
        *,
        reason: str,
        deployment_id: int | None = None,
        patch_proposal_id: int | None = None,
        status: str = "planned",
        rollback_by: str = "human",
        rollback_plan: str = "",
        result: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> int | None:
        """Record a rollback event for audit history.

        Advisory — records THAT a rollback was decided/executed by a human.
        Does NOT perform the rollback, restart bots, or touch broker state.
        """
        try:
            with self._connect() as conn:
                cur = conn.execute(
                    """
                    INSERT INTO rollbacks (
                        created_at_utc, deployment_id, patch_proposal_id,
                        reason, status, rollback_by, rollback_plan,
                        result_json, payload_json, run_id, config_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        utc_now(),
                        deployment_id,
                        patch_proposal_id,
                        reason,
                        status,
                        rollback_by,
                        rollback_plan,
                        _json(result),
                        _json(payload),
                        self.run_id,
                        self.config_hash,
                    ),
                )
                return cur.lastrowid
        except Exception as exc:
            self._handle_error("record_rollback", exc)
            return None


_event_store: EventStore | None = None


def get_event_store(path: str | Path | None = None) -> EventStore:
    global _event_store
    if _event_store is None or path is not None:
        _event_store = EventStore(path)
    return _event_store


def configure_event_store(path: str | Path | None = None, *, fail_safe: bool = True) -> EventStore:
    global _event_store
    _event_store = EventStore(path, fail_safe=fail_safe)
    return _event_store
