"""Prompts and schemas for curated live meeting analysis."""

from __future__ import annotations

import json

SYSTEM_PROMPT = """
You analyze a live meeting transcript and maintain a curated view of what matters.

**Context provided:**
- A rolling summary of earlier parts of the meeting (if available)
- A transcript window (last ~25 segments) with speaker/timestamp, NEW segments marked
- Current state: active key moments, action items, decisions, goals, agenda items, participants, topics

**Your task — return a curated target state, not a log of events:**

SEGMENT_UPDATES (only for NEW segments):
- Assign sentiment [-1..1], speaker attribution, and topic tags per new segment.
- Match topics against existing labels/synonyms before creating new ones.

KEY_MOMENTS (full curated list, max 10):
- Return the most salient moments for the WHOLE meeting so far, not just recent ones.
- Re-evaluate all moments: drop ones that turned out minor, merge near-duplicates.
- Keep 'id' for moments you retain/update. Omit 'id' to create new.
- Moments absent from your list will be soft-archived (not deleted).
- salience ∈ [0.0, 1.0]. Quotes must be verbatim, max 15 words.
- User-flagged moments (flagged_by='user') are shown but you CANNOT drop them — include them as-is.

ACTION ITEMS:
- Mark items resolved in the conversation as 'done'. Archive duplicates with archive:true.
- Update owners/due-dates when the conversation clarifies them. Omit id to create new.

DECISIONS:
- Change status via conversation evidence. Use archive:true for superseded decisions. Omit id to create.

AGENDA (mode-dependent):
- agenda_mode=apriori: ONLY change status/active of existing items. NEVER add, rename, or remove.
- agenda_mode=dynamic: build the agenda — add items when the topic clearly shifts, mark previous done.
- done items are terminal (never re-activate).

GOALS: update status with evidence. Achieved is terminal (never downgrade).

The transcript language is often Dutch. Keep entity text in the transcript language.
Return a single JSON object matching the provided schema.
""".strip()


# ── Shared sub-schemas ────────────────────────────────────────────────────────

_SPEAKER_SCHEMA = {
    "anyOf": [
        {"type": "null"},
        {
            "type": "object", "additionalProperties": False,
            "properties": {"participant_id": {"type": "integer"}},
            "required": ["participant_id"],
        },
        {
            "type": "object", "additionalProperties": False,
            "properties": {
                "new_participant": {
                    "type": "object", "additionalProperties": False,
                    "properties": {
                        "name": {"type": "string"},
                        "initials": {"type": ["string", "null"]},
                    },
                    "required": ["name"],
                }
            },
            "required": ["new_participant"],
        },
    ]
}

