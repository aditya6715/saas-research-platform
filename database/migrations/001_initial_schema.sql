-- Migration 001: Initial schema
-- Creates all core tables with proper types, constraints, and indexes.

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- ── Schema version tracking ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS schema_versions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    version     INTEGER NOT NULL UNIQUE,
    applied_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    description TEXT    NOT NULL
);

-- ── Research sessions ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS research_sessions (
    id                  TEXT    PRIMARY KEY,
    started_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    completed_at        TEXT,
    total_apps          INTEGER NOT NULL DEFAULT 0,
    completed_apps      INTEGER NOT NULL DEFAULT 0,
    failed_apps         INTEGER NOT NULL DEFAULT 0,
    avg_confidence      REAL,
    human_review_count  INTEGER NOT NULL DEFAULT 0,
    total_api_calls     INTEGER NOT NULL DEFAULT 0,
    cache_hit_ratio     REAL,
    estimated_cost_usd  REAL,
    config_snapshot     TEXT    -- JSON blob
);

-- ── App records ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS apps (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id              TEXT    NOT NULL REFERENCES research_sessions(id),
    app_name                TEXT    NOT NULL,
    seed_url                TEXT,
    category                TEXT,
    description             TEXT,
    auth_methods_json       TEXT    NOT NULL DEFAULT '[]',   -- JSON array
    primary_auth            TEXT,
    oauth_flows_json        TEXT    NOT NULL DEFAULT '[]',   -- JSON array
    access_model            TEXT    CHECK(access_model IN ('Self-Serve','Freemium','Gated') OR access_model IS NULL),
    pricing_tier_for_api    TEXT,
    api_types_json          TEXT    NOT NULL DEFAULT '[]',   -- JSON array
    base_api_url            TEXT,
    api_versioning          TEXT,
    rate_limits             TEXT,
    openapi_url             TEXT,
    graphql_schema_url      TEXT,
    mcp_support             TEXT    CHECK(mcp_support IN ('Official','Community','In-Progress','None') OR mcp_support IS NULL),
    mcp_repo_url            TEXT,
    mcp_last_commit         TEXT,
    buildability_verdict    TEXT    CHECK(buildability_verdict IN ('Fully Buildable','Buildable with Workarounds','Blocked') OR buildability_verdict IS NULL),
    biggest_blocker         TEXT,
    documentation_url       TEXT,
    raw_markdown            TEXT,   -- stored for re-extraction without re-crawl
    confidence_score        REAL    NOT NULL DEFAULT 0.0,
    human_review_required   INTEGER NOT NULL DEFAULT 0,
    human_reviewed_by       TEXT,
    human_reviewed_at       TEXT,
    status                  TEXT    NOT NULL DEFAULT 'pending'
                                CHECK(status IN ('pending','in_progress','completed','failed','verified')),
    retry_count             INTEGER NOT NULL DEFAULT 0,
    last_error              TEXT,
    created_at              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- ── Evidence objects ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS evidence (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    app_id              INTEGER NOT NULL REFERENCES apps(id),
    field_name          TEXT    NOT NULL,
    field_value         TEXT,
    source_url          TEXT    NOT NULL,
    extracted_text      TEXT,
    extraction_method   TEXT,
    confidence          REAL    NOT NULL DEFAULT 0.0,
    verified            INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- ── Verification records ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS verification_records (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    app_id                  INTEGER NOT NULL REFERENCES apps(id),
    field_name              TEXT    NOT NULL,
    pass_a_value            TEXT,
    pass_b_value            TEXT,
    final_value             TEXT,
    agreement               INTEGER NOT NULL DEFAULT 0,
    tiebreaker_used         INTEGER NOT NULL DEFAULT 0,
    tiebreaker_reasoning    TEXT,
    browser_verified        INTEGER NOT NULL DEFAULT 0,
    browser_screenshot_path TEXT,
    confidence_before       REAL,
    confidence_after        REAL,
    verified_at             TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- ── Agent logs ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT    NOT NULL,
    app_id          INTEGER,
    agent_name      TEXT    NOT NULL,
    event_type      TEXT    NOT NULL,
    message         TEXT    NOT NULL,
    metadata_json   TEXT,
    level           TEXT    NOT NULL DEFAULT 'INFO',
    timestamp       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- ── Human reviews ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS human_reviews (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    app_id          INTEGER NOT NULL REFERENCES apps(id),
    field_name      TEXT    NOT NULL,
    original_value  TEXT,
    corrected_value TEXT    NOT NULL,
    reviewer_name   TEXT    NOT NULL,
    reason          TEXT,
    allow_overwrite INTEGER NOT NULL DEFAULT 0,
    reviewed_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- ── Indexes ─────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_apps_session   ON apps(session_id);
CREATE INDEX IF NOT EXISTS idx_apps_status    ON apps(status);
CREATE INDEX IF NOT EXISTS idx_apps_name      ON apps(app_name);
CREATE INDEX IF NOT EXISTS idx_evidence_app   ON evidence(app_id);
CREATE INDEX IF NOT EXISTS idx_evidence_field ON evidence(app_id, field_name);
CREATE INDEX IF NOT EXISTS idx_verif_app      ON verification_records(app_id);
CREATE INDEX IF NOT EXISTS idx_logs_session   ON agent_logs(session_id);
CREATE INDEX IF NOT EXISTS idx_logs_app       ON agent_logs(app_id);
CREATE INDEX IF NOT EXISTS idx_logs_agent     ON agent_logs(agent_name, timestamp);

INSERT INTO schema_versions(version, description) VALUES (1, 'Initial schema');
