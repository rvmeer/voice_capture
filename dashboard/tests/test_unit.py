"""Unit tests for dashboard utility logic (no DB or network required)."""

from __future__ import annotations

import hashlib
import re

import pytest


# ── helpers inlined (same logic as in apply.py / stats.py) ──────────────────

def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _dedup_hash(value: str) -> str:
    return hashlib.sha256(_normalize_text(value).encode()).hexdigest()[:16]


def _clamp_sentiment(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return max(-1.0, min(1.0, f))


def _tone_label(avg: float) -> str:
    if avg > 0.15:
        return "constructive"
    if avg < -0.15:
        return "tense"
    return "neutral"


# ── topic synonym matching (replicated from api/setup.py) ───────────────────

def _topic_matches(label: str, existing_label: str, existing_synonyms: list[str]) -> bool:
    label_lower = label.strip().lower()
    if label_lower == existing_label.strip().lower():
        return True
    return any(label_lower == s.strip().lower() for s in (existing_synonyms or []))


# ── agenda state machine ────────────────────────────────────────────────────

def _apply_agenda_transition(items: list[dict], new_active_id: int, now: str) -> list[dict]:
    """Mark currently-active items done, activate the given item."""
    result = []
    for item in items:
        if item["status"] == "active" and item["id"] != new_active_id:
            result.append({**item, "status": "done", "ended_at": now})
        elif item["id"] == new_active_id and item["status"] != "done":
            result.append({
                **item,
                "status": "active",
                "started_at": item.get("started_at") or now,
            })
        else:
            result.append(item)
    return result


# ═══════════════════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestDedupHash:
    def test_same_text_same_hash(self):
        assert _dedup_hash("We doen dit") == _dedup_hash("We doen dit")

    def test_case_insensitive(self):
        assert _dedup_hash("Besluit A") == _dedup_hash("besluit a")

    def test_whitespace_normalised(self):
        assert _dedup_hash("  foo  bar  ") == _dedup_hash("foo bar")

    def test_different_text_different_hash(self):
        assert _dedup_hash("Besluit A") != _dedup_hash("Besluit B")

    def test_length_is_16(self):
        assert len(_dedup_hash("anything")) == 16


class TestSentimentClamp:
    def test_within_range(self):
        assert _clamp_sentiment(0.5) == 0.5

    def test_clamps_above_1(self):
        assert _clamp_sentiment(2.0) == 1.0

    def test_clamps_below_minus_1(self):
        assert _clamp_sentiment(-5) == -1.0

    def test_string_input(self):
        assert _clamp_sentiment("0.3") == pytest.approx(0.3)

    def test_none_input(self):
        assert _clamp_sentiment(None) is None

    def test_invalid_input(self):
        assert _clamp_sentiment("not-a-number") is None


class TestToneWindow:
    def test_positive_is_constructive(self):
        assert _tone_label(0.5) == "constructive"

    def test_boundary_constructive(self):
        assert _tone_label(0.16) == "constructive"

    def test_neutral(self):
        assert _tone_label(0.0) == "neutral"
        assert _tone_label(0.15) == "neutral"
        assert _tone_label(-0.15) == "neutral"

    def test_tense(self):
        assert _tone_label(-0.5) == "tense"


class TestTopicSynonymMatching:
    def test_exact_label_match(self):
        assert _topic_matches("Budget", "budget", []) is True

    def test_synonym_match(self):
        assert _topic_matches("BtD-planner", "Backlog", ["BtD-planner", "planner"]) is True

    def test_case_insensitive_synonym(self):
        assert _topic_matches("btd-planner", "Backlog", ["BtD-Planner"]) is True

    def test_no_match(self):
        assert _topic_matches("Deployment", "Budget", ["kosten"]) is False

    def test_empty_synonyms(self):
        assert _topic_matches("Foo", "Bar", []) is False


class TestAgendaStateMachine:
    def _make_items(self):
        return [
            {"id": 1, "status": "done",    "started_at": "T1", "ended_at": "T2"},
            {"id": 2, "status": "active",  "started_at": "T2", "ended_at": None},
            {"id": 3, "status": "pending", "started_at": None,  "ended_at": None},
        ]

    def test_activates_pending_item(self):
        items = self._make_items()
        result = _apply_agenda_transition(items, new_active_id=3, now="T3")
        active = [i for i in result if i["status"] == "active"]
        assert len(active) == 1
        assert active[0]["id"] == 3

    def test_closes_previously_active_item(self):
        items = self._make_items()
        result = _apply_agenda_transition(items, new_active_id=3, now="T3")
        old = next(i for i in result if i["id"] == 2)
        assert old["status"] == "done"
        assert old["ended_at"] == "T3"

    def test_done_item_never_reverted(self):
        items = self._make_items()
        result = _apply_agenda_transition(items, new_active_id=1, now="T3")
        item1 = next(i for i in result if i["id"] == 1)
        assert item1["status"] == "done"   # already done → not re-activated

    def test_started_at_preserved_when_already_set(self):
        items = [{"id": 1, "status": "pending", "started_at": "EXISTING", "ended_at": None}]
        result = _apply_agenda_transition(items, new_active_id=1, now="NEW")
        assert result[0]["started_at"] == "EXISTING"


class TestGoalLatch:
    """Goal latch: achieved → never downgrade."""

    def _apply_goal(self, current_status: str, requested_status: str) -> str:
        if current_status == "achieved" and requested_status != "achieved":
            return "achieved"
        return requested_status

    def test_achieved_stays_achieved(self):
        assert self._apply_goal("achieved", "open") == "achieved"
        assert self._apply_goal("achieved", "at_risk") == "achieved"

    def test_open_can_become_at_risk(self):
        assert self._apply_goal("open", "at_risk") == "at_risk"

    def test_at_risk_can_become_open(self):
        assert self._apply_goal("at_risk", "open") == "open"

    def test_open_can_become_achieved(self):
        assert self._apply_goal("open", "achieved") == "achieved"


class TestSpeakingRatio:
    """Speaking ratio math: ratios must sum to ≈ 1."""

    def _compute_ratios(self, seconds: dict[int, float]) -> dict[int, float]:
        total = sum(seconds.values())
        if total == 0:
            return {k: 0.0 for k in seconds}
        return {k: v / total for k, v in seconds.items()}

    def test_ratios_sum_to_one(self):
        ratios = self._compute_ratios({1: 60.0, 2: 30.0, 3: 10.0})
        assert sum(ratios.values()) == pytest.approx(1.0)

    def test_single_speaker_is_one(self):
        ratios = self._compute_ratios({1: 120.0})
        assert ratios[1] == pytest.approx(1.0)

    def test_zero_total_gives_zeros(self):
        ratios = self._compute_ratios({1: 0.0, 2: 0.0})
        assert all(v == 0.0 for v in ratios.values())

    def test_proportions_correct(self):
        ratios = self._compute_ratios({1: 75.0, 2: 25.0})
        assert ratios[1] == pytest.approx(0.75)
        assert ratios[2] == pytest.approx(0.25)
