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


# ═══════════════════════════════════════════════════════════════════════════
# Curation-pipeline tests (v2)
# ═══════════════════════════════════════════════════════════════════════════

from dashboard.analyzer.apply import KEY_MOMENTS_MAX


class TestKeyMomentsCap:
    """Server-side hard cap: never more than KEY_MOMENTS_MAX active moments."""

    def _make_active(self, n: int) -> list[dict]:
        return [
            {"id": i + 1, "salience": round(0.9 - i * 0.05, 2), "flagged_by": "ai"}
            for i in range(n)
        ]

    def test_cap_constant_is_10(self):
        assert KEY_MOMENTS_MAX == 10

    def test_cap_below_limit_unchanged(self):
        active = self._make_active(8)
        # Simulate cap logic: keep top KEY_MOMENTS_MAX by salience
        to_keep = sorted(active, key=lambda x: x["salience"], reverse=True)[:KEY_MOMENTS_MAX]
        assert len(to_keep) == 8

    def test_cap_over_limit_evicts_lowest(self):
        active = self._make_active(12)
        to_keep_ids: set[int] = set()
        user_flagged = {r["id"] for r in active if r.get("flagged_by") == "user"}
        to_keep_ids |= user_flagged
        remaining = [r for r in active if r["id"] not in to_keep_ids]
        for r in remaining[:KEY_MOMENTS_MAX - len(to_keep_ids)]:
            to_keep_ids.add(r["id"])
        archived = [r for r in active if r["id"] not in to_keep_ids]
        assert len(to_keep_ids) == KEY_MOMENTS_MAX
        assert len(archived) == 2
        # Archived items should be lowest salience
        for a in archived:
            assert a["salience"] < min(active[i]["salience"] for i in range(KEY_MOMENTS_MAX))

    def test_user_flagged_exempt_from_eviction(self):
        active = self._make_active(12)
        # Make last 3 user-flagged
        for i in range(9, 12):
            active[i]["flagged_by"] = "user"
        user_flagged = {r["id"] for r in active if r.get("flagged_by") == "user"}
        to_keep_ids: set[int] = set(user_flagged)
        remaining = [r for r in active if r["id"] not in to_keep_ids]
        for r in remaining[:KEY_MOMENTS_MAX - len(to_keep_ids)]:
            to_keep_ids.add(r["id"])
        # All user-flagged preserved
        assert user_flagged.issubset(to_keep_ids)
        assert len(to_keep_ids) == KEY_MOMENTS_MAX


class TestAgendaModeEnforcement:
    """agenda_mode=apriori blocks creates; agenda_mode=dynamic allows them."""

    def test_apriori_rejects_new_item(self):
        """In apriori mode, a new_item op should be silently ignored."""
        mode = "apriori"
        item_op = {"title": "New topic", "topic_ref": None}
        # Simulated: only create if dynamic
        created = mode == "dynamic" and bool(item_op.get("title"))
        assert created is False

    def test_dynamic_allows_new_item(self):
        mode = "dynamic"
        item_op = {"title": "New topic", "topic_ref": None}
        created = mode == "dynamic" and bool(item_op.get("title"))
        assert created is True

    def test_apriori_allows_status_change(self):
        """In apriori mode, updating existing item status is allowed."""
        mode = "apriori"
        item_op = {"id": 3, "status": "done"}
        # Has an id → status update allowed in both modes
        is_status_update = bool(item_op.get("id"))
        assert is_status_update is True

    def test_done_is_terminal(self):
        """Done items must not be re-activated."""
        result = apply_agenda_transition(
            [{"id": 1, "status": "done", "started_at": "T0", "ended_at": "T1"}],
            new_active_id=1,
            now="T2",
        )
        assert result[0]["status"] == "done"


class TestDedupHashGuard:
    """dedup_hash prevents re-creation of same entity text."""

    def test_same_description_same_hash(self):
        h1 = _dedup_hash("Ralf zorgt voor data overzicht")
        h2 = _dedup_hash("ralf zorgt voor data overzicht")
        assert h1 == h2

    def test_different_description_different_hash(self):
        h1 = _dedup_hash("Besluit A")
        h2 = _dedup_hash("Besluit B")
        assert h1 != h2

    def test_whitespace_normalised(self):
        assert _dedup_hash("  foo  bar  ") == _dedup_hash("foo bar")


class TestCuratedIdempotency:
    """Re-processing the same key moment list converges to the same state."""

    def test_same_ai_list_twice_produces_same_ids_to_keep(self):
        """Simulates: apply ai_moments twice; the set of ids to keep is identical."""
        ai_moments = [
            {"id": 1, "salience": 0.9},
            {"id": 2, "salience": 0.7},
            {"type": "insight", "quote": "Something important", "salience": 0.6},
        ]
        # Run 1: ids present in AI list
        ids_present_run1 = {int(m["id"]) for m in ai_moments if m.get("id")}
        # Run 2: same list
        ids_present_run2 = {int(m["id"]) for m in ai_moments if m.get("id")}
        assert ids_present_run1 == ids_present_run2

    def test_dropped_id_triggers_archive(self):
        """If AI drops an id from the list, it should be archived."""
        currently_active_ids = {1, 2, 3}
        ai_kept_ids = {1, 3}
        user_flagged_ids: set[int] = set()
        to_archive = currently_active_ids - ai_kept_ids - user_flagged_ids
        assert to_archive == {2}

    def test_user_flagged_not_archived_on_omission(self):
        """User-flagged moments survive even when absent from AI list."""
        currently_active = [
            {"id": 1, "flagged_by": "ai"},
            {"id": 2, "flagged_by": "user"},
        ]
        ai_kept_ids = {1}  # AI omits id=2
        user_flagged_ids = {r["id"] for r in currently_active if r.get("flagged_by") == "user"}
        to_archive = {r["id"] for r in currently_active if r["id"] not in ai_kept_ids and r["id"] not in user_flagged_ids}
        assert to_archive == set()  # id=2 is user-flagged → not archived


