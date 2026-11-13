"""Cost, storage, and throughput scaling model for MeetingOS.

Provides parametric cost and performance projections based on measured
empirical metrics from the 138-meeting AMI corpus run.
Extrapolates linearly and with concurrency to 1,000 and 10,000 meetings.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CorpusScaleMetrics:
    scale_meetings: int
    conversation_words: int
    conversation_tokens: int
    total_chunks: int
    total_vectors: int
    db_storage_mb: float
    faiss_storage_mb: float
    total_storage_mb: float
    sequential_ingest_seconds: float
    parallel_8core_ingest_seconds: float
    llm_input_tokens: int
    llm_output_tokens: int
    estimated_llm_cost_usd: float


def compute_scaling_metrics(
    target_meetings: int,
    measured_meetings: int = 138,
    measured_words: int = 676745,
    measured_tokens: int = 879768,
    measured_chunks: int = 23901,
    measured_vectors: int = 25772,
    measured_db_mb: float = 52.8,
    measured_faiss_mb: float = 37.0,
    measured_wall_seconds: float = 60.0,
    llm_input_price_per_m: float = 0.15,   # Gemini 2.0 Flash / GPT-4o-mini tier
    llm_output_price_per_m: float = 0.60,
    prompt_overhead_ratio: float = 0.15,  # 15% system prompt and template overhead
    extraction_output_ratio: float = 0.18, # 18% event JSON extraction density
) -> CorpusScaleMetrics:
    """Calculate empirical scaling metrics for target meeting volume."""
    ratio = target_meetings / measured_meetings

    words = int(measured_words * ratio)
    tokens = int(measured_tokens * ratio)
    chunks = int(measured_chunks * ratio)
    vectors = int(measured_vectors * ratio)

    db_mb = round(measured_db_mb * ratio, 1)
    faiss_mb = round(measured_faiss_mb * ratio, 1)
    total_mb = round(db_mb + faiss_mb, 1)

    seq_seconds = round(measured_wall_seconds * ratio, 1)
    # Amdahl's law scaling with 8 cores (assuming 85% parallelizable workload across teams)
    speedup_8core = 1.0 / (0.15 + (0.85 / 8))
    par_seconds = round(seq_seconds / speedup_8core, 1)

    input_tokens = int(tokens * (1.0 + prompt_overhead_ratio))
    output_tokens = int(tokens * extraction_output_ratio)

    cost_usd = (input_tokens / 1_000_000) * llm_input_price_per_m + (output_tokens / 1_000_000) * llm_output_price_per_m

    return CorpusScaleMetrics(
        scale_meetings=target_meetings,
        conversation_words=words,
        conversation_tokens=tokens,
        total_chunks=chunks,
        total_vectors=vectors,
        db_storage_mb=db_mb,
        faiss_storage_mb=faiss_mb,
        total_storage_mb=total_mb,
        sequential_ingest_seconds=seq_seconds,
        parallel_8core_ingest_seconds=par_seconds,
        llm_input_tokens=input_tokens,
        llm_output_tokens=output_tokens,
        estimated_llm_cost_usd=round(cost_usd, 2),
    )
