# SPDX-License-Identifier: AGPL-3.0-or-later

"""Versioned data contracts for the cinematic multi-track pipeline."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


SCHEMA_VERSION = "2.0"


class VerificationStatus(str, Enum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    UNKNOWN = "UNKNOWN"


class AnalysisStatus(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNVERIFIED = "UNVERIFIED"


class DialogueCue(BaseModel):
    start_time: float = Field(ge=0)
    end_time: float = Field(gt=0)
    text: str
    speaker: str = "UNKNOWN"
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    source: str = "ASR"

    @model_validator(mode="after")
    def validate_range(self) -> "DialogueCue":
        if self.end_time <= self.start_time:
            raise ValueError("dialogue end_time must be greater than start_time")
        return self


class VisualAnalysis(BaseModel):
    characters: list[str] = Field(default_factory=list)
    location: str = "UNKNOWN"
    action: str = "UNKNOWN"
    emotion: str = "UNKNOWN"
    visual_description: str = "UNKNOWN"
    importance_score: float = Field(default=0.5, ge=0, le=1)
    status: AnalysisStatus = AnalysisStatus.UNVERIFIED


class SceneRecord(BaseModel):
    scene_id: str
    start_time: float = Field(ge=0)
    end_time: float = Field(gt=0)
    characters: list[str] = Field(default_factory=list)
    location: str = "UNKNOWN"
    action: str = "UNKNOWN"
    emotion: str = "UNKNOWN"
    dialogue: list[DialogueCue] = Field(default_factory=list)
    visual_description: str = "UNKNOWN"
    importance_score: float = Field(default=0.5, ge=0, le=1)
    analysis_status: AnalysisStatus = AnalysisStatus.UNVERIFIED
    thumbnail_path: str | None = None

    @model_validator(mode="after")
    def validate_range(self) -> "SceneRecord":
        if self.end_time <= self.start_time:
            raise ValueError("scene end_time must be greater than start_time")
        return self


class SceneDatabase(BaseModel):
    schema_version: Literal["2.0"] = SCHEMA_VERSION
    source_video: str
    source_sha256: str
    scene_detector: str
    asr_backend: str
    asr_status: VerificationStatus = VerificationStatus.UNKNOWN
    visual_backend: str
    visual_status: AnalysisStatus = AnalysisStatus.UNVERIFIED
    scenes: list[SceneRecord]

    @model_validator(mode="after")
    def validate_scenes(self) -> "SceneDatabase":
        if not self.scenes:
            raise ValueError("scene database must contain at least one scene")
        ids = [scene.scene_id for scene in self.scenes]
        if len(ids) != len(set(ids)):
            raise ValueError("scene_id values must be unique")
        starts = [scene.start_time for scene in self.scenes]
        if starts != sorted(starts):
            raise ValueError("scenes must be ordered by start_time")
        return self


class NarrationSegment(BaseModel):
    id: str
    narration: str
    target_scene: str
    emotion: str = "neutral"
    audio_priority: Literal["narration", "dialogue", "climax", "transition"] = "narration"
    estimated_duration: float | None = Field(default=None, gt=0)
    tts_asset: str | None = None
    tts_duration: float | None = Field(default=None, gt=0)


class SceneCandidate(BaseModel):
    scene_id: str
    text_score: float = Field(ge=-1, le=1)
    visual_score: float | None = Field(default=None, ge=-1, le=1)
    similarity_score: float = Field(ge=-1, le=1)


class SceneMatch(BaseModel):
    narration_segment_id: str
    candidates: list[SceneCandidate]
    selected_scene_id: str | None = None
    selection_status: Literal["CANDIDATE", "LOCKED", "REJECTED"] = "CANDIDATE"


class MatchesDocument(BaseModel):
    schema_version: Literal["2.0"] = SCHEMA_VERSION
    matches: list[SceneMatch]


class AudioDecision(BaseModel):
    narration_segment_id: str
    scene_id: str
    classification: Literal["NARRATION", "DIALOGUE", "CLIMAX", "TRANSITION"]
    narration_enabled: bool
    narration_volume: float = Field(ge=0, le=1)
    original_enabled: bool
    original_volume: float = Field(ge=0, le=1)
    bgm_enabled: bool
    bgm_volume: float = Field(ge=0, le=1)
    protect_dialogue: bool = False
    rule: str


class AudioMixDocument(BaseModel):
    schema_version: Literal["2.0"] = SCHEMA_VERSION
    decisions: list[AudioDecision]


class TrackState(BaseModel):
    enabled: bool
    volume: float = Field(ge=0, le=1)
    asset: str | None = None
    duration: float | None = Field(default=None, gt=0)


class VideoTrack(BaseModel):
    scene_id: str
    source_start: float = Field(ge=0)
    source_end: float = Field(gt=0)

    @model_validator(mode="after")
    def validate_range(self) -> "VideoTrack":
        if self.source_end <= self.source_start:
            raise ValueError("video source_end must be greater than source_start")
        return self


class AudioTracks(BaseModel):
    narration: TrackState
    original: TrackState
    bgm: TrackState


class SubtitleTrack(BaseModel):
    text: str
    start: float = Field(ge=0)
    end: float = Field(gt=0)


class TimelineMatchInfo(BaseModel):
    similarity_score: float = Field(ge=-1, le=1)
    selection_status: Literal["CANDIDATE", "LOCKED", "REJECTED"]


class TimelineItem(BaseModel):
    timeline_id: str
    narration_segment_id: str
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    video: VideoTrack
    audio: AudioTracks
    subtitle: SubtitleTrack | None = None
    match: TimelineMatchInfo
    protected_dialogue: list[DialogueCue] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_range(self) -> "TimelineItem":
        if self.end <= self.start:
            raise ValueError("timeline end must be greater than start")
        return self


class TimelineDocument(BaseModel):
    schema_version: Literal["2.0"] = SCHEMA_VERSION
    timebase: Literal["seconds"] = "seconds"
    source_video: str
    duration: float = Field(gt=0)
    items: list[TimelineItem]


class QualityIssue(BaseModel):
    check_id: str
    severity: Literal["INFO", "WARNING", "ERROR"]
    timeline_id: str | None = None
    message: str
    evidence: dict[str, Any] = Field(default_factory=dict)


class QualityReport(BaseModel):
    schema_version: Literal["2.0"] = SCHEMA_VERSION
    status: Literal["PASS", "FAIL", "PASS_WITH_UNKNOWN"]
    issues: list[QualityIssue] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
