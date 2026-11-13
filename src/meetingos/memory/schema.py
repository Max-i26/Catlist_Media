"""SQLite database schema for MeetingOS.

All DDL is here. Never scatter CREATE TABLE statements across modules.
Schema version is tracked; migrations are explicit, never implicit.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

DDL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- -------------------------------------------------------------------------
-- Source memory — the authoritative record
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS turns (
    turn_id           TEXT PRIMARY KEY,
    turn_index        INTEGER NOT NULL,
    meeting_id        TEXT NOT NULL,
    team_id           TEXT NOT NULL,
    meeting_sequence  TEXT NOT NULL,
    meeting_number    INTEGER,
    speaker_id        TEXT NOT NULL,
    timestamp         TEXT,
    timestamp_valid   INTEGER NOT NULL DEFAULT 1,
    text              TEXT NOT NULL,
    word_count        INTEGER NOT NULL,
    byte_offset_start INTEGER NOT NULL,
    byte_offset_end   INTEGER NOT NULL,
    source_file       TEXT NOT NULL,
    source_checksum   TEXT NOT NULL,
    ingested_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_turns_meeting     ON turns(meeting_id);
CREATE INDEX IF NOT EXISTS idx_turns_team        ON turns(team_id);
CREATE INDEX IF NOT EXISTS idx_turns_turn_index  ON turns(turn_index);
CREATE INDEX IF NOT EXISTS idx_turns_speaker     ON turns(team_id, meeting_id, speaker_id);

-- Coverage registry — first-class concept
CREATE TABLE IF NOT EXISTS team_coverage (
    team_id              TEXT PRIMARY KEY,
    expected_sequences   TEXT NOT NULL,  -- JSON array
    available_sequences  TEXT NOT NULL,  -- JSON array
    missing_sequences    TEXT NOT NULL,  -- JSON array
    coverage_status      TEXT NOT NULL CHECK(coverage_status IN ('complete','partial')),
    earliest_available   TEXT NOT NULL,
    latest_available     TEXT NOT NULL,
    total_turns          INTEGER NOT NULL
);

-- -------------------------------------------------------------------------
-- Processing — retrieval units
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS embedding_configs (
    config_id         TEXT PRIMARY KEY,
    embedding_model   TEXT NOT NULL,
    model_revision    TEXT NOT NULL,
    embedding_dim     INTEGER NOT NULL,
    max_seq_length    INTEGER NOT NULL,
    normalization     TEXT NOT NULL,
    chunking_version  TEXT NOT NULL,
    created_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id           TEXT PRIMARY KEY,
    meeting_id         TEXT NOT NULL,
    team_id            TEXT NOT NULL,
    meeting_sequence   TEXT NOT NULL,
    turn_ids           TEXT NOT NULL,   -- JSON array
    speakers           TEXT NOT NULL,   -- JSON array
    start_timestamp    TEXT,
    end_timestamp      TEXT,
    turn_index_start   INTEGER NOT NULL,
    turn_index_end     INTEGER NOT NULL,
    token_count        INTEGER NOT NULL,
    text               TEXT NOT NULL,
    embedding_config_id TEXT NOT NULL,
    FOREIGN KEY(embedding_config_id) REFERENCES embedding_configs(config_id)
);

CREATE INDEX IF NOT EXISTS idx_chunks_meeting  ON chunks(meeting_id);
CREATE INDEX IF NOT EXISTS idx_chunks_team     ON chunks(team_id);
CREATE INDEX IF NOT EXISTS idx_chunks_config   ON chunks(embedding_config_id);

-- FTS5 for lexical BM25 retrieval
-- Uses trigger-maintained external content to stay in sync with chunks table.
-- Note: FTS5 BM25 returns NEGATIVE scores (lower = better rank).
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text,
    content='chunks',
    content_rowid='rowid'
);

-- Maintenance triggers (required for external-content FTS5)
CREATE TRIGGER IF NOT EXISTS chunks_fts_insert
AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, text) VALUES (new.rowid, new.text);
END;

CREATE TRIGGER IF NOT EXISTS chunks_fts_update
AFTER UPDATE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES ('delete', old.rowid, old.text);
    INSERT INTO chunks_fts(rowid, text) VALUES (new.rowid, new.text);
END;

CREATE TRIGGER IF NOT EXISTS chunks_fts_delete
AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES ('delete', old.rowid, old.text);
END;

-- FAISS vector ID → SQLite chunk_id mapping
CREATE TABLE IF NOT EXISTS vector_index_map (
    vector_id  INTEGER NOT NULL,
    chunk_id   TEXT NOT NULL,
    team_id    TEXT NOT NULL,
    config_id  TEXT NOT NULL,
    PRIMARY KEY (team_id, vector_id),
    FOREIGN KEY(chunk_id) REFERENCES chunks(chunk_id)
);

-- -------------------------------------------------------------------------
-- Decision memory — event-sourced (append-only)
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS decision_entities (
    decision_entity_id  TEXT PRIMARY KEY,
    team_id             TEXT NOT NULL,
    topic               TEXT NOT NULL,
    created_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_de_team ON decision_entities(team_id);

-- Immutable event log — never UPDATE, only INSERT
CREATE TABLE IF NOT EXISTS decision_events (
    event_id            TEXT PRIMARY KEY,
    decision_entity_id  TEXT NOT NULL,
    team_id             TEXT NOT NULL,
    meeting_id          TEXT NOT NULL,
    turn_index          INTEGER NOT NULL,
    event_type          TEXT NOT NULL CHECK(event_type IN (
        'proposed','accepted','rejected','superseded',
        'reopened','withdrawn','contradicted','noted','unknown'
    )),
    description         TEXT NOT NULL,
    evidence_turn_ids   TEXT NOT NULL,   -- JSON array of turn_ids
    evidence_quotes     TEXT NOT NULL,   -- JSON array of quote strings
    confidence          TEXT NOT NULL CHECK(confidence IN ('high','medium','low')),
    extracted_at        TEXT NOT NULL,
    FOREIGN KEY(decision_entity_id) REFERENCES decision_entities(decision_entity_id)
);

CREATE INDEX IF NOT EXISTS idx_devt_entity     ON decision_events(decision_entity_id);
CREATE INDEX IF NOT EXISTS idx_devt_team       ON decision_events(team_id);
CREATE INDEX IF NOT EXISTS idx_devt_turn_index ON decision_events(turn_index);

CREATE TABLE IF NOT EXISTS decision_relations (
    relation_id             TEXT PRIMARY KEY,
    source_entity_id        TEXT NOT NULL,
    target_entity_id        TEXT NOT NULL,
    relation_type           TEXT NOT NULL CHECK(relation_type IN (
        'supersedes','contradicts','reopens','clarifies'
    )),
    established_in_meeting  TEXT NOT NULL,
    evidence_turn_ids       TEXT NOT NULL,
    FOREIGN KEY(source_entity_id) REFERENCES decision_entities(decision_entity_id),
    FOREIGN KEY(target_entity_id) REFERENCES decision_entities(decision_entity_id)
);

-- Derived view — NEVER the authoritative record
CREATE VIEW IF NOT EXISTS decision_current_state AS
SELECT
    de.decision_entity_id,
    de.team_id,
    de.topic,
    -- Latest event by turn_index
    (SELECT event_type FROM decision_events
     WHERE decision_entity_id = de.decision_entity_id
     ORDER BY turn_index DESC LIMIT 1) AS latest_event_type,
    -- Last accepted event (may differ from latest event)
    (SELECT meeting_id FROM decision_events
     WHERE decision_entity_id = de.decision_entity_id
       AND event_type = 'accepted'
     ORDER BY turn_index DESC LIMIT 1) AS last_accepted_in,
    -- Is there a withdrawal or rejection after the last acceptance?
    (SELECT COUNT(*) FROM decision_events e2
     WHERE e2.decision_entity_id = de.decision_entity_id
       AND e2.event_type IN ('withdrawn','rejected')
       AND e2.turn_index > COALESCE(
           (SELECT MAX(turn_index) FROM decision_events
            WHERE decision_entity_id = de.decision_entity_id
              AND event_type = 'accepted'), 0
       )) AS post_acceptance_revocations
FROM decision_entities de;

-- -------------------------------------------------------------------------
-- Action memory — event-sourced (append-only)
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS action_entities (
    action_entity_id  TEXT PRIMARY KEY,
    team_id           TEXT NOT NULL,
    description       TEXT NOT NULL,
    created_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS action_events (
    event_id           TEXT PRIMARY KEY,
    action_entity_id   TEXT NOT NULL,
    team_id            TEXT NOT NULL,
    meeting_id         TEXT NOT NULL,
    turn_index         INTEGER NOT NULL,
    event_type         TEXT NOT NULL CHECK(event_type IN (
        'suggested','assigned','reassigned','completed',
        'cancelled','reopened','followed_up','unknown'
    )),
    owner              TEXT,         -- Speaker letter or NULL
    deadline           TEXT,         -- NULL if not stated
    evidence_turn_ids  TEXT NOT NULL,
    evidence_quotes    TEXT NOT NULL,
    confidence         TEXT NOT NULL CHECK(confidence IN ('high','medium','low')),
    extracted_at       TEXT NOT NULL,
    FOREIGN KEY(action_entity_id) REFERENCES action_entities(action_entity_id)
);

CREATE INDEX IF NOT EXISTS idx_aevt_entity ON action_events(action_entity_id);
CREATE INDEX IF NOT EXISTS idx_aevt_team   ON action_events(team_id);

-- -------------------------------------------------------------------------
-- Numeric evidence
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS numeric_evidence (
    numeric_id       TEXT PRIMARY KEY,
    team_id          TEXT NOT NULL,
    meeting_id       TEXT NOT NULL,
    turn_id          TEXT NOT NULL,
    value_text       TEXT NOT NULL,       -- exact transcript string
    normalized_value REAL,                -- for comparison only; NULL if ambiguous
    unit             TEXT,                -- NULL if not stated
    unit_confidence  TEXT NOT NULL CHECK(unit_confidence IN ('explicit','inferred','unknown')),
    context_summary  TEXT,
    FOREIGN KEY(turn_id) REFERENCES turns(turn_id)
);

-- -------------------------------------------------------------------------
-- Agent execution state — checkpoint persistence
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agent_runs (
    run_id              TEXT PRIMARY KEY,
    question_id         TEXT NOT NULL,
    status              TEXT NOT NULL CHECK(status IN (
        'started','planning','retrieving','synthesizing','validating','complete','failed'
    )),
    current_iteration   INTEGER NOT NULL DEFAULT 0,
    sub_questions       TEXT,     -- JSON array
    retrieved_chunk_ids TEXT,     -- JSON array
    tool_call_history   TEXT,     -- JSON array
    error_details       TEXT,
    started_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
"""


def get_connection(db_path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    """Return a configured SQLite connection."""
    uri = f"file:{db_path}{'?mode=ro' if readonly else ''}"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialise_db(db_path: Path) -> sqlite3.Connection:
    """
    Create the database and apply the schema.
    Idempotent: safe to call on an existing database.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(db_path)
    conn.executescript(DDL)
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta(key, value) VALUES (?, ?)",
        ("schema_version", str(SCHEMA_VERSION)),
    )
    conn.commit()
    return conn


def verify_schema_version(conn: sqlite3.Connection) -> bool:
    """Return True if the schema version matches the expected version."""
    row = conn.execute(
        "SELECT value FROM schema_meta WHERE key = 'schema_version'"
    ).fetchone()
    return row is not None and int(row["value"]) == SCHEMA_VERSION
