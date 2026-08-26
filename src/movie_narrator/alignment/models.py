# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stable, backend-neutral synchronization and QC models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class TimelineItemSnapshot(BaseModel):
    """The small readback projection needed by the alignment engine."""

    item_id: str
    track_id: str = "UNKNOWN"
    track_type: str = "UNKNOWN"
    timeline_start: float = Field(ge=0)
    timeline_end: float = Field(gt=0)
    source_start: float | None = Field(default=None, ge=0)
    source_end: float | None = Field(default=None, gt=0)
    narration_id: str | None = None
    event_ids: list[str] = Field(default_factory=list)
    original_audio_conflict: bool = False
    caption_aligned: bool | None = None

    @model_validator(mode="after")
    def validate_range(self) -> "TimelineItemSnapshot":
        if self.timeline_end <= self.timeline_start:
            raise ValueError("timeline_end must be greater than timeline_start")
        if self.source_start is not None and self.source_end is not None:
            if self.source_end <= self.source_start:
                raise ValueError("source_end must be greater than source_start")
        return self


class SyncMapRow(BaseModel):
    sync_id: str
    narration_id: str
    visual_event_ids: list[str] = Field(min_length=1)
    source_start: float = Field(ge=0)
    source_end: float = Field(gt=0)
    timeline_start: float | None = Field(default=None, ge=0)
    timeline_end: float | None = Field(default=None, gt=0)
    narration_text: str
    tts_duration: float | None = Field(default=None, gt=0)
    visual_anchor: str = "UNKNOWN"
    anchor_source_time: float | None = Field(default=None, ge=0)
    anchor_timeline_time: float | None = Field(default=None, ge=0)
    spoken_anchor_time: float | None = Field(default=None, ge=0)
    semantic_offset: float | None = None
    narration_lead: float | None = Field(default=None, ge=0)
    visual_lead: float | None = Field(default=None, ge=0)
    fit_status: Literal["PASS", "SYNC_FIT_FAIL", "UNKNOWN"] = "UNKNOWN"
    event_match_status: Literal["PASS", "CANDIDATE", "FAIL", "UNKNOWN"] = "UNKNOWN"
    stale_sync_map: bool = False
    original_audio_conflict: bool = False
    caption_aligned: bool | None = None
    critical_event: bool = False
    confidence: float = Field(default=0.0, ge=0, le=1)
    evidence: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_range(self) -> "SyncMapRow":
        if self.source_end <= self.source_start:
            raise ValueError("sync map source_end must be greater than source_start")
        if self.timeline_start is not None and self.timeline_end is not None:
            if self.timeline_end <= self.timeline_start:
                raise ValueError("sync map timeline_end must be greater than timeline_start")
        return self


class SyncMapDocument(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    status: Literal["SYNC_MAPPED", "SYNC_QC", "FAIL", "UNVERIFIED", "STALE"]
    timeline_readback_hash: str | None = None
    rows: list[SyncMapRow] = Field(min_length=1)


class AlignmentIssue(BaseModel):
    check_id: str
    severity: Literal["INFO", "WARNING", "ERROR"]
    sync_id: str | None = None
    message: str
    evidence: dict[str, Any] = Field(default_factory=dict)


class AlignmentReport(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    status: Literal["PASS", "FAIL", "PASS_WITH_UNKNOWN"]
    final_ready: bool = False
    issues: list[AlignmentIssue] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    rows_checked: int = 0
