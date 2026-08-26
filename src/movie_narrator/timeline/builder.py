# SPDX-License-Identifier: AGPL-3.0-or-later

"""Build the cinematic master timeline from selected source-shot durations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from ..cinematic.models import (
    AudioDecision,
    AudioTracks,
    NarrationSegment,
    SceneDatabase,
    SceneMatch,
    SubtitleTrack,
    TimelineDocument,
    TimelineItem,
    TimelineMatchInfo,
    TrackState,
    VideoTrack,
)


class TimelineBuilder:
    def build(
        self,
        *,
        source_video: str,
        narrations: Sequence[NarrationSegment],
        matches: Sequence[SceneMatch],
        decisions: Sequence[AudioDecision],
        scene_database: SceneDatabase,
        bgm_asset: str | None = None,
        require_tts_timing: bool = True,
    ) -> TimelineDocument:
        match_by_narration = {item.narration_segment_id: item for item in matches}
        decision_by_narration = {
            item.narration_segment_id: item for item in decisions
        }
        scene_by_id = {item.scene_id: item for item in scene_database.scenes}
        if len(match_by_narration) != len(matches):
            raise ValueError("matches contain duplicate narration_segment_id values")
        if len(decision_by_narration) != len(decisions):
            raise ValueError("audio decisions contain duplicate narration_segment_id values")

        cursor = 0.0
        items: list[TimelineItem] = []
        for index, narration in enumerate(narrations, start=1):
            match = match_by_narration.get(narration.id)
            decision = decision_by_narration.get(narration.id)
            if match is None or decision is None:
                raise ValueError(f"missing match or audio decision for {narration.id}")
            if not match.selected_scene_id or match.selected_scene_id not in scene_by_id:
                raise ValueError(f"missing selected scene for {narration.id}")
            scene = scene_by_id[match.selected_scene_id]
            if decision.scene_id != scene.scene_id:
                raise ValueError(f"audio decision scene mismatch for {narration.id}")
            if not match.candidates:
                raise ValueError(f"match has no candidate scores for {narration.id}")

            source_duration = scene.end_time - scene.start_time
            item_start = cursor
            item_end = item_start + source_duration
            narration_duration = narration.tts_duration or narration.estimated_duration
            if decision.narration_enabled and require_tts_timing and narration.tts_duration is None:
                raise ValueError(f"verified TTS duration is required for {narration.id}")
            if decision.narration_enabled and narration_duration is None:
                raise ValueError(f"narration timing is unavailable for {narration.id}")
            if narration_duration is not None and narration_duration > source_duration + 1e-6:
                raise ValueError(
                    f"narration {narration.id} duration exceeds selected source scene"
                )

            subtitle = None
            if decision.narration_enabled and narration_duration is not None:
                subtitle = SubtitleTrack(
                    text=narration.narration,
                    start=item_start,
                    end=item_start + narration_duration,
                )
            selected_candidate = next(
                (
                    candidate
                    for candidate in match.candidates
                    if candidate.scene_id == scene.scene_id
                ),
                match.candidates[0],
            )
            items.append(
                TimelineItem(
                    timeline_id=f"TL-{index:04d}",
                    narration_segment_id=narration.id,
                    start=item_start,
                    end=item_end,
                    video=VideoTrack(
                        scene_id=scene.scene_id,
                        source_start=scene.start_time,
                        source_end=scene.end_time,
                    ),
                    audio=AudioTracks(
                        narration=TrackState(
                            enabled=decision.narration_enabled,
                            volume=decision.narration_volume,
                            asset=narration.tts_asset,
                            duration=(
                                narration_duration if decision.narration_enabled else None
                            ),
                        ),
                        original=TrackState(
                            enabled=decision.original_enabled,
                            volume=decision.original_volume,
                            duration=source_duration,
                        ),
                        bgm=TrackState(
                            enabled=decision.bgm_enabled and bool(bgm_asset),
                            volume=decision.bgm_volume,
                            asset=bgm_asset,
                            duration=(
                                source_duration
                                if decision.bgm_enabled and bool(bgm_asset)
                                else None
                            ),
                        ),
                    ),
                    subtitle=subtitle,
                    match=TimelineMatchInfo(
                        similarity_score=selected_candidate.similarity_score,
                        selection_status=match.selection_status,
                    ),
                    protected_dialogue=list(scene.dialogue),
                )
            )
            cursor = item_end

        if not items:
            raise ValueError("timeline requires at least one narration/scene item")
        return TimelineDocument(
            source_video=str(Path(source_video)),
            duration=cursor,
            items=items,
        )

    @staticmethod
    def write(timeline: TimelineDocument, output_path: str | Path) -> Path:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(timeline.model_dump(mode="json"), ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        return target
