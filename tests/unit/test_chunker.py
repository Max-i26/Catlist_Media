"""Unit tests for conversation chunker."""
from __future__ import annotations

import sqlite3
import pytest

from meetingos.models import Turn
from meetingos.processing.chunker import (
    chunk_meeting_turns,
    count_chunks,
    format_chunk_text,
    get_chunks_for_meeting,
    save_chunks_to_db,
)


def make_turn(turn_idx: int, speaker: str, text: str, meeting_id: str = "ES2008b") -> Turn:
    return Turn(
        turn_id=f"{meeting_id}_{speaker}_{turn_idx+1:04d}",
        turn_index=turn_idx,
        meeting_id=meeting_id,
        team_id=meeting_id[:-1],
        meeting_sequence=meeting_id[-1],
        meeting_number=2,
        speaker_id=speaker,
        timestamp=f"00:{turn_idx:02d}:00",
        timestamp_valid=True,
        text=text,
        word_count=len(text.split()),
        byte_offset_start=0,
        byte_offset_end=10,
        source_file="dummy.txt",
        source_checksum="abc",
        ingested_at="2026-01-01T00:00:00",
    )


class TestChunker:

    def test_single_window_if_turns_leq_window_size(self) -> None:
        turns = [
            make_turn(0, "A", "Turn zero text."),
            make_turn(1, "B", "Turn one text."),
            make_turn(2, "C", "Turn two text."),
        ]
        chunks = chunk_meeting_turns(turns, window_size=5, stride=3)
        assert len(chunks) == 1
        assert chunks[0].turn_ids == [t.turn_id for t in turns]
        assert chunks[0].speakers == ["A", "B", "C"]
        assert chunks[0].turn_index_start == 0
        assert chunks[0].turn_index_end == 2

    def test_sliding_window_5_turns_stride_3(self) -> None:
        turns = [make_turn(i, "A" if i % 2 == 0 else "B", f"Statement number {i}.") for i in range(10)]
        chunks = chunk_meeting_turns(turns, window_size=5, stride=3)

        # Expected starts: 0, 3, 6, 9
        assert len(chunks) >= 3
        # First chunk covers turns 0..4
        assert len(chunks[0].turn_ids) == 5
        assert chunks[0].turn_index_start == 0
        assert chunks[0].turn_index_end == 4

        # Second chunk starts at turn 3 (stride 3)
        assert chunks[1].turn_index_start == 3

    def test_window_size_3(self) -> None:
        turns = [make_turn(i, "A", f"Statement {i}") for i in range(7)]
        chunks = chunk_meeting_turns(turns, window_size=3, stride=2)
        assert all(len(c.turn_ids) <= 3 for c in chunks)
        # All turns are covered
        covered = set(tid for c in chunks for tid in c.turn_ids)
        assert covered == set(t.turn_id for t in turns)

    def test_window_size_8(self) -> None:
        turns = [make_turn(i, "B", f"Statement {i}") for i in range(15)]
        chunks = chunk_meeting_turns(turns, window_size=8, stride=4)
        assert chunks[0].turn_index_start == 0
        assert chunks[0].turn_index_end == 7
        assert chunks[1].turn_index_start == 4

    def test_format_chunk_text_includes_speakers_and_timestamps(self) -> None:
        turns = [
            make_turn(0, "A", "Hello world."),
            make_turn(1, "B", "Response here."),
        ]
        formatted = format_chunk_text(turns)
        assert "[00:00:00] Speaker A: Hello world." in formatted
        assert "[00:01:00] Speaker B: Response here." in formatted

    def test_save_and_retrieve_chunks_db(self) -> None:
        from meetingos.memory.schema import initialise_db
        from meetingos.processing.embedder import TextEmbedder, save_embedding_config
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            conn = initialise_db(db_path)

            embedder = TextEmbedder(lazy_load=True)
            cfg = embedder.create_config_record(chunking_version="w3_test")
            save_embedding_config(cfg, conn)

            turns = [make_turn(i, "A", f"Text {i}") for i in range(6)]
            chunks = chunk_meeting_turns(turns, window_size=3, stride=2, config_id=cfg.config_id)
            inserted = save_chunks_to_db(chunks, conn)
            assert inserted == len(chunks)
            assert count_chunks(conn) == len(chunks)

            loaded = get_chunks_for_meeting("ES2008b", conn)
            assert len(loaded) == len(chunks)
            assert loaded[0].chunk_id == chunks[0].chunk_id
            assert loaded[0].speakers == ["A"]

            conn.close()
