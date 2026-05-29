PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS bot_runs (
    id TEXT PRIMARY KEY,
    created_at_utc TEXT NOT NULL,
    ended_at_utc TEXT,
    bot_name TEXT,
    broker TEXT,
    mode TEXT,
    asset_class TEXT,
    status TEXT,
    config_hash TEXT,
    payload_json TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at_utc TEXT NOT NULL,
    bot_name TEXT,
    broker TEXT,
    asset_class TEXT,
    strategy TEXT,
    symbol TEXT,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'info',
    payload_json TEXT,
    source_component TEXT,
    source_file TEXT,
    run_id TEXT,
    config_hash TEXT
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    bot_name TEXT,
    broker TEXT,
    asset_class TEXT,
    strategy TEXT,
    symbol TEXT,
    event_type TEXT,
    severity TEXT,
    client_order_id TEXT,
    broker_order_id TEXT,
    intent_key TEXT,
    side TEXT,
    purpose TEXT,
    notional REAL,
    qty REAL,
    status TEXT,
    payload_json TEXT,
    source_component TEXT,
    source_file TEXT,
    run_id TEXT,
    config_hash TEXT
);

CREATE TABLE IF NOT EXISTS fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at_utc TEXT NOT NULL,
    bot_name TEXT,
    broker TEXT,
    asset_class TEXT,
    strategy TEXT,
    symbol TEXT,
    client_order_id TEXT,
    broker_order_id TEXT,
    fill_price REAL,
    qty REAL,
    notional REAL,
    fees REAL,
    payload_json TEXT,
    run_id TEXT,
    config_hash TEXT
);

CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT,
    bot_name TEXT,
    broker TEXT,
    asset_class TEXT,
    strategy TEXT,
    symbol TEXT,
    status TEXT,
    qty REAL,
    notional REAL,
    entry_price REAL,
    payload_json TEXT,
    run_id TEXT,
    config_hash TEXT
);

CREATE TABLE IF NOT EXISTS risk_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at_utc TEXT NOT NULL,
    bot_name TEXT,
    broker TEXT,
    asset_class TEXT,
    strategy TEXT,
    symbol TEXT,
    allowed INTEGER NOT NULL,
    reason TEXT,
    requested_notional REAL,
    current_exposure REAL,
    projected_exposure REAL,
    cap_name TEXT,
    cap_value REAL,
    daily_loss REAL,
    consecutive_losses INTEGER,
    payload_json TEXT,
    source_component TEXT,
    source_file TEXT,
    run_id TEXT,
    config_hash TEXT
);

CREATE TABLE IF NOT EXISTS strategy_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at_utc TEXT NOT NULL,
    bot_name TEXT,
    broker TEXT,
    asset_class TEXT,
    strategy TEXT,
    symbol TEXT,
    signal TEXT,
    confidence REAL,
    payload_json TEXT,
    run_id TEXT,
    config_hash TEXT
);

CREATE TABLE IF NOT EXISTS broker_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at_utc TEXT NOT NULL,
    bot_name TEXT,
    broker TEXT,
    asset_class TEXT,
    equity REAL,
    buying_power REAL,
    payload_json TEXT,
    run_id TEXT,
    config_hash TEXT
);

CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at_utc TEXT NOT NULL,
    bot_name TEXT,
    broker TEXT,
    asset_class TEXT,
    severity TEXT NOT NULL,
    component TEXT,
    summary TEXT NOT NULL,
    details_json TEXT,
    resolved INTEGER NOT NULL DEFAULT 0,
    resolved_at_utc TEXT,
    source_file TEXT,
    run_id TEXT,
    config_hash TEXT
);

CREATE TABLE IF NOT EXISTS config_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at_utc TEXT NOT NULL,
    bot_name TEXT,
    broker TEXT,
    mode TEXT,
    asset_class TEXT,
    config_file TEXT,
    config_hash TEXT NOT NULL,
    payload_json TEXT,
    run_id TEXT
);

