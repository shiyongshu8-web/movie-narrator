# SPDX-License-Identifier: AGPL-3.0-or-later

"""Logical ChatCut track plan used before applying real project edits."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ...alignment.models import SyncMapDocument


CHATCUT_TRACKS = {
    "V1": "original_picture",
    "V2": "b_roll",
    "V3": "graphics",
    "A1": "original_audio",
    "A2": "narration",
    "A3": "bgm",
    "A4": "sfx",
    "C1": "captions",
}


class ChatCutTimelineItemPlan(BaseModel):
    sync_id: str
    narration_id: str
    track: Literal["V1", "V2", "V3", "A1", "A2", "A3", "A4", "C1"]
    editable_role: str
    timeline_start: float | None = None
    timeline_end: float | None = None
    source_start: float | None = None
    source_end: float | None = None
    status: Literal["PLANNED", "READBACK_REQUIRED"] = "READBACK_REQUIRED"


class ChatCutTimelinePlan(BaseModel):
    backend: Literal["chatcut"] = "chatcut"
    tracks: dict[str, str] = Field(default_factory=lambda: dict(CHATCUT_TRACKS))
    items: list[ChatCutTimelineItemPlan] = Field(min_length=1)
    verification: Literal["PENDING", "PASS", "FAIL"] = "PENDING"


def build_timeline_plan(sync_map: SyncMapDocument) -> ChatCutTimelinePlan:
    items: list[ChatCutTimelineItemPlan] = []
    for row in sync_map.rows:
        items.extend(
            [
                ChatCutTimelineItemPlan(
                    sync_id=row.sync_id,
                    narration_id=row.narration_id,
                    track="V1",
                    editable_role="original_picture",
                    timeline_start=row.timeline_start,
                    timeline_end=row.timeline_end,
                    source_start=row.source_start,
                    source_end=row.source_end,
                ),
                ChatCutTimelineItemPlan(
                    sync_id=row.sync_id,
                    narration_id=row.narration_id,
                    track="A2",
                    editable_role="narration",
                    timeline_start=row.timeline_start,
                    timeline_end=(
                        row.timeline_start + row.tts_duration
                        if row.timeline_start is not None and row.tts_duration is not None
                        else None
                    ),
                ),
                ChatCutTimelineItemPlan(
                    sync_id=row.sync_id,
                    narration_id=row.narration_id,
                    track="C1",
                    editable_role="captions",
                    timeline_start=row.timeline_start,
                    timeline_end=(
                        row.timeline_start + row.tts_duration
                        if row.timeline_start is not None and row.tts_duration is not None
                        else None
                    ),
                ),
            ]
        )
    return ChatCutTimelinePlan(items=items)
