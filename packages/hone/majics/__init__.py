"""Hone's MAJICS pipeline: panel review + panel proposal, judge-fused.

A close adaptation of Rejudge (https://github.com/syabro/rejudge) on Harbor +
the pi agent — see pipeline.py for the two-job flow and driver/majics.ts for
the in-sandbox MAJICS core.
"""

from .pipeline import MajicsPipeline, PipelineFailure
from .agent import MajicsAgent

__all__ = ["MajicsAgent", "MajicsPipeline", "PipelineFailure"]