CREATE TABLE IF NOT EXISTS daily_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at_utc TEXT NOT NULL,
    summary_date TEXT NOT NULL,
    markdown_path TEXT,
    json_path TEXT,
    payload_json TEXT
);

CREATE TABLE IF NOT EXISTS recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at_utc TEXT NOT NULL,
    bot_name TEXT,
    broker TEXT,
    asset_class TEXT,
    severity TEXT,
    recommendation TEXT NOT NULL,
    rationale_json TEXT,
    approved INTEGER NOT NULL DEFAULT 0,
    run_id TEXT,
    config_hash TEXT
);

CREATE TABLE IF NOT EXISTS experiments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'proposed',
    risk_class INTEGER NOT NULL,
    hypothesis TEXT,
    evidence_json TEXT,
    test_result_json TEXT,
    paper_validation_id INTEGER,
    approval_decision_id INTEGER,
    rollback_plan TEXT,
    payload_json TEXT,
    run_id TEXT,
    config_hash TEXT
);

CREATE TABLE IF NOT EXISTS patch_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'proposed',
    risk_class INTEGER NOT NULL,
    summary TEXT,
    files_json TEXT,
    diff_path TEXT,
    evidence_json TEXT,
    tests_json TEXT,
    approval_decision_id INTEGER,
    rollback_plan TEXT,
    payload_json TEXT,
    run_id TEXT,
    config_hash TEXT
);

CREATE TABLE IF NOT EXISTS paper_validations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at_utc TEXT NOT NULL,
    patch_proposal_id INTEGER,
    experiment_id INTEGER,
    mode TEXT NOT NULL DEFAULT 'paper',
    broker TEXT,
    asset_class TEXT,
    command TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    result_json TEXT,
    approved_for_live INTEGER NOT NULL DEFAULT 0,
    payload_json TEXT,
    run_id TEXT,
    config_hash TEXT
);

CREATE TABLE IF NOT EXISTS deployments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at_utc TEXT NOT NULL,
    patch_proposal_id INTEGER,
    approval_decision_id INTEGER,
    deployed_by TEXT,
    status TEXT NOT NULL DEFAULT 'planned',
    target TEXT,
    version_label TEXT,
    restart_required INTEGER NOT NULL DEFAULT 0,
    restart_completed INTEGER NOT NULL DEFAULT 0,
    payload_json TEXT,
    run_id TEXT,
    config_hash TEXT
);

CREATE TABLE IF NOT EXISTS rollbacks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at_utc TEXT NOT NULL,
    deployment_id INTEGER,
    patch_proposal_id INTEGER,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'planned',
    rollback_by TEXT,
    rollback_plan TEXT,
    result_json TEXT,
    payload_json TEXT,
    run_id TEXT,
    config_hash TEXT
);

CREATE TABLE IF NOT EXISTS approval_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at_utc TEXT NOT NULL,
    subject_type TEXT NOT NULL,
    subject_id INTEGER,
    risk_class INTEGER NOT NULL,
    decision TEXT NOT NULL,
    decided_by TEXT,
    requires_human_approval INTEGER NOT NULL DEFAULT 1,
    separate_risk_review_required INTEGER NOT NULL DEFAULT 0,
    rationale TEXT,
    payload_json TEXT,
    run_id TEXT,
    config_hash TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at_utc);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_orders_intent ON orders(intent_key);
CREATE INDEX IF NOT EXISTS idx_orders_client_order_id ON orders(client_order_id);
CREATE INDEX IF NOT EXISTS idx_risk_created ON risk_decisions(created_at_utc);
CREATE INDEX IF NOT EXISTS idx_incidents_created ON incidents(created_at_utc);
CREATE INDEX IF NOT EXISTS idx_experiments_status ON experiments(status);
CREATE INDEX IF NOT EXISTS idx_patch_proposals_status ON patch_proposals(status);
CREATE INDEX IF NOT EXISTS idx_approval_subject ON approval_decisions(subject_type, subject_id);
