"""Sentiment utilities."""

from __future__ import annotations


def clamp_sentiment(value: float | int | None) -> float | None:
    if value is None:
        return None
    numeric = float(value)
    if numeric > 1.0:
        return 1.0
    if numeric < -1.0:
        return -1.0
    return round(numeric, 3)


def sentiment_label(value: float | None) -> str:
    value = clamp_sentiment(value)
    if value is None:
        return "neutral"
    if value >= 0.25:
        return "positive"
    if value <= -0.25:
        return "negative"
    return "neutral"
