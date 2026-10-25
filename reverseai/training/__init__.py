"""Verified-trace datasets and a benchmark-gated improvement pipeline."""

from .dataset import TraceDataset, TraceRecord, extract_traces
from .pipeline import ImprovementPipeline, ImprovementProposal, TrainingPlan

__all__ = [
    "TraceRecord", "TraceDataset", "extract_traces",
    "TrainingPlan", "ImprovementProposal", "ImprovementPipeline",
]
