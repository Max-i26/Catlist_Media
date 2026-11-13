"""Unit tests for HybridRetriever (BM25 + FAISS + RRF fusion)."""
from __future__ import annotations

import tempfile
from pathlib import Path
import pytest

from meetingos.memory.schema import initialise_db
from meetingos.memory.source import SourceMemory
from meetingos.models import Chunk, Turn
from meetingos.processing.chunker import save_chunks_to_db
from meetingos.processing.embedder import TextEmbedder
from meetingos.processing.indexer import LexicalIndexer, TeamVectorIndexer
from meetingos.retrieval.hybrid import HybridRetriever


def make_turn(turn_idx: int, speaker: str, text: str, meeting_id: str = "TS3006a") -> Turn:
    return Turn(
        turn_id=f"{meeting_id}_{speaker}_{turn_idx+1:04d}",
        turn_index=turn_idx,
        meeting_id=meeting_id,
        team_id=meeting_id[:-1],
        meeting_sequence=meeting_id[-1],
        meeting_number=1,
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


def make_chunk(chunk_id: str, team_id: str, meeting_id: str, text: str, turn_ids: list[str]) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        meeting_id=meeting_id,
        team_id=team_id,
        meeting_sequence=meeting_id[-1],
        turn_ids=turn_ids,
        speakers=["A", "B"],
        start_timestamp="00:01:00",
        end_timestamp="00:02:00",
        turn_index_start=0,
        turn_index_end=1,
        token_count=len(text.split()),
        text=text,
        embedding_config_id="cfg_hybrid",
    )


class TestHybridRetriever:

    def test_rrf_scoring_formula(self) -> None:
        """Verify RRF score calculation: 1/(k + rank_bm25) + 1/(k + rank_vec)."""
        k = 60
        # If item is rank 1 in both: 1/61 + 1/61 = 2/61 ~ 0.03278
        score_both_1 = (1.0 / (k + 1)) + (1.0 / (k + 1))
        # If item is rank 1 in only one: 1/61 ~ 0.01639
        score_one_1 = 1.0 / (k + 1)
        assert score_both_1 > score_one_1
        assert pytest.approx(0.03278, abs=1e-4) == score_both_1

    def test_hybrid_retrieval_and_expansion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "hybrid_test.db"
            conn = initialise_db(db_path)
            memory = SourceMemory(conn)
            embedder = TextEmbedder(lazy_load=True)

            with conn:
                conn.execute(
                    """INSERT OR REPLACE INTO embedding_configs
                       (config_id, embedding_model, model_revision, embedding_dim, max_seq_length, normalization, chunking_version, created_at)
                       VALUES ('cfg_hybrid', 'model', 'rev', 384, 256, 'l2', 'test', '2026-01-01')"""
                )

            # Insert raw turns
            t1 = make_turn(0, "A", "We considered LCD screen for the remote control.")
            t2 = make_turn(1, "B", "And also speech recognition as an alternative.")
            t3 = make_turn(2, "A", "The costs forced us to make a cut.")
            t4 = make_turn(3, "B", "We dropped speech recognition and kept LCD.")

            from meetingos.ingestion.parser import build_coverage_registry, ParsedMeeting, ParsedTurn
            pm = ParsedMeeting(
                meeting_id="TS3006a",
                team_id="TS3006",
                meeting_sequence="a",
                meeting_number=1,
                declared_speakers=["A", "B"],
                source_file="dummy.txt",
                source_checksum="abc",
                turns=[
                    ParsedTurn("A", "00:00:00", t1.text, 0, 10),
                    ParsedTurn("B", "00:01:00", t2.text, 10, 20),
                    ParsedTurn("A", "00:02:00", t3.text, 20, 30),
                    ParsedTurn("B", "00:03:00", t4.text, 30, 40),
                ]
            )
            cov = build_coverage_registry([pm])
            memory.save_meetings([pm], cov)

            # Insert chunk
            c1 = make_chunk("C1", "TS3006", "TS3006a", "LCD screen speech recognition cost cut dropped", ["TS3006a_A_0001", "TS3006a_B_0002"])
            save_chunks_to_db([c1], conn)

            lexical = LexicalIndexer(conn)
            vector = TeamVectorIndexer(conn, embedder, index_dir=Path(tmp))

            retriever = HybridRetriever(lexical, vector, memory)
            res = retriever.retrieve("speech recognition", team_id="TS3006", limit=5)
            assert len(res) >= 1
            assert res[0].chunk_id == "C1"
            assert res[0].rank == 1

            # Evidence expansion test
            expanded = retriever.expand_evidence(res, context_window=1)
            assert len(expanded) == 1
            assert expanded[0].chunk_id == "C1"
            assert len(expanded[0].core_turns) == 2
            # Context window includes neighboring turns
            assert len(expanded[0].context_turns) >= 2

            conn.close()
