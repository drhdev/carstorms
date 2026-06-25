"""Event pipeline: turn point-in-time observations into threaded, deduplicated
events and decide when a Telegram message is worth sending."""

from __future__ import annotations

from carstorms.pipeline.correlate import EvaluationResult, evaluate, evaluate_close

__all__ = ["EvaluationResult", "evaluate", "evaluate_close"]