_TOPIC_TAG_SCHEMA = {
    "type": "array",
    "items": {
        "anyOf": [
            {
                "type": "object", "additionalProperties": False,
                "properties": {
                    "topic_id": {"type": "integer"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["topic_id", "confidence"],
            },
            {
                "type": "object", "additionalProperties": False,
                "properties": {
                    "new_topic": {
                        "type": "object", "additionalProperties": False,
                        "properties": {
                            "label": {"type": "string"},
                            "parent_topic_id": {"type": ["integer", "null"]},
                            "synonyms": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["label"],
                    },
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["new_topic", "confidence"],
            },
        ]
    },
}


# ── Main curation schema ──────────────────────────────────────────────────────

ANALYSIS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "segment_updates": {
            "type": "array",
            "description": "Per-segment updates — ONLY for segments marked NEW",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "segment_num": {"type": "integer"},
                    "sentiment": {"type": ["number", "null"], "minimum": -1.0, "maximum": 1.0},
                    "speaker": _SPEAKER_SCHEMA,
                    "topic_tags": _TOPIC_TAG_SCHEMA,
                },
                "required": ["segment_num"],
            },
        },
        "key_moments": {
            "type": "array",
            "description": "Full curated list of at most 10 key moments for the meeting so far",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "integer"},
                    "type": {"type": "string", "enum": ["commitment", "decision", "tension", "insight"]},
                    "quote": {"type": "string"},
                    "salience": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "speaker_ref": {"type": ["integer", "string", "null"]},
                },
                "required": ["type", "quote", "salience"],
            },
        },
        "action_items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "integer"},
                    "description": {"type": "string"},
                    "status": {"type": "string", "enum": ["open", "done", "cancelled"]},
                    "owner_ref": {"type": ["integer", "string", "null"]},
                    "due_date": {"type": ["string", "null"]},
                    "topic_ref": {"type": ["integer", "string", "null"]},
                    "archive": {"type": "boolean"},
                    "merge_into": {"type": ["integer", "null"]},
                },
            },
        },
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "integer"},
                    "description": {"type": "string"},
                    "status": {"type": "string", "enum": ["agreed", "concept", "rejected"]},
                    "topic_ref": {"type": ["integer", "string", "null"]},
                    "archive": {"type": "boolean"},
                },
            },
        },
        "goal_updates": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "goal_id": {"type": "integer"},
                    "status": {"type": "string", "enum": ["achieved", "at_risk", "open"]},
                    "coaching_tip": {"type": ["string", "null"]},
                },
                "required": ["goal_id", "status"],
            },
        },
        "new_goals": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "description": {"type": "string"},
                    "coaching_tip": {"type": ["string", "null"]},
                    "topic_ref": {"type": ["integer", "string", "null"]},
                },
                "required": ["description"],
            },
        },
        "agenda": {
            "anyOf": [
                {"type": "null"},
                {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "active_item_id": {"type": ["integer", "null"]},
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "id": {"type": "integer"},
                                    "title": {"type": "string"},
                                    "status": {"type": "string", "enum": ["pending", "active", "done"]},
                                    "topic_ref": {"type": ["integer", "string", "null"]},
                                },
                            },
                        },
                    },
                },
            ],
        },
        "add_synonyms": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "topic_id": {"type": "integer"},
                    "synonym": {"type": "string"},
                },
                "required": ["topic_id", "synonym"],
            },
        },
    },
    "required": [
        "segment_updates",
        "key_moments",
        "action_items",
        "decisions",
        "goal_updates",
        "new_goals",
        "agenda",
        "add_synonyms",
    ],
}

CLAUDE_TOOL = {
    "name": "meeting_curation",
    "description": "Curate the live meeting state: segment updates, key moments (max 10), action items, decisions, goals, agenda.",
    "input_schema": ANALYSIS_SCHEMA,
}


EXAMPLE_OUTPUT = {
    "segment_updates": [
        {
            "segment_num": 41,
            "sentiment": 0.2,
            "speaker": {"participant_id": 2},
            "topic_tags": [{"new_topic": {"label": "datavoorbereiding", "synonyms": ["data op tafel"]}, "confidence": 0.8}],
        }
    ],
    "key_moments": [
        {"id": 3, "type": "decision", "quote": "We gaan naar het nieuwe platform migreren", "salience": 0.9, "speaker_ref": "Ralf"},
        {"type": "commitment", "quote": "Ellis stuurt het rapport uiterlijk vrijdag", "salience": 0.7, "speaker_ref": "Ellis"},
    ],
    "action_items": [
        {"id": 2, "status": "done"},
        {"description": "Ralf zorgt voor data overzicht", "owner_ref": "Ralf", "due_date": None, "topic_ref": "datavoorbereiding"},
    ],
    "decisions": [
        {"id": 1, "status": "agreed"},
    ],
    "goal_updates": [],
    "new_goals": [],
    "agenda": {"active_item_id": 4, "items": [{"id": 3, "status": "done"}]},
    "add_synonyms": [],
}


def ollama_system_prompt() -> str:
    return (
        SYSTEM_PROMPT
        + "\n\nReturn JSON with ALL of these fields:\n"
        + json.dumps(ANALYSIS_SCHEMA, ensure_ascii=False, indent=2)
        + "\n\nEXAMPLE OUTPUT (shows required format):\n"
        + json.dumps(EXAMPLE_OUTPUT, ensure_ascii=False)
    )


