"""Belief-state layer: atomic signals -> temporal belief states -> presentation.

Observed -> Inferred -> Verified. See docs/BELIEF_LAYER.md.
"""
from .ontology import VERSION
from .engine import infer, headline, compact
from .signals import collect_signals, make_signal, lexical_signals

__all__ = ["VERSION", "infer", "headline", "compact", "collect_signals", "make_signal", "lexical_signals"]
