from movie_narrator.cinematic.models import (
    AudioDecision,
    NarrationSegment,
    SceneCandidate,
    SceneDatabase,
    SceneMatch,
    SceneRecord,
)
from movie_narrator.timeline import TimelineBuilder


def _match(narration_id, scene_id, status="LOCKED"):
    return SceneMatch(
        narration_segment_id=narration_id,
        candidates=[
            SceneCandidate(
                scene_id=scene_id,
                text_score=0.8,
                similarity_score=0.8,
            )
        ],
        selected_scene_id=scene_id,
        selection_status=status,
    )


def _decision(narration_id, scene_id):
    return AudioDecision(
        narration_segment_id=narration_id,
        scene_id=scene_id,
        classification="NARRATION",
        narration_enabled=True,
        narration_volume=1,
        original_enabled=True,
        original_volume=0.1,
        bgm_enabled=True,
        bgm_volume=0.3,
        rule="test",
    )


def test_master_timeline_is_driven_by_source_scene_duration(tmp_path):
    database = SceneDatabase(
        source_video="movie.mp4",
        source_sha256="abc",
        scene_detector="stub",
        asr_backend="none",
        visual_backend="none",
        scenes=[
            SceneRecord(scene_id="SCN-0001", start_time=10, end_time=15),
            SceneRecord(scene_id="SCN-0002", start_time=30, end_time=37),
        ],
    )
    narrations = [
        NarrationSegment(
            id="N1",
            narration="第一段",
            target_scene="场景一",
            tts_asset="n1.mp3",
            tts_duration=2,
        ),
        NarrationSegment(
            id="N2",
            narration="第二段",
            target_scene="场景二",
            tts_asset="n2.mp3",
            tts_duration=3,
        ),
    ]
    timeline = TimelineBuilder().build(
        source_video="movie.mp4",
        narrations=narrations,
        matches=[_match("N1", "SCN-0001"), _match("N2", "SCN-0002")],
        decisions=[_decision("N1", "SCN-0001"), _decision("N2", "SCN-0002")],
        scene_database=database,
        bgm_asset="bgm.mp3",
    )

    assert timeline.duration == 12
    assert [(item.start, item.end) for item in timeline.items] == [(0, 5), (5, 12)]
    assert timeline.items[0].subtitle.end == 2
    assert timeline.items[1].subtitle.end == 8
    assert TimelineBuilder.write(timeline, tmp_path / "timeline.json").exists()


def test_builder_rejects_narration_longer_than_source_scene():
    database = SceneDatabase(
        source_video="movie.mp4",
        source_sha256="abc",
        scene_detector="stub",
        asr_backend="none",
        visual_backend="none",
        scenes=[SceneRecord(scene_id="SCN-0001", start_time=0, end_time=2)],
    )
    narration = NarrationSegment(
        id="N1",
        narration="太长",
        target_scene="短镜头",
        tts_asset="n1.mp3",
        tts_duration=3,
    )
    try:
        TimelineBuilder().build(
            source_video="movie.mp4",
            narrations=[narration],
            matches=[_match("N1", "SCN-0001")],
            decisions=[_decision("N1", "SCN-0001")],
            scene_database=database,
        )
    except ValueError as exc:
        assert "exceeds selected source scene" in str(exc)
    else:
        raise AssertionError("overflow narration must fail")
