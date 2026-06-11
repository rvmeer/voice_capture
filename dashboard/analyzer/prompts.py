"""Prompts and schemas for segment analysis."""

from __future__ import annotations

import json

SYSTEM_PROMPT = """
You analyze one new transcript segment of a live meeting.
The transcript language is often Dutch. Keep any extracted names, topics, quotes, and entity text in the transcript language.
You receive the latest segment, recent transcript context, current participants, topics, goals, and agenda.
Return only operations clearly justified by the latest segment. Most segments should produce few or no operations.
Reuse existing entities whenever possible.
For topics, match against labels and synonyms before creating a new topic. If the segment uses a new wording for an existing topic, add a synonym instead of creating a duplicate topic.
Decisions require clear convergence. Action items require a real commitment. Owner is optional unless named or strongly implied.
Goals should become achieved only on clear evidence. Achieved goals never get downgraded.
Key moments must be genuinely notable. Quotes must be verbatim and no more than 15 words.
Always return sentiment and topic_tags. Speaker attribution is optional, but include it if the speaker can be identified.
Return a single JSON object matching the provided schema.
""".strip()

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
