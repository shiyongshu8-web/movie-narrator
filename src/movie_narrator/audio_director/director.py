# SPDX-License-Identifier: AGPL-3.0-or-later

"""Decide narration, original-audio, and BGM priority per matched scene."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from ..cinematic.models import (
    AudioDecision,
    AudioMixDocument,
    NarrationSegment,
    SceneDatabase,
    SceneMatch,
    VerificationStatus,
)


_CLIMAX_TERMS = {
    "冲突",
    "告白",
    "反转",
    "死亡",
    "比赛",
    "climax",
    "conflict",
    "confession",
    "reversal",
    "death",
    "race",
}


class AudioDirector:
    def direct(
        self,
        narrations: Sequence[NarrationSegment],
        matches: Sequence[SceneMatch],
        database: SceneDatabase,
    ) -> list[AudioDecision]:
        narration_by_id = {item.id: item for item in narrations}
        scene_by_id = {scene.scene_id: scene for scene in database.scenes}
        decisions: list[AudioDecision] = []
        for match in matches:
            narration = narration_by_id.get(match.narration_segment_id)
            if narration is None:
                raise ValueError(
                    f"match references missing narration: {match.narration_segment_id}"
                )
            if not match.selected_scene_id or match.selected_scene_id not in scene_by_id:
                raise ValueError(
                    f"match has no valid selected scene: {match.narration_segment_id}"
                )
            scene = scene_by_id[match.selected_scene_id]
            decisions.append(self._decide(narration, scene))
        return decisions

    @staticmethod
    def write(decisions: Sequence[AudioDecision], output_path: str | Path) -> Path:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        document = AudioMixDocument(decisions=list(decisions))
        target.write_text(
            json.dumps(document.model_dump(mode="json"), ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        return target

    def _decide(self, narration: NarrationSegment, scene) -> AudioDecision:
        has_dialogue = bool(scene.dialogue)
        verified_dialogue = any(
            cue.verification_status is VerificationStatus.VERIFIED
            for cue in scene.dialogue
        )
        priority = narration.audio_priority
        # ASR output is a retrieval candidate, not verified editorial dialogue.
        # Only an explicit script decision or a VERIFIED cue may silence narration.
        if priority == "dialogue" or verified_dialogue:
            return AudioDecision(
                narration_segment_id=narration.id,
                scene_id=scene.scene_id,
                classification="DIALOGUE",
                narration_enabled=False,
                narration_volume=0.0,
                original_enabled=True,
                original_volume=1.0,
                bgm_enabled=False,
                bgm_volume=0.0,
                protect_dialogue=verified_dialogue,
                rule=(
                    "script_requested_dialogue_foreground"
                    if priority == "dialogue" and not verified_dialogue
                    else "verified_dialogue_foreground"
                ),
            )

        climax = (
            priority == "climax"
            or scene.importance_score >= 0.8
            or any(term in f"{scene.action} {scene.emotion}".lower() for term in _CLIMAX_TERMS)
        )
        if climax:
            return AudioDecision(
                narration_segment_id=narration.id,
                scene_id=scene.scene_id,
                classification="CLIMAX",
                narration_enabled=True,
                narration_volume=0.25,
                original_enabled=True,
                original_volume=0.9,
                bgm_enabled=True,
                bgm_volume=0.2,
                protect_dialogue=False,
                rule="climax_preserve_source_energy",
            )

        if priority == "transition":
            return AudioDecision(
                narration_segment_id=narration.id,
                scene_id=scene.scene_id,
                classification="TRANSITION",
                narration_enabled=True,
                narration_volume=0.8,
                original_enabled=True,
                original_volume=0.2,
                bgm_enabled=True,
                bgm_volume=0.3,
                protect_dialogue=False,
                rule="transition_bridge",
            )

        return AudioDecision(
            narration_segment_id=narration.id,
            scene_id=scene.scene_id,
            classification="NARRATION",
            narration_enabled=True,
            narration_volume=1.0,
            original_enabled=True,
            original_volume=0.2 if has_dialogue else 0.1,
            bgm_enabled=True,
            bgm_volume=0.3,
            protect_dialogue=False,
            rule="background_or_plot_exposition",
        )
