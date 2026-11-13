"""Indexing engine: FTS5 lexical index and FAISS per-team vector index.

Guarantees:
- External-content FTS5 synchronization with triggers, rebuild, and integrity checking.
- Pre-retrieval team isolation via dedicated per-team FAISS indexes.
- Persistent SQLite vector_index_map table mapping vector_id to parent chunk_id.
- Reconciliation checks between SQLite chunks, vector_index_map, and FAISS indices.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional

import faiss
import numpy as np

from meetingos.config import FAISS_DIR
from meetingos.models import Chunk, EmbeddingConfig
from meetingos.processing.embedder import TextEmbedder


class LexicalIndexer:
    """Manages SQLite FTS5 BM25 index on chunks."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def rebuild(self) -> None:
        """Execute full FTS5 index rebuild from chunks table."""
        with self.conn:
            self.conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')")

    def integrity_check(self) -> bool:
        """Run FTS5 internal integrity check."""
        try:
            with self.conn:
                self.conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('integrity-check')")
            return True
        except sqlite3.OperationalError:
            return False

    def search(
        self,
        query: str,
        team_id: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict]:
        """
        Execute BM25 search over chunks.

        Note: FTS5 bm25() returns negative values where LOWER (more negative) is better rank.
        We sort ascending by score and assign integer rank 1..N.
        """
        # Clean query for FTS5 (escape special syntax characters)
        sanitized = self._sanitize_fts_query(query)
        if not sanitized.strip():
            return []

        if team_id:
            sql = """
                SELECT c.chunk_id, c.meeting_id, c.team_id, c.text, bm25(chunks_fts) AS score
                FROM chunks_fts f
                JOIN chunks c ON f.rowid = c.rowid
                WHERE chunks_fts MATCH ? AND c.team_id = ?
                ORDER BY score ASC
                LIMIT ?
            """
            params = (sanitized, team_id, limit)
        else:
            sql = """
                SELECT c.chunk_id, c.meeting_id, c.team_id, c.text, bm25(chunks_fts) AS score
                FROM chunks_fts f
                JOIN chunks c ON f.rowid = c.rowid
                WHERE chunks_fts MATCH ?
                ORDER BY score ASC
                LIMIT ?
            """
            params = (sanitized, limit)

        try:
            rows = self.conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            # Fallback for complex queries
            simple_terms = " OR ".join(f'"{t}"' for t in query.split() if len(t) > 2)
            if not simple_terms:
                return []
            if team_id:
                sql_fallback = """
                    SELECT c.chunk_id, c.meeting_id, c.team_id, c.text, bm25(chunks_fts) AS score
                    FROM chunks_fts f
                    JOIN chunks c ON f.rowid = c.rowid
                    WHERE chunks_fts MATCH ? AND c.team_id = ?
                    ORDER BY score ASC
                    LIMIT ?
                """
                rows = self.conn.execute(sql_fallback, (simple_terms, team_id, limit)).fetchall()
            else:
                sql_fallback = """
                    SELECT c.chunk_id, c.meeting_id, c.team_id, c.text, bm25(chunks_fts) AS score
                    FROM chunks_fts f
                    JOIN chunks c ON f.rowid = c.rowid
                    WHERE chunks_fts MATCH ?
                    ORDER BY score ASC
                    LIMIT ?
                """
                rows = self.conn.execute(sql_fallback, (simple_terms, limit)).fetchall()

        results = []
        for rank, row in enumerate(rows, start=1):
            results.append({
                "chunk_id": row["chunk_id"],
                "meeting_id": row["meeting_id"],
                "team_id": row["team_id"],
                "text": row["text"],
                "raw_bm25_score": row["score"],
                "rank": rank,
            })
        return results

    @staticmethod
    def _sanitize_fts_query(query: str) -> str:
        """Escape FTS5 operators and build match expression."""
        # Split into alphanumeric tokens
        import re
        tokens = re.findall(r"\b[A-Za-z0-9_]+\b", query)
        if not tokens:
            return ""
        # Match any or all tokens with prefix matching
        return " OR ".join(f'"{t}"*' for t in tokens)


