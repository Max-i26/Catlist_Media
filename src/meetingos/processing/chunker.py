"""Hierarchical conversation chunker.

Turn-boundary-aware sliding window segmentation.
Preserves speaker turns as atomic units; groups adjacent turns into retrieval units.
Never splits turns mid-sentence at the chunk level.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Optional

from meetingos.models import Chunk, Turn


def format_chunk_text(turns: list[Turn]) -> str:
    """Format turns into clean readable conversational text with speaker tags."""
    formatted_lines = []
    for t in turns:
        ts = t.timestamp or "00:00:00"
        formatted_lines.append(f"[{ts}] Speaker {t.speaker_id}: {t.text}")
    return "\n".join(formatted_lines)


def estimate_tokens(text: str) -> int:
    """Fast, reliable token estimate (~1.3 tokens per whitespace-separated word)."""
    words = len(text.split())
    return max(1, int(words * 1.3))


def chunk_meeting_turns(
    turns: list[Turn],
    window_size: int = 5,
    stride: int = 3,
    config_id: str = "default_config",
) -> list[Chunk]:
    """
    Segment a meeting's turns into overlapping sliding windows.

    Rules:
    - Never split a speaker turn across chunks (atomic turn preservation).
    - Window advances by `stride` turns.
    - Captures metadata: turn_ids, distinct speakers, timestamps, turn_index range.
    - Zero cross-meeting contamination (input must belong to a single meeting).
    """
    if not turns:
        return []

    meeting_id = turns[0].meeting_id
    team_id = turns[0].team_id
    meeting_sequence = turns[0].meeting_sequence

    chunks: list[Chunk] = []
    chunk_seq = 1

    total_turns = len(turns)

    if total_turns <= window_size:
        # Meeting has fewer turns than window size: single chunk
        chunk_text = format_chunk_text(turns)
        chunks.append(Chunk(
            chunk_id=f"{meeting_id}_chunk_{chunk_seq:04d}",
            meeting_id=meeting_id,
            team_id=team_id,
            meeting_sequence=meeting_sequence,
            turn_ids=[t.turn_id for t in turns],
            speakers=sorted(list({t.speaker_id for t in turns})),
            start_timestamp=turns[0].timestamp,
            end_timestamp=turns[-1].timestamp,
            turn_index_start=turns[0].turn_index,
            turn_index_end=turns[-1].turn_index,
            token_count=estimate_tokens(chunk_text),
            text=chunk_text,
            embedding_config_id=config_id,
        ))
        return chunks

    start_idx = 0
    while start_idx < total_turns:
        end_idx = min(start_idx + window_size, total_turns)
        window_turns = turns[start_idx:end_idx]

        # If a trailing window has too few turns and we already have chunks,
        # merge with previous or adjust so every turn is covered
        if len(window_turns) < 2 and chunks:
            # Last turn is already covered in previous window if stride < window_size
            if window_turns[-1].turn_id in chunks[-1].turn_ids:
                break

        chunk_text = format_chunk_text(window_turns)
        chunks.append(Chunk(
            chunk_id=f"{meeting_id}_chunk_{chunk_seq:04d}",
            meeting_id=meeting_id,
            team_id=team_id,
            meeting_sequence=meeting_sequence,
            turn_ids=[t.turn_id for t in window_turns],
            speakers=sorted(list({t.speaker_id for t in window_turns})),
            start_timestamp=window_turns[0].timestamp,
            end_timestamp=window_turns[-1].timestamp,
            turn_index_start=window_turns[0].turn_index,
            turn_index_end=window_turns[-1].turn_index,
            token_count=estimate_tokens(chunk_text),
            text=chunk_text,
            embedding_config_id=config_id,
        ))
        chunk_seq += 1

        if end_idx == total_turns:
            break

        start_idx += stride

    return chunks


def save_chunks_to_db(chunks: list[Chunk], conn: sqlite3.Connection) -> int:
    """
    Store chunks into the SQLite chunks table.
    FTS5 triggers automatically maintain chunks_fts.
    """
    rows_to_insert = [
        (
            c.chunk_id,
            c.meeting_id,
            c.team_id,
            c.meeting_sequence,
            json.dumps(c.turn_ids),
            json.dumps(c.speakers),
            c.start_timestamp,
            c.end_timestamp,
            c.turn_index_start,
            c.turn_index_end,
            c.token_count,
            c.text,
            c.embedding_config_id,
        )
        for c in chunks
    ]

    with conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO chunks (
                chunk_id, meeting_id, team_id, meeting_sequence, turn_ids,
                speakers, start_timestamp, end_timestamp, turn_index_start,
                turn_index_end, token_count, text, embedding_config_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows_to_insert,
        )

    return len(rows_to_insert)


def get_chunks_for_meeting(meeting_id: str, conn: sqlite3.Connection) -> list[Chunk]:
    """Fetch all chunks for a meeting from SQLite."""
    rows = conn.execute(
        "SELECT * FROM chunks WHERE meeting_id = ? ORDER BY turn_index_start ASC",
        (meeting_id,),
    ).fetchall()
    return [_row_to_chunk(r) for r in rows]


def get_chunks_for_team(team_id: str, conn: sqlite3.Connection) -> list[Chunk]:
    """Fetch all chunks for a team across all meetings from SQLite."""
    rows = conn.execute(
        "SELECT * FROM chunks WHERE team_id = ? ORDER BY turn_index_start ASC",
        (team_id,),
    ).fetchall()
    return [_row_to_chunk(r) for r in rows]


def count_chunks(conn: sqlite3.Connection) -> int:
    """Return total number of chunks stored in SQLite."""
    row = conn.execute("SELECT COUNT(*) AS cnt FROM chunks").fetchone()
    return row["cnt"]


def _row_to_chunk(row: sqlite3.Row) -> Chunk:
    return Chunk(
        chunk_id=row["chunk_id"],
        meeting_id=row["meeting_id"],
        team_id=row["team_id"],
        meeting_sequence=row["meeting_sequence"],
        turn_ids=json.loads(row["turn_ids"]),
        speakers=json.loads(row["speakers"]),
        start_timestamp=row["start_timestamp"],
        end_timestamp=row["end_timestamp"],
        turn_index_start=row["turn_index_start"],
        turn_index_end=row["turn_index_end"],
        token_count=row["token_count"],
        text=row["text"],
        embedding_config_id=row["embedding_config_id"],
    )
