"""Corpus Extraction & Temporal Reconciliation Pipeline.

Executes:
Stage 1: Per-meeting extraction of decisions, actions, and numeric evidence.
Stage 2: Per-team temporal reconciliation into SQLite event-sourced memory.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Optional

from meetingos.config import DB_PATH
from meetingos.extraction.meeting_extractor import MeetingExtractor
from meetingos.extraction.reconciler import TemporalReconciler
from meetingos.memory.schema import get_connection
from meetingos.memory.source import SourceMemory

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def run_corpus_extraction(
    db_path: Path = DB_PATH,
    team_filter: Optional[list[str]] = None,
) -> dict[str, int]:
    """
    Execute two-stage extraction across meetings and populate persistent memory.
    """
    conn = get_connection(db_path, readonly=False)
    memory = SourceMemory(conn)
    extractor = MeetingExtractor()
    reconciler = TemporalReconciler(conn)

    teams_rows = conn.execute(
        "SELECT DISTINCT team_id FROM turns ORDER BY team_id ASC"
    ).fetchall()
    all_teams = [r["team_id"] for r in teams_rows]

    if team_filter:
        target_teams = [t for t in all_teams if t in team_filter]
    else:
        target_teams = all_teams

    logger.info(f"Starting two-stage extraction for {len(target_teams)} teams...")

    total_decisions = 0
    total_actions = 0
    total_numerics = 0

    for i, tid in enumerate(target_teams, start=1):
        m_rows = conn.execute(
            "SELECT DISTINCT meeting_id FROM turns WHERE team_id = ? ORDER BY meeting_sequence ASC",
            (tid,),
        ).fetchall()
        meeting_ids = [r["meeting_id"] for r in m_rows]

        team_decisions = []
        team_actions = []
        team_numerics = []

        # Stage 1: Meeting-level extraction
        for mid in meeting_ids:
            m_turns = memory.get_turns_for_meeting(mid)
            decs, acts, nums = extractor.extract_from_meeting_turns(m_turns)
            team_decisions.extend(decs)
            team_actions.extend(acts)
            team_numerics.extend(nums)

        # Stage 2: Temporal reconciliation & persistence
        d_cnt, a_cnt, n_cnt = reconciler.reconcile_team_events(
            team_id=tid,
            candidates_decisions=team_decisions,
            candidates_actions=team_actions,
            candidates_numerics=team_numerics,
        )

        total_decisions += d_cnt
        total_actions += a_cnt
        total_numerics += n_cnt

        if i % 5 == 0 or i == len(target_teams):
            logger.info(
                f"[{i}/{len(target_teams)}] Reconciled {tid}: "
                f"{d_cnt} decisions, {a_cnt} actions, {n_cnt} numerics"
            )

    logger.info(
        f"Corpus extraction complete. Total persisted: "
        f"{total_decisions} decisions, {total_actions} actions, {total_numerics} numerics"
    )

    conn.close()
    return {
        "teams_processed": len(target_teams),
        "total_decisions": total_decisions,
        "total_actions": total_actions,
        "total_numerics": total_numerics,
    }


if __name__ == "__main__":
    run_corpus_extraction()
