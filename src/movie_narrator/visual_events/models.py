# SPDX-License-Identifier: AGPL-3.0-or-later

"""Versioned contracts for the visual-event layer.

The index deliberately distinguishes a scene-derived candidate from a
human-locked story event.  A midpoint or subtitle cue is never presented as a
verified semantic anchor.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


VISUAL_EVENT_SCHEMA_VERSION = "1.0"


class VisualEvent(BaseModel):
    event_id: str
    source_start: float = Field(ge=0)
    source_end: float = Field(gt=0)
    shot_ids: list[str] = Field(min_length=1)
    characters: list[str] = Field(default_factory=list)
    location: str = "UNKNOWN"
    visual_action: str = "UNKNOWN"
    story_event: str = "UNKNOWN"
    dialogue_context: str = ""
    importance: float = Field(default=0.5, ge=0, le=1)
    confidence: float = Field(default=0.0, ge=0, le=1)
    critical: bool = False
    review_status: Literal["CANDIDATE", "LOCKED", "UNVERIFIED"] = "CANDIDATE"
    anchor_source_time: float | None = Field(default=None, ge=0)
    anchor_basis: str = "UNKNOWN"
    evidence: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_range(self) -> "VisualEvent":
        if self.source_end <= self.source_start:
            raise ValueError("visual event source_end must be greater than source_start")
        if self.anchor_source_time is not None and not (
            self.source_start <= self.anchor_source_time <= self.source_end
        ):
            raise ValueError("visual event anchor_source_time must be inside its source range")
        return self


class VisualEventIndex(BaseModel):
    schema_version: Literal["1.0"] = VISUAL_EVENT_SCHEMA_VERSION
    source_video: str
    source_sha256: str
    scene_database_path: str
    index_status: Literal["EVENT_INDEXED", "UNVERIFIED", "BLOCKED"]
    events: list[VisualEvent] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_events(self) -> "VisualEventIndex":
        ids = [event.event_id for event in self.events]
        if len(ids) != len(set(ids)):
            raise ValueError("visual event IDs must be unique")
        if [event.source_start for event in self.events] != sorted(
            event.source_start for event in self.events
        ):
            raise ValueError("visual events must be ordered by source_start")
        return self
