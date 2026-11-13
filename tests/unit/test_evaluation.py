"""Unit tests for evaluation metrics and scaling models."""
from __future__ import annotations

import pytest

from meetingos.evaluation.scaling_model import compute_scaling_metrics


class TestScalingModel:

    def test_compute_scaling_metrics_1000(self):
        metrics = compute_scaling_metrics(1000)
        assert metrics.scale_meetings == 1000
        assert metrics.total_storage_mb > 0
        assert metrics.estimated_llm_cost_usd > 0
        assert metrics.parallel_8core_ingest_seconds < metrics.sequential_ingest_seconds
        assert metrics.total_chunks > 100000

    def test_compute_scaling_metrics_10000(self):
        metrics = compute_scaling_metrics(10000)
        assert metrics.scale_meetings == 10000
        assert metrics.total_storage_mb > 5000  # ~6.5GB
        assert metrics.conversation_words > 40_000_000
