# SPDX-License-Identifier: AGPL-3.0-or-later

"""Build a conservative visual event index from the existing scene database."""

from __future__ import annotations

import json
from pathlib import Path

from ..cinematic.models import AnalysisStatus, SceneDatabase
from .models import VisualEvent, VisualEventIndex


def _scene_event(scene, *, index: int) -> VisualEvent:
    action = scene.action if scene.action != "UNKNOWN" else scene.visual_description
    visual_status = scene.analysis_status is AnalysisStatus.COMPLETE
    asr_context = " ".join(cue.text for cue in scene.dialogue).strip()
    # The middle of a shot is a locator candidate only.  It is not a verified
    # word-level or action-level anchor until a reviewer/visual readback locks it.
    midpoint = (scene.start_time + scene.end_time) / 2.0
    confidence = 0.7 if visual_status else 0.35
    if scene.dialogue:
        confidence += 0.05
    confidence = min(confidence, 0.8)
    return VisualEvent(
        event_id=f"EVT-{index:04d}",
        source_start=scene.start_time,
        source_end=scene.end_time,
        shot_ids=[scene.scene_id],
        characters=list(scene.characters),
        location=scene.location,
        visual_action=action or "UNKNOWN",
        # Story interpretation is intentionally not invented from a single
        # shot.  A later editorial pass may replace this with a locked value.
        story_event="UNKNOWN",
        dialogue_context=asr_context,
        importance=scene.importance_score,
        confidence=confidence,
        critical=scene.importance_score >= 0.8,
        review_status="CANDIDATE",
        anchor_source_time=midpoint,
        anchor_basis="SCENE_MIDPOINT_CANDIDATE",
        evidence={
            "scene_id": scene.scene_id,
            "visual_status": scene.analysis_status.value,
            "dialogue_status": (
                "UNVERIFIED" if scene.dialogue else "UNKNOWN"
            ),
            "source_first": True,
        },
    )


def build_visual_event_index(
    scene_database: SceneDatabase | str | Path,
    output_path: str | Path | None = None,
) -> VisualEventIndex:
    """Build and optionally write ``VISUAL_EVENT_INDEX.json``.

    Only evidence already present in ``SceneDatabase`` is carried forward.
    There is no frame-by-frame scan and no free-form story generation here.
    """

    source_path: Path | None = None
    if isinstance(scene_database, SceneDatabase):
        database = scene_database
    else:
        source_path = Path(scene_database).resolve()
        database = SceneDatabase.model_validate_json(source_path.read_text(encoding="utf-8"))

    events = [_scene_event(scene, index=i) for i, scene in enumerate(database.scenes, 1)]
    index = VisualEventIndex(
        source_video=database.source_video,
        source_sha256=database.source_sha256,
        scene_database_path=str(source_path) if source_path else "IN_MEMORY",
        index_status=(
            "EVENT_INDEXED"
            if database.visual_status is AnalysisStatus.COMPLETE
            else "UNVERIFIED"
        ),
        events=events,
    )
    if output_path is not None:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(index.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return index


def load_visual_event_index(path: str | Path) -> VisualEventIndex:
    return VisualEventIndex.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )
