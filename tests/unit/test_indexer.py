"""Unit tests for FTS5 LexicalIndexer and FAISS TeamVectorIndexer."""
from __future__ import annotations

import tempfile
from pathlib import Path
import pytest

from meetingos.memory.schema import initialise_db
from meetingos.models import Chunk, EmbeddingConfig
from meetingos.processing.chunker import save_chunks_to_db
from meetingos.processing.embedder import TextEmbedder
from meetingos.processing.indexer import LexicalIndexer, TeamVectorIndexer


def make_chunk(chunk_id: str, team_id: str, meeting_id: str, text: str) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        meeting_id=meeting_id,
        team_id=team_id,
        meeting_sequence=meeting_id[-1],
        turn_ids=[f"{chunk_id}_T1"],
        speakers=["A"],
        start_timestamp="00:01:00",
        end_timestamp="00:02:00",
        turn_index_start=0,
        turn_index_end=1,
        token_count=len(text.split()),
        text=text,
        embedding_config_id="cfg_test",
    )


def _init_test_config(conn) -> None:
    embedder = TextEmbedder(lazy_load=True)
    cfg = embedder.create_config_record(chunking_version="w5_test")
    from meetingos.processing.embedder import save_embedding_config
    save_embedding_config(cfg, conn)
    # also insert cfg_test for tests using that ID
    with conn:
        conn.execute(
            """INSERT OR REPLACE INTO embedding_configs
               (config_id, embedding_model, model_revision, embedding_dim, max_seq_length, normalization, chunking_version, created_at)
               VALUES ('cfg_test', 'model', 'rev', 384, 256, 'l2', 'test', '2026-01-01')"""
        )

class TestLexicalIndexer:

    def test_fts5_trigger_synchronization_and_search(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "fts_test.db"
            conn = initialise_db(db_path)
            _init_test_config(conn)
            indexer = LexicalIndexer(conn)

            c1 = make_chunk("C1", "TS3006", "TS3006a", "We discussed the speech recognition feature.")
            c2 = make_chunk("C2", "TS3006", "TS3006b", "The titanium back was replaced by rubber.")
            c3 = make_chunk("C3", "ES2008", "ES2008a", "Speech recognition was also mentioned here.")

            save_chunks_to_db([c1, c2, c3], conn)

            # Search globally for "speech recognition"
            res = indexer.search("speech recognition", limit=10)
            assert len(res) == 2
            ids = [r["chunk_id"] for r in res]
            assert "C1" in ids
            assert "C3" in ids
            # Ranks are 1 and 2
            assert res[0]["rank"] == 1
            assert res[1]["rank"] == 2
            # Raw BM25 score is negative (lower = better)
            assert res[0]["raw_bm25_score"] <= res[1]["raw_bm25_score"]

            # Search with team filter
            res_team = indexer.search("speech recognition", team_id="TS3006", limit=10)
            assert len(res_team) == 1
            assert res_team[0]["chunk_id"] == "C1"
            conn.close()

    def test_fts5_update_and_delete_triggers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "fts_sync.db"
            conn = initialise_db(db_path)
            _init_test_config(conn)
            indexer = LexicalIndexer(conn)

            c1 = make_chunk("C1", "TS3006", "TS3006a", "Initial wooden casing design.")
            save_chunks_to_db([c1], conn)

            assert len(indexer.search("wooden", limit=5)) == 1

            # Update chunk text
            with conn:
                conn.execute("UPDATE chunks SET text = ? WHERE chunk_id = ?", ("Switched to plastic polymer.", "C1"))

            # Old word no longer matches, new text matches
            assert len(indexer.search("wooden", limit=5)) == 0
            res_new = indexer.search("plastic", limit=5)
            assert len(res_new) == 1
            assert res_new[0]["chunk_id"] == "C1"

            # Delete chunk
            with conn:
                conn.execute("DELETE FROM chunks WHERE chunk_id = ?", ("C1",))

            assert len(indexer.search("plastic", limit=5)) == 0
            conn.close()

    def test_fts5_rebuild_and_integrity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "fts_rebuild.db"
            conn = initialise_db(db_path)
            indexer = LexicalIndexer(conn)

            assert indexer.integrity_check() is True
            indexer.rebuild()
            assert indexer.integrity_check() is True
            conn.close()


class TestTeamVectorIndexer:

    def test_team_isolated_vector_indexing_and_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "vec_test.db"
            conn = initialise_db(db_path)
            _init_test_config(conn)
            embedder = TextEmbedder(use_mock=True)
            vector_indexer = TeamVectorIndexer(conn, embedder, index_dir=Path(tmp))

            config = embedder.create_config_record()
            from meetingos.processing.embedder import save_embedding_config
            save_embedding_config(config, conn)

            # Chunks for two different teams
            c_ts_1 = make_chunk("TS_C1", "TS3006", "TS3006a", "We selected speech recognition interface.")
            c_ts_2 = make_chunk("TS_C2", "TS3006", "TS3006b", "The budget required dropping speech recognition.")
            c_es_1 = make_chunk("ES_C1", "ES2008", "ES2008a", "We evaluated voice control functionality.")

            save_chunks_to_db([c_ts_1, c_ts_2, c_es_1], conn)

            # Build index for TS3006
            idx_ts = vector_indexer.build_team_index("TS3006", [c_ts_1, c_ts_2], config)
            assert idx_ts.ntotal == 2
            assert vector_indexer.reconcile("TS3006") is True

            # Build index for ES2008
            idx_es = vector_indexer.build_team_index("ES2008", [c_es_1], config)
            assert idx_es.ntotal == 1
            assert vector_indexer.reconcile("ES2008") is True

            # Search in TS3006 must return TS3006 results only (0% leakage)
            res = vector_indexer.search_team("speech recognition", team_id="TS3006", limit=5)
            assert len(res) == 2
            assert all(r["team_id"] == "TS3006" for r in res)
            assert res[0]["rank"] == 1
            assert res[0]["score"] > 0.0

            # Persistence test: save and load index
            saved_path = vector_indexer.save_team_index("TS3006")
            assert saved_path.exists()

            new_indexer = TeamVectorIndexer(conn, embedder, index_dir=Path(tmp))
            res_loaded = new_indexer.search_team("speech recognition", team_id="TS3006", limit=5)
            assert len(res_loaded) == 2
            assert res_loaded[0]["chunk_id"] == res[0]["chunk_id"]
            conn.close()
