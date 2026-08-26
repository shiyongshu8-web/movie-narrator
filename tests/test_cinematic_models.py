import pytest
from pydantic import ValidationError

from movie_narrator.cinematic.models import SceneDatabase, SceneRecord


def test_scene_database_requires_unique_ordered_scenes():
    scene = SceneRecord(scene_id="SCN-0001", start_time=0, end_time=2)
    database = SceneDatabase(
        source_video="movie.mp4",
        source_sha256="abc",
        scene_detector="test",
        asr_backend="none",
        visual_backend="none",
        scenes=[scene],
    )
    assert database.schema_version == "2.0"

    with pytest.raises(ValidationError):
        SceneDatabase(
            source_video="movie.mp4",
            source_sha256="abc",
            scene_detector="test",
            asr_backend="none",
            visual_backend="none",
            scenes=[scene, scene],
        )


def test_scene_range_is_validated():
    with pytest.raises(ValidationError):
        SceneRecord(scene_id="SCN-0001", start_time=2, end_time=2)
