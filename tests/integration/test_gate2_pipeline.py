"""Integration tests for Gate 2 and Gate 3 processing pipeline."""
from __future__ import annotations

import tempfile
from pathlib import Path
import pytest

from meetingos.config import DB_PATH, FAISS_DIR
from meetingos.memory.schema import get_connection, initialise_db
from meetingos.memory.source import SourceMemory
from meetingos.processing.pipeline import run_processing_pipeline
from meetingos.processing.validator import Gate2Validator, Gate3Validator


@pytest.fixture(scope="module")
def gate2_results():
    if not DB_PATH.exists() or not FAISS_DIR.exists():
        pytest.skip("Gate 2 artifacts not present. Run processing first.")

    conn = get_connection(DB_PATH, readonly=False)
    validator = Gate2Validator(conn, FAISS_DIR)
    report = validator.validate()
    chunks_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    vectors_count = conn.execute("SELECT COUNT(*) FROM vector_index_map").fetchone()[0]
    conn.close()

    return chunks_count, vectors_count, report, FAISS_DIR


class TestGate2PipelineIntegration:

    def test_gate2_report_passes(self, gate2_results) -> None:
        _, _, report, _ = gate2_results
        assert report.passed, f"Gate 2 report failed:\n{report.summary()}"
        assert report.failures == []

    def test_chunk_and_turn_accounting(self, gate2_results) -> None:
        chunks_count, _, report, _ = gate2_results
        assert report.total_chunks > 10000, f"Expected >10K chunks for w5_s3, got {chunks_count}"
        assert report.distinct_meetings == 138
        assert report.total_turns_covered == 48148

    def test_fts5_integrity(self, gate2_results) -> None:
        _, _, report, _ = gate2_results
        assert report.fts5_integrity is True

    def test_faiss_all_teams_reconciled(self, gate2_results) -> None:
        _, _, report, _ = gate2_results
        assert report.faiss_reconciled is True

    def test_gate3_validation(self, gate2_results) -> None:
        conn = get_connection(DB_PATH, readonly=True)
        validator = Gate3Validator(conn)
        report = validator.validate()
        conn.close()

        assert report.passed, f"Gate 3 validation failed:\n{report.summary()}"
        assert report.foreign_keys_ok is True
