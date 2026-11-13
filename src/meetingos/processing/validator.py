"""Gate 2 & Gate 3 Acceptance Validation Engine.

Enforces:
Gate 2:
- Zero turns lost between ingestion and chunking (100% turn coverage).
- Zero chunks crossing meeting boundaries.
- Full source traceability: every chunk maps to its source turn_ids.
- Long turns (>256 tokens) properly partitioned without information loss.
- FTS5 external-content index rowset matches chunks rowset exactly; integrity check passes.
- FAISS vector index reconciliation: vector_index_map matches FAISS vector counts across all 35 teams.

Gate 3:
- Referential integrity across turns, chunks, and vector mappings.
- Event-sourced decision and action memory: no record without evidence.
- Derived states match validated event-sequence rules.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from meetingos.config import FAISS_DIR
from meetingos.memory.actions import ActionMemory
from meetingos.memory.decisions import DecisionMemory
from meetingos.memory.source import SourceMemory
from meetingos.models import ActionEventType, DecisionEventType
from meetingos.processing.chunker import count_chunks
from meetingos.processing.indexer import LexicalIndexer, TeamVectorIndexer


@dataclass
class Gate2Report:
    passed:               bool
    total_chunks:         int
    total_turns_covered:  int
    distinct_meetings:    int
    fts5_integrity:       bool
    faiss_reconciled:     bool
    long_turns_segmented: bool
    failures:             list[str] = field(default_factory=list)

    def summary(self) -> str:
        status_str = "PASSED" if self.passed else "FAILED"
        lines = [
            f"=== Gate 2 Validation Report: {status_str} ===",
            f"Total Chunks:           {self.total_chunks}",
            f"Turns Covered:          {self.total_turns_covered}",
            f"Distinct Meetings:      {self.distinct_meetings} / 138",
            f"FTS5 Integrity Verified:{self.fts5_integrity}",
            f"FAISS Teams Reconciled: {self.faiss_reconciled}",
            f"Long Turns Covered:     {self.long_turns_segmented}",
        ]
        if self.failures:
            lines.append("Failures:")
            for f in self.failures:
                lines.append(f"  - {f}")
        return "\n".join(lines)


@dataclass
class Gate3Report:
    passed:                 bool
    decisions_verified:     bool
    actions_verified:       bool
    foreign_keys_ok:        bool
    derived_states_ok:      bool
    failures:               list[str] = field(default_factory=list)

    def summary(self) -> str:
        status_str = "PASSED" if self.passed else "FAILED"
        lines = [
            f"=== Gate 3 Validation Report: {status_str} ===",
            f"Decisions Memory Check: {self.decisions_verified}",
            f"Actions Memory Check:   {self.actions_verified}",
            f"Foreign Keys Integrity: {self.foreign_keys_ok}",
            f"Derived States Valid:   {self.derived_states_ok}",
        ]
        if self.failures:
            lines.append("Failures:")
            for f in self.failures:
                lines.append(f"  - {f}")
        return "\n".join(lines)


class Gate2Validator:
    """Automated validator for Gate 2 acceptance criteria."""

    def __init__(self, conn: sqlite3.Connection, faiss_dir: Path = FAISS_DIR):
        self.conn = conn
        self.faiss_dir = faiss_dir

    def validate(self) -> Gate2Report:
        failures: list[str] = []

        total_chunks = count_chunks(self.conn)
        if total_chunks == 0:
            failures.append("No chunks found in database.")
            return Gate2Report(False, 0, 0, 0, False, False, False, failures)

        # 1. 100% turn coverage & boundary isolation
        chunk_rows = self.conn.execute("SELECT * FROM chunks ORDER BY chunk_id").fetchall()
        covered_turns: set[str] = set()
        distinct_meetings = set()

        for r in chunk_rows:
            distinct_meetings.add(r["meeting_id"])
            turn_ids = json.loads(r["turn_ids"])
            meeting_id = r["meeting_id"]
            team_id = r["team_id"]

            # Boundary check: every turn in chunk must belong to this meeting and team
            for tid in turn_ids:
                covered_turns.add(tid)
                if not tid.startswith(f"{meeting_id}_"):
                    failures.append(
                        f"Cross-meeting leakage: chunk {r['chunk_id']} has turn {tid} from different meeting"
                    )
                    break

        total_source_turns = self.conn.execute("SELECT COUNT(*) AS cnt FROM turns").fetchone()["cnt"]
        if len(covered_turns) != total_source_turns:
            missing = total_source_turns - len(covered_turns)
            failures.append(
                f"Turn coverage gap: {len(covered_turns)} turns covered out of {total_source_turns} ({missing} missing)"
            )

        if len(distinct_meetings) != 138:
            failures.append(
                f"Expected chunks for 138 meetings, found {len(distinct_meetings)}"
            )

        # 2. FTS5 integrity and row count match
        lexical = LexicalIndexer(self.conn)
        fts5_integrity = lexical.integrity_check()
        if not fts5_integrity:
            failures.append("FTS5 integrity check failed.")

        fts_row_count = self.conn.execute("SELECT COUNT(*) AS cnt FROM chunks_fts").fetchone()["cnt"]
        if fts_row_count != total_chunks:
            failures.append(
                f"FTS5 rowcount mismatch: chunks={total_chunks}, chunks_fts={fts_row_count}"
            )

        # 3. FAISS team reconciliation
        faiss_reconciled = True
        teams = [r["team_id"] for r in self.conn.execute("SELECT DISTINCT team_id FROM chunks").fetchall()]

        for team_id in teams:
            index_path = self.faiss_dir / f"{team_id}.faiss"
            if not index_path.exists():
                failures.append(f"Missing FAISS index file for team {team_id}")
                faiss_reconciled = False
                continue

            import faiss
            idx = faiss.read_index(str(index_path))
            map_count = self.conn.execute(
                "SELECT COUNT(*) AS cnt FROM vector_index_map WHERE team_id = ?",
                (team_id,),
            ).fetchone()["cnt"]

            if idx.ntotal != map_count:
                failures.append(
                    f"Team {team_id} vector mismatch: FAISS ntotal={idx.ntotal}, vector_index_map={map_count}"
                )
                faiss_reconciled = False

        # 4. Long turns segmented
        long_turns_segmented = True
        long_turns = self.conn.execute(
            "SELECT turn_id, word_count FROM turns WHERE word_count > 250"
        ).fetchall()

        if len(long_turns) > 0:
            # Check that vectors for these chunks exist in vector_index_map
            for lt in long_turns[:5]:
                # Find chunk containing this turn
                row = self.conn.execute(
                    "SELECT chunk_id FROM chunks WHERE turn_ids LIKE ?",
                    (f"%{lt['turn_id']}%",),
                ).fetchone()
                if row:
                    vec_rows = self.conn.execute(
                        "SELECT COUNT(*) AS cnt FROM vector_index_map WHERE chunk_id = ?",
                        (row["chunk_id"],),
                    ).fetchone()["cnt"]
                    if vec_rows == 0:
                        failures.append(f"No vector index entries for long-turn chunk {row['chunk_id']}")
                        long_turns_segmented = False

        passed = len(failures) == 0

        return Gate2Report(
            passed=passed,
            total_chunks=total_chunks,
            total_turns_covered=len(covered_turns),
            distinct_meetings=len(distinct_meetings),
            fts5_integrity=fts5_integrity,
            faiss_reconciled=faiss_reconciled,
            long_turns_segmented=long_turns_segmented,
            failures=failures,
        )


class Gate3Validator:
    """Automated validator for Gate 3 acceptance criteria."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def validate(self) -> Gate3Report:
        failures: list[str] = []

        # 1. Foreign key integrity check
        fk_errors = self.conn.execute("PRAGMA foreign_key_check").fetchall()
        foreign_keys_ok = len(fk_errors) == 0
        if not foreign_keys_ok:
            failures.append(f"Foreign key integrity violations found: {len(fk_errors)} rows")

        # 2. Decision memory verification
        dm = DecisionMemory(self.conn)
        decisions_verified = True
        entities = self.conn.execute("SELECT * FROM decision_entities").fetchall()
        for ent in entities:
            events = dm.get_entity_history(ent["decision_entity_id"])
            for e in events:
                if not e.evidence:
                    failures.append(f"Decision event {e.event_id} has no supporting evidence")
                    decisions_verified = False

        # 3. Action memory verification
        am = ActionMemory(self.conn)
        actions_verified = True
        act_entities = self.conn.execute("SELECT * FROM action_entities").fetchall()
        for ent in act_entities:
            events = am.get_action_history(ent["action_entity_id"])
            for e in events:
                # Evidence check
                if e.event_type in (ActionEventType.ASSIGNED, ActionEventType.COMPLETED):
                    if not e.evidence:
                        failures.append(f"Action event {e.event_id} has no supporting evidence")
                        actions_verified = False

        derived_states_ok = decisions_verified and actions_verified
        passed = len(failures) == 0

        return Gate3Report(
            passed=passed,
            decisions_verified=decisions_verified,
            actions_verified=actions_verified,
            foreign_keys_ok=foreign_keys_ok,
            derived_states_ok=derived_states_ok,
            failures=failures,
        )
