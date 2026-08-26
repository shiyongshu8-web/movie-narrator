# SPDX-License-Identifier: AGPL-3.0-or-later

"""Persistent top-K retrieval over cinematic scene records."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from ..cinematic.models import NarrationSegment, SceneCandidate, SceneDatabase, SceneMatch
from .embeddings import HashingTextEmbedder, TextEmbedder, Vector, VisualEmbedder, cosine


def _scene_text(scene) -> str:
    dialogue = " ".join(cue.text for cue in scene.dialogue)
    characters = " ".join(scene.characters)
    return " ".join(
        part
        for part in (
            scene.visual_description,
            scene.location,
            scene.action,
            scene.emotion,
            characters,
            dialogue,
        )
        if part and part != "UNKNOWN"
    ) or scene.scene_id


class SceneMemory:
    def __init__(
        self,
        database: SceneDatabase,
        text_embedder: TextEmbedder | None = None,
        visual_embedder: VisualEmbedder | None = None,
        *,
        text_weight: float = 0.75,
        visual_weight: float = 0.25,
    ) -> None:
        if text_weight < 0 or visual_weight < 0 or text_weight + visual_weight <= 0:
            raise ValueError("embedding weights must be non-negative and not both zero")
        self.database = database
        self.text_embedder = text_embedder or HashingTextEmbedder()
        self.visual_embedder = visual_embedder
        total = text_weight + visual_weight
        self.text_weight = text_weight / total
        self.visual_weight = visual_weight / total
        self._scene_text_vectors = self.text_embedder.encode(
            [_scene_text(scene) for scene in database.scenes]
        )
        self._scene_visual_vectors: list[Vector] | None = None
        if visual_embedder and all(scene.thumbnail_path for scene in database.scenes):
            self._scene_visual_vectors = visual_embedder.encode_images(
                [scene.thumbnail_path or "" for scene in database.scenes]
            )

    def retrieve(
        self,
        narration: NarrationSegment,
        *,
        top_k: int = 5,
        query_image: str | None = None,
    ) -> SceneMatch:
        if top_k <= 0:
            raise ValueError("top_k must be greater than zero")
        query = f"{narration.target_scene} {narration.narration} {narration.emotion}"
        query_text_vector = self.text_embedder.encode([query])[0]
        query_visual_vector: Vector | None = None
        if self.visual_embedder and self._scene_visual_vectors:
            query_visual_vector = (
                self.visual_embedder.encode_images([query_image])[0]
                if query_image
                else self.visual_embedder.encode_texts([query])[0]
            )

        candidates: list[SceneCandidate] = []
        for index, scene in enumerate(self.database.scenes):
            text_score = cosine(query_text_vector, self._scene_text_vectors[index])
            visual_score = None
            combined = text_score
            if query_visual_vector is not None and self._scene_visual_vectors is not None:
                visual_score = cosine(query_visual_vector, self._scene_visual_vectors[index])
                combined = self.text_weight * text_score + self.visual_weight * visual_score
            candidates.append(
                SceneCandidate(
                    scene_id=scene.scene_id,
                    text_score=max(-1.0, min(1.0, text_score)),
                    visual_score=(
                        max(-1.0, min(1.0, visual_score)) if visual_score is not None else None
                    ),
                    similarity_score=max(-1.0, min(1.0, combined)),
                )
            )
        candidates.sort(key=lambda item: item.similarity_score, reverse=True)
        selected = candidates[0].scene_id if candidates else None
        return SceneMatch(
            narration_segment_id=narration.id,
            candidates=candidates[: min(top_k, len(candidates))],
            selected_scene_id=selected,
            selection_status="CANDIDATE",
        )

    def match_all(self, narrations: Sequence[NarrationSegment], top_k: int = 5) -> list[SceneMatch]:
        return [self.retrieve(narration, top_k=top_k) for narration in narrations]

    @staticmethod
    def write_matches(matches: Sequence[SceneMatch], output_path: str | Path) -> Path:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": "2.0",
            "matches": [match.model_dump(mode="json") for match in matches],
        }
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return target
