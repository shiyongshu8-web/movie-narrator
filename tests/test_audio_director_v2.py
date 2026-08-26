from movie_narrator.audio_director import AudioDirector
from movie_narrator.cinematic.models import (
    DialogueCue,
    NarrationSegment,
    SceneCandidate,
    SceneDatabase,
    SceneMatch,
    SceneRecord,
    VerificationStatus,
)


def _match(narration_id, scene_id):
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
    )


def test_audio_director_applies_four_priority_classes(tmp_path):
    scenes = [
        SceneRecord(scene_id="SCN-0001", start_time=0, end_time=5),
        SceneRecord(
            scene_id="SCN-0002",
            start_time=5,
            end_time=10,
            dialogue=[
                DialogueCue(
                    start_time=6,
                    end_time=8,
                    text="留下这句对白",
                    verification_status=VerificationStatus.VERIFIED,
                )
            ],
        ),
        SceneRecord(
            scene_id="SCN-0003",
            start_time=10,
            end_time=15,
            importance_score=0.9,
        ),
        SceneRecord(scene_id="SCN-0004", start_time=15, end_time=20),
    ]
    database = SceneDatabase(
        source_video="movie.mp4",
        source_sha256="abc",
        scene_detector="stub",
        asr_backend="stub",
        visual_backend="stub",
        scenes=scenes,
    )
    narrations = [
        NarrationSegment(id="N1", narration="背景", target_scene="背景"),
        NarrationSegment(
            id="N2",
            narration="对白留白",
            target_scene="对白",
            audio_priority="dialogue",
        ),
        NarrationSegment(
            id="N3",
            narration="高潮",
            target_scene="高潮",
            audio_priority="climax",
        ),
        NarrationSegment(
            id="N4",
            narration="过渡",
            target_scene="过渡",
            audio_priority="transition",
        ),
    ]
    matches = [_match(f"N{index}", f"SCN-{index:04d}") for index in range(1, 5)]
    decisions = AudioDirector().direct(narrations, matches, database)

    assert [item.classification for item in decisions] == [
        "NARRATION",
        "DIALOGUE",
        "CLIMAX",
        "TRANSITION",
    ]
    assert decisions[1].narration_volume == 0
    assert decisions[1].original_volume == 1
    assert decisions[1].protect_dialogue is True
    assert decisions[2].narration_volume == 0.25
    assert decisions[2].original_volume == 0.9
    assert AudioDirector.write(decisions, tmp_path / "audio_mix.json").exists()


def test_audio_director_rejects_missing_selected_scene():
    database = SceneDatabase(
        source_video="movie.mp4",
        source_sha256="abc",
        scene_detector="stub",
        asr_backend="none",
        visual_backend="none",
        scenes=[SceneRecord(scene_id="SCN-0001", start_time=0, end_time=5)],
    )
    narration = NarrationSegment(id="N1", narration="背景", target_scene="背景")
    match = SceneMatch(narration_segment_id="N1", candidates=[])
    try:
        AudioDirector().direct([narration], [match], database)
    except ValueError as exc:
        assert "no valid selected scene" in str(exc)
    else:
        raise AssertionError("missing selected scene must fail")


def test_unverified_dialogue_is_preserved_without_claiming_verification():
    scene = SceneRecord(
        scene_id="SCN-0001",
        start_time=0,
        end_time=5,
        dialogue=[DialogueCue(start_time=1, end_time=2, text="ASR候选")],
    )
    database = SceneDatabase(
        source_video="movie.mp4",
        source_sha256="abc",
        scene_detector="stub",
        asr_backend="stub",
        visual_backend="none",
        scenes=[scene],
    )
    narration = NarrationSegment(id="N1", narration="背景", target_scene="背景")
    decision = AudioDirector().direct(
        [narration], [_match("N1", "SCN-0001")], database
    )[0]
    assert decision.classification == "NARRATION"
    assert decision.narration_enabled is True
    assert decision.original_enabled is True
    assert decision.protect_dialogue is False


def test_verified_dialogue_automatically_takes_foreground():
    scene = SceneRecord(
        scene_id="SCN-0001",
        start_time=0,
        end_time=5,
        dialogue=[
            DialogueCue(
                start_time=1,
                end_time=2,
                text="已人工核验",
                verification_status=VerificationStatus.VERIFIED,
            )
        ],
    )
    database = SceneDatabase(
        source_video="movie.mp4",
        source_sha256="abc",
        scene_detector="stub",
        asr_backend="stub",
        visual_backend="none",
        scenes=[scene],
    )
    narration = NarrationSegment(id="N1", narration="背景", target_scene="背景")
    decision = AudioDirector().direct(
        [narration], [_match("N1", "SCN-0001")], database
    )[0]
    assert decision.classification == "DIALOGUE"
    assert decision.narration_enabled is False
    assert decision.protect_dialogue is True
