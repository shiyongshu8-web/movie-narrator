import json

import pytest

from movie_narrator.cinematic.models import (
    MatchesDocument,
    SceneCandidate,
    SceneDatabase,
    SceneMatch,
    SceneRecord,
)
from movie_narrator.cinematic.review import lock_matches


def _inputs(tmp_path):
    matches = tmp_path / "matches.json"
    matches.write_text(
        MatchesDocument(
            matches=[
                SceneMatch(
                    narration_segment_id="N1",
                    candidates=[
                        SceneCandidate(scene_id="S1", text_score=0.9, similarity_score=0.9),
                        SceneCandidate(scene_id="S2", text_score=0.8, similarity_score=0.8),
                    ],
                    selected_scene_id="S1",
                )
            ]
        ).model_dump_json(),
        encoding="utf-8",
    )
    scenes = tmp_path / "scene_database.json"
    scenes.write_text(
        SceneDatabase(
            source_video="movie.mp4",
            source_sha256="abc",
            scene_detector="stub",
            asr_backend="none",
            visual_backend="none",
            scenes=[
                SceneRecord(scene_id="S1", start_time=0, end_time=2),
                SceneRecord(scene_id="S2", start_time=2, end_time=4),
            ],
        ).model_dump_json(),
        encoding="utf-8",
    )
    return matches, scenes


def test_lock_matches_creates_locked_copy_and_hash_manifest(tmp_path):
    matches, scenes = _inputs(tmp_path)
    selections = tmp_path / "selections.json"
    selections.write_text(json.dumps({"N1": "S2"}), encoding="utf-8")
    output, manifest = lock_matches(
        matches_path=matches,
        selections_path=selections,
        scene_database_path=scenes,
        output_path=tmp_path / "matches.locked.json",
    )

    locked = MatchesDocument.model_validate_json(output.read_text(encoding="utf-8"))
    assert locked.matches[0].selected_scene_id == "S2"
    assert locked.matches[0].selection_status == "LOCKED"
    assert json.loads(manifest.read_text(encoding="utf-8"))["status"] == "LOCKED"


def test_lock_matches_rejects_selection_outside_top_k(tmp_path):
    matches, scenes = _inputs(tmp_path)
    selections = tmp_path / "selections.json"
    selections.write_text(json.dumps({"N1": "S3"}), encoding="utf-8")
    with pytest.raises(ValueError, match="does not exist"):
        lock_matches(
            matches_path=matches,
            selections_path=selections,
            scene_database_path=scenes,
            output_path=tmp_path / "locked.json",
        )
