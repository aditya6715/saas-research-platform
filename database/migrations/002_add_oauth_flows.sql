-- Migration 002: Add raw_markdown column if not already present (safe no-op if exists)
-- SQLite doesn't support IF NOT EXISTS on columns; use a try-catch approach via migration versioning.

-- Add retry_count to apps if this is a fresh migration path
-- (these columns are already in migration 001; this is a placeholder for future schema work)

INSERT OR IGNORE INTO schema_versions(version, description) VALUES (2, 'OAuth flows and retry tracking — already included in 001');