ANALYSIS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "sentiment": {"type": "number", "minimum": -1.0, "maximum": 1.0},
        "speaker": {
            "anyOf": [
                {"type": "null"},
                {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"participant_id": {"type": "integer"}},
                    "required": ["participant_id"],
                },
                {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "new_participant": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "name": {"type": "string"},
                                "initials": {"type": ["string", "null"]},
                            },
                            "required": ["name"],
                        }
                    },
                    "required": ["new_participant"],
                },
            ]
        },
        "topic_tags": {
            "type": "array",
            "items": {
                "anyOf": [
                    {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "topic_id": {"type": "integer"},
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        },
                        "required": ["topic_id", "confidence"],
                    },
                    {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "new_topic": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "label": {"type": "string"},
                                    "parent_topic_id": {"type": ["integer", "null"]},
                                    "synonyms": {"type": "array", "items": {"type": "string"}},
                                },
                                "required": ["label"],
                            },
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        },
                        "required": ["new_topic", "confidence"],
                    },
                ]
            },
        },
        "add_synonyms": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "topic_id": {"type": "integer"},
                    "synonym": {"type": "string"},
                },
                "required": ["topic_id", "synonym"],
            },
        },
        "goal_updates": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "goal_id": {"type": "integer"},
                    "status": {"type": "string", "enum": ["achieved", "at_risk", "open"]},
                    "coaching_tip": {"type": ["string", "null"]},
                },
                "required": ["goal_id", "status"],
            },
        },
        "new_goals": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "description": {"type": "string"},
                    "coaching_tip": {"type": ["string", "null"]},
                    "topic_ref": {"type": ["integer", "string", "null"]},
                },
                "required": ["description"],
            },
        },
        "agenda": {
            "anyOf": [
                {"type": "null"},
                {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"active_item_id": {"type": "integer"}},
                    "required": ["active_item_id"],
                },
                {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "new_item": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "title": {"type": "string"},
                                "topic_ref": {"type": ["integer", "string", "null"]},
                            },
                            "required": ["title"],
                        }
                    },
                    "required": ["new_item"],
                },
            ]
        },
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "description": {"type": "string"},
                    "status": {"type": "string", "enum": ["agreed", "concept", "rejected"]},
                    "topic_ref": {"type": ["integer", "string", "null"]},
                },
                "required": ["description", "status"],
            },
        },
        "action_items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "description": {"type": "string"},
                    "owner_ref": {"type": ["integer", "string", "null"]},
                    "due_date": {"type": ["string", "null"]},
                    "topic_ref": {"type": ["integer", "string", "null"]},
                },
                "required": ["description"],
            },
        },
        "key_moments": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["commitment", "decision", "tension", "insight"],
                    },
                    "quote": {"type": "string"},
                    "speaker_ref": {"type": ["integer", "string", "null"]},
                },
                "required": ["type", "quote"],
            },
        },
    },
    "required": [
        "sentiment",
        "speaker",
        "topic_tags",
        "add_synonyms",
        "goal_updates",
        "new_goals",
        "agenda",
        "decisions",
        "action_items",
        "key_moments",
    ],
}

CLAUDE_TOOL = {
    "name": "meeting_segment_analysis",
    "description": "Analyze a live meeting transcript segment and emit structured updates.",
    "input_schema": ANALYSIS_SCHEMA,
}


EXAMPLE_OUTPUT = {
    "sentiment": 0.2,
    "speaker": None,
    "topic_tags": [
        {"new_topic": {"label": "datavoorbereiding", "synonyms": ["data op tafel"]}, "confidence": 0.8}
    ],
    "add_synonyms": [],
    "goal_updates": [],
    "new_goals": [],
    "agenda": None,
    "decisions": [],
    "action_items": [
        {"description": "Ralf zorgt voor data overzicht", "owner_ref": "Ralf", "due_date": None, "topic_ref": "datavoorbereiding"}
    ],
    "key_moments": [],
}


def ollama_system_prompt() -> str:
    return (
        SYSTEM_PROMPT
        + "\n\nReturn JSON with ALL of these fields:\n"
        + json.dumps(ANALYSIS_SCHEMA, ensure_ascii=False, indent=2)
        + "\n\nEXAMPLE OUTPUT (shows required format for topic_tags and action_items):\n"
        + json.dumps(EXAMPLE_OUTPUT, ensure_ascii=False)
    )
