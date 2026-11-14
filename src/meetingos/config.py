"""MeetingOS configuration — all tuneable parameters in one place.

Change a value here; never hard-code it in module files.
Every parameter should be defensible: comment WHY it was chosen.
"""
from __future__ import annotations

import os
from pathlib import Path

# Disable HF xet downloader (prevents hanging on Windows Python 3.13)
os.environ["HF_HUB_DISABLE_XET"] = "1"

# ---------------------------------------------------------------------------
# Paths (Dynamically resolved across Linux, Colab, Mac, and Windows)
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

def _find_data_dir() -> Path:
    if "MEETINGOS_DATA_DIR" in os.environ:
        return Path(os.environ["MEETINGOS_DATA_DIR"])
    candidates = [
        PROJECT_ROOT / "data",
        PROJECT_ROOT / "Catalist_AI_Intern_Build_Test_Data",
        PROJECT_ROOT.parent / "Catalist_AI_Intern_Build_Test_Data",
        Path(r"D:\Catalist_Media\Catalist_AI_Intern_Build_Test_Data"),
    ]
    for c in candidates:
        if (c / "transcripts").exists():
            return c
    return PROJECT_ROOT / "data"

def _find_outputs_dir() -> Path:
    if "MEETINGOS_OUTPUTS_DIR" in os.environ:
        return Path(os.environ["MEETINGOS_OUTPUTS_DIR"])
    candidates = [
        PROJECT_ROOT / "outputs",
        PROJECT_ROOT.parent / "meetingos" / "outputs",
        Path(r"D:\Catalist_Media\meetingos\outputs"),
    ]
    for c in candidates:
        if (c / "meetingos.db").exists():
            return c
    return PROJECT_ROOT / "outputs"

DATA_DIR        = _find_data_dir()
TRANSCRIPTS_DIR = DATA_DIR / "transcripts"
QUESTIONS_FILE  = DATA_DIR / "questions.json"
OUTPUTS_DIR     = _find_outputs_dir()
DB_PATH         = OUTPUTS_DIR / "meetingos.db"
FAISS_DIR       = OUTPUTS_DIR / "faiss_indexes"

# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------
# Expected number of transcript files. Gate 1 fails if count differs.
EXPECTED_FILE_COUNT = 138

# Meeting sequences expected per team (standard AMI layout)
EXPECTED_SEQUENCES = ["a", "b", "c", "d"]

# Known teams with incomplete meeting histories (corpus fact, not error)
INCOMPLETE_TEAMS: dict[str, list[str]] = {
    "IS1002": ["b", "c", "d"],  # missing 'a'
    "IS1005": ["a", "b", "c"],  # missing 'd'
}

# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------
# Sliding window sizes to benchmark. Unit: number of consecutive turns.
# These are experimental candidates; we select via Recall@10 measurement.
CHUNK_WINDOW_SIZES = [3, 5, 8]

# Default window size used in production after benchmarking.
# MUST be updated via ADR-003 after benchmark results are recorded.
DEFAULT_CHUNK_WINDOW = 5

# Overlap between consecutive windows (in turns). Prevents boundary misses.
CHUNK_STRIDE = 2  # i.e. window advances by (window - stride) turns each step

# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------
# Baseline embedding model. Must be measured before finalising (ADR-002).
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIM   = 384
# Actual max_seq_length from the model's config — do NOT assume from name.
# MiniLM-L6-v2 is 256 tokens. Verified at runtime against model.max_seq_length.
EMBEDDING_MAX_SEQ_LENGTH = 256

# Overlap stride for long-turn splitting (in tokens).
# A turn > EMBEDDING_MAX_SEQ_LENGTH gets split into overlapping segments
# so that the tail content is not silently truncated.
LONG_TURN_STRIDE_TOKENS = 128  # 50% overlap

# Normalization applied before FAISS inner product search.
EMBEDDING_NORMALIZATION = "l2"

# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------
# Number of candidates retrieved per sub-question, per method.
RETRIEVAL_LIMIT = 20

# RRF fusion constant. k=60 is the standard default from the original paper.
# Higher k reduces the influence of very high individual rankings.
RRF_K = 60

# Minimum number of distinct meeting_ids in final evidence for a cross-meeting Q.
MIN_MEETING_COVERAGE = 2

# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------
MAX_RETRIEVAL_ITERATIONS = 4
MAX_SUB_QUESTIONS        = 6
MAX_EVIDENCE_CANDIDATES  = 20  # per sub-question

# Per-operation timeouts (seconds)
TIMEOUT_EMBEDDING       = 10
TIMEOUT_FTS_RETRIEVAL   = 5
TIMEOUT_FAISS_RETRIEVAL = 5
TIMEOUT_LLM_EXTRACTION  = 60   # Stage 1: per meeting
TIMEOUT_LLM_DECOMPOSE   = 20   # Question decomposition
TIMEOUT_LLM_SYNTHESIS   = 45   # Answer generation

# Retry policy
MAX_RETRIES        = 3
RETRY_BACKOFF_BASE = 1.0  # seconds; doubles each retry

# ---------------------------------------------------------------------------
# Output contract (from questions.json — do not change without re-reading source)
# ---------------------------------------------------------------------------
MIN_ANSWER_SENTENCES = 1
MAX_ANSWER_SENTENCES = 3
MIN_CITATIONS        = 1
MAX_CITATIONS        = 3
MIN_QUOTE_WORDS      = 6  # "at least six words" per questions.json instructions

# ---------------------------------------------------------------------------
# Model Synthesis & Routing (Anthropic Claude Active Models)
# ---------------------------------------------------------------------------
# Claude Haiku 4.5 is the active cost-efficient synthesis tier ($0.25 / $1.25 per 1M)
DEFAULT_CLAUDE_SYNTHESIS_MODEL = "claude-haiku-4-5"

# Claude Sonnet 4.6 is the active escalation tier for complex multi-meeting arbitration
DEFAULT_CLAUDE_ESCALATION_MODEL = "claude-sonnet-4-6"

# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------
RECALL_AT_K = [5, 10]  # Recall@5 and Recall@10
