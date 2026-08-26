# SPDX-License-Identifier: AGPL-3.0-or-later

"""Small deterministic helpers for semantic anchor extraction.

The formal gate consumes explicit anchor timestamps from a transcript or a
human/ChatCut inspection.  This module only offers conservative candidate
term extraction; it does not claim that ASR text verifies film dialogue.
"""

from __future__ import annotations

import re

from ..visual_events.models import VisualEvent


def extract_anchor_terms(text: str) -> list[str]:
    """Return meaningful Chinese characters and Latin/number tokens."""

    tokens = re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9_]+", text or "")
    stop = {"的", "了", "着", "在", "是", "终于", "然后", "就在", "这个", "那个"}
    return [token for token in tokens if token not in stop]


def score_event_match(text: str, event: VisualEvent) -> float:
    terms = set(extract_anchor_terms(text))
    evidence = " ".join(
        [
            event.visual_action,
            event.story_event,
            event.location,
            event.dialogue_context,
            *event.characters,
        ]
    )
    evidence_terms = set(extract_anchor_terms(evidence))
    if not terms or not evidence_terms:
        return 0.0
    return len(terms.intersection(evidence_terms)) / len(terms)
