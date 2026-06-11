"""Dashboard aggregate statistics helpers."""

from __future__ import annotations

from datetime import date
from typing import Any


def tone_window(sentiments: list[float | None]) -> dict[str, float | str]:
    values = [float(value) for value in sentiments if value is not None]
    if not values:
        return {"window_avg": 0.0, "label": "neutral"}
    window_avg = round(sum(values) / len(values), 3)
    if window_avg > 0.15:
        label = "constructive"
    elif window_avg < -0.15:
        label = "tense"
    else:
        label = "neutral"
    return {"window_avg": window_avg, "label": label}


def overdue_check(due_date: date | None, status: str, *, today: date | None = None) -> bool:
    if due_date is None or status == "done":
        return False
    today = today or date.today()
    return due_date < today


def apply_overdue(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in items:
        enriched = dict(item)
        if overdue_check(enriched.get("due_date"), enriched.get("status", "open")):
            enriched["status"] = "overdue"
        result.append(enriched)
    return result


def speaking_ratios(participants: list[dict[str, Any]]) -> list[dict[str, Any]]:
    total = sum(float(item.get("speaking_seconds") or 0.0) for item in participants)
    result: list[dict[str, Any]] = []
    for participant in participants:
        enriched = dict(participant)
        seconds = float(enriched.get("speaking_seconds") or 0.0)
        enriched["speaking_time_ratio"] = round(seconds / total, 4) if total > 0 else 0.0
        result.append(enriched)
    return result


def header_stats(
    participants: list[dict[str, Any]],
    goals: list[dict[str, Any]],
    action_items: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
) -> dict[str, int]:
    return {
        "participants": len(participants),
        "goals_achieved": sum(1 for goal in goals if goal.get("status") == "achieved"),
        "goals_total": len(goals),
        "action_items": len(action_items),
        "decisions": len(decisions),
    }
