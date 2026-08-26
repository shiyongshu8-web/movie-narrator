# SPDX-License-Identifier: AGPL-3.0-or-later

"""Generate scene-bound narration segments instead of a free-form script blob."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import NarrationSegment, SceneDatabase


class CinematicScriptGenerator:
    def __init__(self, client: Any, model: str) -> None:
        self.client = client
        self.model = model

    def generate(
        self,
        scene_database: SceneDatabase,
        *,
        style: str,
        target_duration: int,
        story_context: str = "",
    ) -> list[NarrationSegment]:
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0.4,
            messages=[
                {"role": "system", "content": self._system_prompt()},
                {
                    "role": "user",
                    "content": self._user_prompt(
                        scene_database,
                        style=style,
                        target_duration=target_duration,
                        story_context=story_context,
                    ),
                },
            ],
        )
        content = response.choices[0].message.content or ""
        payload = self._parse_payload(content)
        segments = [NarrationSegment.model_validate(item) for item in payload]
        self._validate_segments(segments)
        return segments

    @staticmethod
    def write_segments(
        segments: list[NarrationSegment], output_path: str | Path
    ) -> Path:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": "2.0",
            "segments": [segment.model_dump(mode="json") for segment in segments],
        }
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return target

    @staticmethod
    def _system_prompt() -> str:
        return (
            "You are a cinematic recap editor. Return a JSON array only. "
            "Do not return a free-form narration script. Each item must contain "
            "id, narration, target_scene, emotion, and audio_priority. "
            "audio_priority must be narration, dialogue, climax, or transition. "
            "Bind every narration sentence to visible source evidence. Do not invent "
            "dialogue, character identity, action, or timecode when the scene database "
            "says UNKNOWN or UNVERIFIED. Reserve dialogue/climax items so narration can yield."
        )

    @staticmethod
    def _user_prompt(
        database: SceneDatabase,
        *,
        style: str,
        target_duration: int,
        story_context: str,
    ) -> str:
        compact_scenes = []
        for scene in database.scenes:
            compact_scenes.append(
                {
                    "scene_id": scene.scene_id,
                    "time": [scene.start_time, scene.end_time],
                    "characters": scene.characters,
                    "location": scene.location,
                    "action": scene.action,
                    "emotion": scene.emotion,
                    "visual_description": scene.visual_description,
                    "importance_score": scene.importance_score,
                    "dialogue_candidates": [cue.text for cue in scene.dialogue],
                }
            )
        return json.dumps(
            {
                "task": "Generate structured NarrationSegment objects",
                "style": style,
                "target_duration_seconds": target_duration,
                "story_context": story_context,
                "scenes": compact_scenes,
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _parse_payload(content: str) -> list[dict]:
        text = content.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1]).strip()
        payload = json.loads(text)
        if isinstance(payload, dict):
            payload = payload.get("segments")
        if not isinstance(payload, list):
            raise ValueError("cinematic script response must be a JSON array")
        if not payload:
            raise ValueError("cinematic script response contains no segments")
        if not all(isinstance(item, dict) for item in payload):
            raise ValueError("each cinematic script segment must be a JSON object")
        return payload

    @staticmethod
    def _validate_segments(segments: list[NarrationSegment]) -> None:
        ids = [segment.id for segment in segments]
        if len(ids) != len(set(ids)):
            raise ValueError("narration segment IDs must be unique")
        for segment in segments:
            if not segment.narration.strip():
                raise ValueError(f"{segment.id} narration must not be empty")
            if not segment.target_scene.strip():
                raise ValueError(f"{segment.id} target_scene must not be empty")
