# SPDX-License-Identifier: AGPL-3.0-or-later

"""Narration segments that cannot exist without visual-event bindings."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from ..cinematic.models import NarrationSegment as LegacyNarrationSegment
from ..visual_events.models import VisualEventIndex


class BoundNarrationSegment(BaseModel):
    narration_id: str
    event_ids: list[str] = Field(min_length=1)
    text: str = Field(min_length=1)
    target_visual_start: float = Field(ge=0)
    target_visual_end: float = Field(gt=0)
    target_duration: float = Field(gt=0)
    estimated_tts_duration: float | None = Field(default=None, gt=0)
    actual_tts_duration: float | None = Field(default=None, gt=0)
    tts_asset: str | None = None
    visual_anchor: str = "UNKNOWN"
    anchor_source_time: float | None = Field(default=None, ge=0)
    spoken_anchor_time: float | None = Field(default=None, ge=0)
    spoken_anchor_offset: float | None = Field(default=None, ge=0)
    critical_event: bool = False
    sync_confidence: float = Field(default=0.0, ge=0, le=1)
    binding_status: Literal["CANDIDATE", "LOCKED", "UNVERIFIED"] = "CANDIDATE"

    @model_validator(mode="after")
    def validate_segment(self) -> "BoundNarrationSegment":
        if self.target_visual_end <= self.target_visual_start:
            raise ValueError("target_visual_end must be greater than target_visual_start")
        if self.spoken_anchor_time is None and self.spoken_anchor_offset is not None:
            if self.spoken_anchor_offset > self.target_duration:
                raise ValueError("spoken_anchor_offset cannot exceed target_duration")
        return self


class NarrationSegmentsDocument(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    status: Literal["SCRIPTED", "TTS_READY", "UNVERIFIED", "BLOCKED"]
    segments: list[BoundNarrationSegment] = Field(min_length=1)


def _event_for_legacy_target(target_scene: str, index: VisualEventIndex):
    for event in index.events:
        if target_scene in event.shot_ids or target_scene in {
            event.event_id,
            event.visual_action,
            event.story_event,
            event.location,
        }:
            return event
    return None


def _load_payload(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    segments = payload.get("segments")
    if not isinstance(segments, list):
        raise ValueError(f"{path} does not contain a segments array")
    return segments


def load_narration_segments(
    path: str | Path,
    *,
    visual_events: VisualEventIndex | None = None,
) -> NarrationSegmentsDocument:
    """Load the new contract or adapt the existing cinematic v2 file.

    Legacy v2 items are accepted only when ``target_scene`` resolves to a
    visual event.  An unbound free-form item is rejected rather than silently
    treated as synchronized.
    """

    source = Path(path)
    raw_items = _load_payload(source)
    bound: list[BoundNarrationSegment] = []
    for raw in raw_items:
        if "event_ids" in raw:
            bound.append(BoundNarrationSegment.model_validate(raw))
            continue
        if visual_events is None:
            raise ValueError(
                f"{source}: legacy narration item {raw.get('id', 'UNKNOWN')} "
                "requires VISUAL_EVENT_INDEX for binding"
            )
        legacy = LegacyNarrationSegment.model_validate(raw)
        event = _event_for_legacy_target(legacy.target_scene, visual_events)
        if event is None:
            raise ValueError(
                f"{source}: narration {legacy.id} has no visual event for "
                f"target_scene={legacy.target_scene!r}"
            )
        bound.append(
            BoundNarrationSegment(
                narration_id=legacy.id,
                event_ids=[event.event_id],
                text=legacy.narration,
                target_visual_start=event.source_start,
                target_visual_end=event.source_end,
                target_duration=event.source_end - event.source_start,
                estimated_tts_duration=legacy.estimated_duration,
                actual_tts_duration=legacy.tts_duration,
                tts_asset=legacy.tts_asset,
                visual_anchor=event.visual_action,
                anchor_source_time=event.anchor_source_time,
                critical_event=event.critical,
                sync_confidence=event.confidence,
                binding_status="CANDIDATE",
            )
        )
    actual = all(item.actual_tts_duration is not None for item in bound)
    return NarrationSegmentsDocument(
        status="TTS_READY" if actual else "UNVERIFIED",
        segments=bound,
    )


def write_narration_segments(
    document: NarrationSegmentsDocument,
    output_path: str | Path,
) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(document.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target
