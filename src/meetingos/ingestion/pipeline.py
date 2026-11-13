"""Gate 1 Ingestion Pipeline Orchestrator.

Runs deterministic ingestion, writes to SQLite, produces manifest,
and enforces Gate 1 acceptance validation.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from meetingos.config import DB_PATH, OUTPUTS_DIR, TRANSCRIPTS_DIR
from meetingos.ingestion.manifest import IngestionManifest, create_manifest
from meetingos.ingestion.parser import (
    build_coverage_registry,
    discover_transcripts,
    parse_transcript,
    run_gate1_checks,
)
from meetingos.ingestion.validator import Gate1Report, Gate1Validator
from meetingos.memory.schema import initialise_db
from meetingos.memory.source import SourceMemory


def run_ingestion_pipeline(
    transcripts_dir: Path | None = None,
    db_path: Path | None = None,
    manifest_path: Path | None = None,
    raise_on_failure: bool = True,
) -> tuple[SourceMemory, IngestionManifest, Gate1Report]:
    """
    Execute the complete Gate 1 pipeline.

    1. Parse all transcripts
    2. Build coverage registry
    3. Initialize SQLite database & store turns + coverage
    4. Generate and save ingestion manifest JSON
    5. Run Gate 1 validator
    """
    t_dir = transcripts_dir or TRANSCRIPTS_DIR
    target_db = db_path or DB_PATH
    target_manifest = manifest_path or (OUTPUTS_DIR / "ingestion_manifest.json")

    # Step 1: Discover and parse
    files = discover_transcripts(t_dir)
    meetings = [parse_transcript(f) for f in files]

    # Step 2: Coverage registry
    coverage = build_coverage_registry(meetings)

    # Step 3: Run pre-DB Gate 1 parser checks
    pre_failures = run_gate1_checks(files, meetings, coverage)
    if pre_failures and raise_on_failure:
        raise AssertionError(f"Pre-ingestion parser checks failed:\n" + "\n".join(pre_failures))

    # Step 4: Initialise DB and persist source memory
    conn = initialise_db(target_db)
    memory = SourceMemory(conn)
    memory.save_meetings(meetings, coverage)

    # Step 5: Generate and write manifest
    manifest = create_manifest(meetings, coverage)
    manifest.to_json_file(target_manifest)

    # Step 6: Validate Gate 1
    validator = Gate1Validator(memory, manifest)
    report = validator.validate()

    if not report.passed and raise_on_failure:
        raise AssertionError(
            f"Gate 1 acceptance validation failed:\n{report.summary()}"
        )

    return memory, manifest, report
