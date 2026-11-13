"""Milestone 2 Processing Pipeline Orchestrator.

Executes:
1. Turn-boundary-aware hierarchical conversation chunking across all 138 meetings.
2. Embedding configuration versioning and persistence.
3. FTS5 BM25 index synchronization, rebuild, and integrity checking.
4. Pre-retrieval team-isolated FAISS vector index construction and persistence for all 35 teams.
5. Gate 2 automated acceptance validation.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Optional

from meetingos.config import (
    DEFAULT_CHUNK_WINDOW,
    CHUNK_STRIDE,
    DB_PATH,
    FAISS_DIR,
)
from meetingos.memory.schema import get_connection
from meetingos.memory.source import SourceMemory
from meetingos.models import Chunk, EmbeddingConfig
from meetingos.processing.chunker import chunk_meeting_turns, save_chunks_to_db
from meetingos.processing.embedder import TextEmbedder, save_embedding_config
from meetingos.processing.indexer import LexicalIndexer, TeamVectorIndexer
from meetingos.processing.validator import Gate2Report, Gate2Validator


def run_processing_pipeline(
    db_path: Path | None = None,
    faiss_dir: Path | None = None,
    window_size: int = DEFAULT_CHUNK_WINDOW,
    stride: int = CHUNK_STRIDE,
    use_mock_embedder: bool = False,
    raise_on_failure: bool = True,
) -> tuple[int, int, Gate2Report]:
    """
    Execute Milestone 2 conversation processing and indexing.

    Returns:
        (total_chunks_created, total_vectors_indexed, gate2_report)
    """
    target_db = db_path or DB_PATH
    target_faiss_dir = faiss_dir or FAISS_DIR
    target_faiss_dir.mkdir(parents=True, exist_ok=True)

    conn = get_connection(target_db)
    memory = SourceMemory(conn)

    # Step 1: Embedding configuration
    embedder = TextEmbedder(lazy_load=False, use_mock=use_mock_embedder)
    config = embedder.create_config_record(
        chunking_version=f"w{window_size}_s{stride}_v1",
        model_revision="main",
    )
    save_embedding_config(config, conn)

    # Step 2: Chunk all 138 meetings
    distinct_meeting_ids = [
        r["meeting_id"]
        for r in conn.execute("SELECT DISTINCT meeting_id FROM turns ORDER BY turn_index ASC").fetchall()
    ]

    all_chunks: list[Chunk] = []
    for mid in distinct_meeting_ids:
        m_turns = memory.get_turns_for_meeting(mid)
        chunks = chunk_meeting_turns(
            turns=m_turns,
            window_size=window_size,
            stride=stride,
            config_id=config.config_id,
        )
        all_chunks.extend(chunks)

    # Step 3: Persist chunks into SQLite (FTS5 triggers update automatically)
    save_chunks_to_db(all_chunks, conn)

    # Step 4: Rebuild & verify FTS5
    lexical = LexicalIndexer(conn)
    lexical.rebuild()
    if not lexical.integrity_check():
        raise RuntimeError("FTS5 integrity check failed after rebuild")

    # Step 5: Build per-team FAISS indexes
    vector_indexer = TeamVectorIndexer(conn, embedder, index_dir=target_faiss_dir)
    teams = [
        r["team_id"]
        for r in conn.execute("SELECT DISTINCT team_id FROM chunks ORDER BY team_id ASC").fetchall()
    ]

    total_vectors = 0
    chunks_by_team: dict[str, list[Chunk]] = {}
    for c in all_chunks:
        chunks_by_team.setdefault(c.team_id, []).append(c)

    for team_id in teams:
        team_chunks = chunks_by_team.get(team_id, [])
        idx = vector_indexer.build_team_index(team_id, team_chunks, config)
        vector_indexer.save_team_index(team_id)
        total_vectors += idx.ntotal

    # Step 6: Validate Gate 2
    validator = Gate2Validator(conn, faiss_dir=target_faiss_dir)
    report = validator.validate()

    conn.close()

    if not report.passed and raise_on_failure:
        raise AssertionError(
            f"Gate 2 acceptance validation failed:\n{report.summary()}"
        )

    return len(all_chunks), total_vectors, report