class TeamVectorIndexer:
    """Manages per-team FAISS indexes with persistent SQLite mapping."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        embedder: TextEmbedder,
        index_dir: Path = FAISS_DIR,
    ):
        self.conn = conn
        self.embedder = embedder
        self.index_dir = Path(index_dir) if index_dir is not None else Path(FAISS_DIR)
        self.indexes: dict[str, faiss.Index] = {}

    def build_team_index(
        self,
        team_id: str,
        chunks: list[Chunk],
        config: EmbeddingConfig,
    ) -> faiss.Index:
        """
        Build and persist a dedicated FAISS index for one team.

        Processes long-turn segments cleanly: if a chunk was partitioned into
        sub-segments, every sub-segment vector is indexed and mapped back to the
        parent chunk_id.
        """
        all_segments = []
        for c in chunks:
            all_segments.extend(self.embedder.segment_chunk(c))

        if not all_segments:
            index = faiss.IndexFlatIP(self.embedder.dim)
            self.indexes[team_id] = index
            return index

        # Generate embeddings in batch
        texts = [seg.text for seg in all_segments]
        embeddings = self.embedder.embed_texts(texts)

        # Create IndexFlatIP (cosine similarity with L2 normalized vectors)
        index = faiss.IndexFlatIP(self.embedder.dim)
        index.add(embeddings)
        self.indexes[team_id] = index

        # Store vector_index_map in SQLite
        mapping_rows = [
            (vec_id, seg.chunk_id, team_id, config.config_id)
            for vec_id, seg in enumerate(all_segments)
        ]

        with self.conn:
            self.conn.execute("DELETE FROM vector_index_map WHERE team_id = ?", (team_id,))
            self.conn.executemany(
                """
                INSERT INTO vector_index_map (vector_id, chunk_id, team_id, config_id)
                VALUES (?, ?, ?, ?)
                """,
                mapping_rows,
            )

        return index

    def save_team_index(self, team_id: str) -> Path:
        """Save a team's FAISS index to disk."""
        self.index_dir.mkdir(parents=True, exist_ok=True)
        path = self.index_dir / f"{team_id}.faiss"
        if team_id in self.indexes:
            faiss.write_index(self.indexes[team_id], str(path))
        return path

    def load_team_index(self, team_id: str) -> Optional[faiss.Index]:
        """Load a team's FAISS index from disk."""
        path = self.index_dir / f"{team_id}.faiss"
        if path.exists():
            idx = faiss.read_index(str(path))
            self.indexes[team_id] = idx
            return idx
        return None

    def search_team(
        self,
        query: str,
        team_id: str,
        limit: int = 20,
    ) -> list[dict]:
        """
        Semantic search isolated strictly to team_id.

        Guarantees:
        - 0% cross-team contamination (pre-retrieval team isolation).
        - Multiple sub-segment hits from the same chunk_id are deduplicated,
          preserving the maximum cosine similarity score.
        """
        index = self.indexes.get(team_id)
        if index is None:
            index = self.load_team_index(team_id)
        if index is None or index.ntotal == 0:
            return []

        query_vec = self.embedder.embed_query(query)
        # Search for up to 3x limit to account for sub-segment deduplication
        k_search = min(limit * 3, index.ntotal)
        scores, vector_ids = index.search(query_vec, k_search)

        # Retrieve chunk mapping from SQLite
        vector_id_list = [int(vid) for vid in vector_ids[0] if vid != -1]
        if not vector_id_list:
            return []

        placeholders = ",".join("?" * len(vector_id_list))
        rows = self.conn.execute(
            f"""
            SELECT v.vector_id, v.chunk_id, c.meeting_id, c.team_id, c.text
            FROM vector_index_map v
            JOIN chunks c ON v.chunk_id = c.chunk_id
            WHERE v.team_id = ? AND v.vector_id IN ({placeholders})
            """,
            [team_id] + vector_id_list,
        ).fetchall()

        mapping = {r["vector_id"]: r for r in rows}

        # Deduplicate by chunk_id keeping max score
        seen_chunks: dict[str, dict] = {}
        for score, vid in zip(scores[0], vector_ids[0]):
            if vid == -1 or vid not in mapping:
                continue
            r = mapping[vid]
            cid = r["chunk_id"]
            if cid not in seen_chunks or score > seen_chunks[cid]["score"]:
                seen_chunks[cid] = {
                    "chunk_id": cid,
                    "meeting_id": r["meeting_id"],
                    "team_id": r["team_id"],
                    "text": r["text"],
                    "score": float(score),
                }

        # Sort descending by cosine similarity score
        sorted_results = sorted(seen_chunks.values(), key=lambda x: x["score"], reverse=True)[:limit]
        for rank, res in enumerate(sorted_results, start=1):
            res["rank"] = rank

        return sorted_results

    def reconcile(self, team_id: str) -> bool:
        """
        Verify reconciliation between FAISS index and SQLite vector_index_map.
        """
        index = self.indexes.get(team_id)
        if index is None:
            index = self.load_team_index(team_id)
        if index is None:
            return False

        row = self.conn.execute(
            "SELECT COUNT(*) AS cnt FROM vector_index_map WHERE team_id = ?",
            (team_id,),
        ).fetchone()

        return index.ntotal == row["cnt"]
