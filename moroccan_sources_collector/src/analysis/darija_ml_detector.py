"""Experimental placeholder for a future supervised Darija detector.

This module is intentionally disabled by default. A future version can train a
TF-IDF character n-gram + logistic regression classifier on validated data and
combine its probability with the lexical detector score.
"""

from __future__ import annotations


class ExperimentalDarijaMLDetector:
    enabled = False

    def predict(self, text: str) -> dict:
        raise RuntimeError("Experimental supervised Darija detector is not trained or enabled.")
