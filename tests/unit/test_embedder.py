"""Unit tests for TextEmbedder and long-turn splitting."""
from __future__ import annotations

import numpy as np
import pytest

from meetingos.models import Chunk
from meetingos.processing.embedder import (
    TextEmbedder,
    get_embedding_config,
    save_embedding_config,
)


def make_chunk(text: str, token_count: int, chunk_id: str = "ES2008b_chunk_0001") -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        meeting_id="ES2008b",
        team_id="ES2008",
        meeting_sequence="b",
        turn_ids=["ES2008b_A_0001"],
        speakers=["A"],
        start_timestamp="00:01:00",
        end_timestamp="00:02:00",
        turn_index_start=0,
        turn_index_end=0,
        token_count=token_count,
        text=text,
        embedding_config_id="cfg_001",
    )


class TestEmbedder:

    def test_config_record_and_persistence(self) -> None:
        from meetingos.memory.schema import initialise_db
        import tempfile
        from pathlib import Path

        embedder = TextEmbedder(lazy_load=True)
        config = embedder.create_config_record(chunking_version="w5_s3_v1")
        assert len(config.config_id) == 16
        assert config.embedding_dim == 384
        assert config.max_seq_length == 256

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test_cfg.db"
            conn = initialise_db(db_path)
            save_embedding_config(config, conn)

            loaded = get_embedding_config(config.config_id, conn)
            assert loaded is not None
            assert loaded.config_id == config.config_id
            assert loaded.embedding_model == config.embedding_model
            assert loaded.max_seq_length == 256
            conn.close()

    def test_short_chunk_produces_single_segment(self) -> None:
        embedder = TextEmbedder(max_seq_length=256, lazy_load=True)
        chunk = make_chunk("Short turn text.", 10)
        segments = embedder.segment_chunk(chunk)
        assert len(segments) == 1
        assert not segments[0].is_subsegment
        assert segments[0].text == "Short turn text."
        assert segments[0].chunk_id == chunk.chunk_id

    def test_long_chunk_splits_into_overlapping_segments(self) -> None:
        """A 600-word turn (~800 tokens) must split into multiple sub-segments."""
        embedder = TextEmbedder(max_seq_length=256, stride_tokens=128, lazy_load=True)
        words = [f"word{i}" for i in range(600)]
        long_text = " ".join(words)
        chunk = make_chunk(long_text, 800)

        segments = embedder.segment_chunk(chunk)
        assert len(segments) > 1, f"Expected multiple segments, got {len(segments)}"
        assert all(seg.is_subsegment for seg in segments)
        assert all(seg.chunk_id == chunk.chunk_id for seg in segments)

        # Content at the very end must appear in the last segment
        assert "word599" in segments[-1].text
        # Content at the beginning must appear in the first segment
        assert "word0" in segments[0].text

    def test_embedding_generation_shape_and_l2_norm(self) -> None:
        embedder = TextEmbedder(use_mock=True)
        texts = ["First test sentence.", "Second test sentence for embedding."]
        vecs = embedder.embed_texts(texts)

        assert vecs.shape == (2, embedder.dim)
        assert vecs.dtype == np.float32

        # Check L2 normalization (norm should be ~1.0)
        for i in range(len(texts)):
            norm = np.linalg.norm(vecs[i])
            assert pytest.approx(1.0, abs=1e-4) == norm
