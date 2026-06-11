"""Unit tests for dashboard utility logic (no DB or network required)."""

from __future__ import annotations

import pytest

# Import real implementations — never inline replicas
from dashboard.analyzer.apply import _dedup_hash, apply_agenda_transition, apply_goal_latch
from dashboard.analyzer.sentiment import clamp_sentiment
from dashboard.api.setup import topic_label_matches
from dashboard.stats import TONE_WINDOW_SIZE, speaking_ratios, tone_window


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
        assert clamp_sentiment(0.5) == 0.5

    def test_clamps_above_1(self):
        assert clamp_sentiment(2.0) == 1.0

    def test_clamps_below_minus_1(self):
        assert clamp_sentiment(-5) == -1.0

    def test_string_input(self):
        assert clamp_sentiment("0.3") == pytest.approx(0.3)  # type: ignore[arg-type]

    def test_none_input(self):
        assert clamp_sentiment(None) is None

    def test_invalid_input(self):
        assert clamp_sentiment("not-a-number") is None  # type: ignore[arg-type]


class TestToneWindow:
    def test_positive_is_constructive(self):
        result = tone_window([0.5] * TONE_WINDOW_SIZE)
        assert result["label"] == "constructive"

    def test_boundary_constructive(self):
        result = tone_window([0.16] * TONE_WINDOW_SIZE)
        assert result["label"] == "constructive"

    def test_neutral(self):
        assert tone_window([0.0])["label"] == "neutral"
        assert tone_window([0.15])["label"] == "neutral"
        assert tone_window([-0.15])["label"] == "neutral"

    def test_tense(self):
        result = tone_window([-0.5] * TONE_WINDOW_SIZE)
        assert result["label"] == "tense"

    def test_empty_is_neutral(self):
        result = tone_window([])
        assert result["label"] == "neutral"
        assert result["window_avg"] == 0.0

    def test_none_values_ignored(self):
        result = tone_window([None, 0.5, None])  # type: ignore[list-item]
        assert result["window_avg"] == pytest.approx(0.5)

    def test_window_size_constant_is_18(self):
        assert TONE_WINDOW_SIZE == 18


class TestTopicSynonymMatching:
    def test_exact_label_match(self):
        assert topic_label_matches("Budget", "budget", []) is True

    def test_synonym_match(self):
        assert topic_label_matches("BtD-planner", "Backlog", ["BtD-planner", "planner"]) is True

    def test_case_insensitive_synonym(self):
        assert topic_label_matches("btd-planner", "Backlog", ["BtD-Planner"]) is True

    def test_no_match(self):
        assert topic_label_matches("Deployment", "Budget", ["kosten"]) is False

    def test_empty_synonyms(self):
        assert topic_label_matches("Foo", "Bar", []) is False


class TestAgendaStateMachine:
    def _make_items(self):
        return [
            {"id": 1, "status": "done",    "started_at": "T1", "ended_at": "T2"},
            {"id": 2, "status": "active",  "started_at": "T2", "ended_at": None},
            {"id": 3, "status": "pending", "started_at": None,  "ended_at": None},
        ]

    def test_activates_pending_item(self):
        result = apply_agenda_transition(self._make_items(), new_active_id=3, now="T3")
        active = [i for i in result if i["status"] == "active"]
        assert len(active) == 1
        assert active[0]["id"] == 3

    def test_closes_previously_active_item(self):
        result = apply_agenda_transition(self._make_items(), new_active_id=3, now="T3")
        old = next(i for i in result if i["id"] == 2)
        assert old["status"] == "done"
        assert old["ended_at"] == "T3"

    def test_done_item_never_reverted(self):
        result = apply_agenda_transition(self._make_items(), new_active_id=1, now="T3")
        item1 = next(i for i in result if i["id"] == 1)
        assert item1["status"] == "done"

    def test_started_at_preserved_when_already_set(self):
        items = [{"id": 1, "status": "pending", "started_at": "EXISTING", "ended_at": None}]
        result = apply_agenda_transition(items, new_active_id=1, now="NEW")
        assert result[0]["started_at"] == "EXISTING"


class TestGoalLatch:
    """Goal latch: achieved → never downgrade."""

    def test_achieved_stays_achieved(self):
        assert apply_goal_latch("achieved", "open") == "achieved"
        assert apply_goal_latch("achieved", "at_risk") == "achieved"

    def test_open_can_become_at_risk(self):
        assert apply_goal_latch("open", "at_risk") == "at_risk"

    def test_at_risk_can_become_open(self):
        assert apply_goal_latch("at_risk", "open") == "open"

    def test_open_can_become_achieved(self):
        assert apply_goal_latch("open", "achieved") == "achieved"


class TestSpeakingRatio:
    """Speaking ratio math: ratios must sum to ≈ 1."""

    def _make_participants(self, seconds: dict[int, float]) -> list[dict]:
        return [
            {"id": k, "name": str(k), "speaking_seconds": v}
            for k, v in seconds.items()
        ]

    def test_ratios_sum_to_one(self):
        participants = self._make_participants({1: 60.0, 2: 30.0, 3: 10.0})
        result = speaking_ratios(participants)
        assert sum(p["speaking_time_ratio"] for p in result) == pytest.approx(1.0)

    def test_single_speaker_is_one(self):
        participants = self._make_participants({1: 120.0})
        result = speaking_ratios(participants)
        assert result[0]["speaking_time_ratio"] == pytest.approx(1.0)

    def test_zero_total_gives_zeros(self):
        participants = self._make_participants({1: 0.0, 2: 0.0})
        result = speaking_ratios(participants)
        assert all(p["speaking_time_ratio"] == 0.0 for p in result)

    def test_proportions_correct(self):
        participants = self._make_participants({1: 75.0, 2: 25.0})
        result = speaking_ratios(participants)
        by_id = {p["id"]: p["speaking_time_ratio"] for p in result}
        assert by_id[1] == pytest.approx(0.75)
        assert by_id[2] == pytest.approx(0.25)

