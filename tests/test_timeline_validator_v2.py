from movie_narrator.cinematic.models import (
    AudioTracks,
    DialogueCue,
    SubtitleTrack,
    TimelineDocument,
    TimelineItem,
    TimelineMatchInfo,
    TrackState,
    VerificationStatus,
    VideoTrack,
)
from movie_narrator.timeline import TimelineValidator


def _timeline(*, locked=True, narration_volume=0.8, original_volume=0.1, dialogue=None):
    item = TimelineItem(
        timeline_id="TL-0001",
        narration_segment_id="N1",
        start=0,
        end=5,
        video=VideoTrack(scene_id="SCN-0001", source_start=10, source_end=15),
        audio=AudioTracks(
            narration=TrackState(
                enabled=True,
                volume=narration_volume,
                asset="n1.mp3",
                duration=2,
            ),
            original=TrackState(enabled=True, volume=original_volume),
            bgm=TrackState(enabled=True, volume=0.2, asset="bgm.mp3"),
        ),
        subtitle=SubtitleTrack(text="旁白", start=0, end=2),
        match=TimelineMatchInfo(
            similarity_score=0.8,
            selection_status="LOCKED" if locked else "CANDIDATE",
        ),
        protected_dialogue=dialogue or [],
    )
    return TimelineDocument(source_video="movie.mp4", duration=5, items=[item])


def test_validator_passes_locked_non_conflicting_timeline(tmp_path):
    report = TimelineValidator().validate(_timeline())
    assert report.status == "PASS"
    target = TimelineValidator.write(report, tmp_path / "quality_report.json")
    assert target.exists()
    assert not target.with_name("timeline_quality_report.json").exists()


def test_validator_keeps_candidate_semantics_unknown():
    report = TimelineValidator().validate(_timeline(locked=False))
    assert report.status == "PASS_WITH_UNKNOWN"
    assert "SEMANTIC_AV_ALIGNMENT_REQUIRES_REVIEW" in report.unknowns


def test_validator_blocks_verified_dialogue_overlap():
    dialogue = [
        DialogueCue(
            start_time=11,
            end_time=13,
            text="经典对白",
            verification_status=VerificationStatus.VERIFIED,
        )
    ]
    report = TimelineValidator().validate(
        _timeline(narration_volume=0.3, original_volume=1, dialogue=dialogue)
    )
    assert report.status == "FAIL"
    assert any(issue.check_id == "DIALOGUE_OVERLAP" for issue in report.issues)


def test_validator_allows_verified_dialogue_outside_narration_window():
    dialogue = [
        DialogueCue(
            start_time=13,
            end_time=14,
            text="旁白结束后的对白",
            verification_status=VerificationStatus.VERIFIED,
        )
    ]
    report = TimelineValidator().validate(
        _timeline(narration_volume=0.3, original_volume=1, dialogue=dialogue)
    )
    assert report.status == "PASS"


def test_validator_blocks_muted_verified_dialogue_even_without_narration_overlap():
    dialogue = [
        DialogueCue(
            start_time=13,
            end_time=14,
            text="应保留对白",
            verification_status=VerificationStatus.VERIFIED,
        )
    ]
    report = TimelineValidator().validate(
        _timeline(narration_volume=0.1, original_volume=0.2, dialogue=dialogue)
    )
    assert report.status == "FAIL"
    assert any(
        issue.check_id == "VERIFIED_DIALOGUE_NOT_AUDIBLE" for issue in report.issues
    )


def test_validator_blocks_narration_and_subtitle_duration_mismatch():
    timeline = _timeline()
    timeline.items[0].audio.narration.duration = 4
    report = TimelineValidator().validate(timeline)
    assert report.status == "FAIL"
    ids = {issue.check_id for issue in report.issues}
    assert "SUBTITLE_NARRATION_DESYNC" in ids


def test_validator_blocks_subtitle_outside_item():
    timeline = _timeline()
    timeline.items[0].subtitle.end = 6
    report = TimelineValidator().validate(timeline)
    assert report.status == "FAIL"
    assert any(issue.check_id == "SUBTITLE_OUT_OF_BOUNDS" for issue in report.issues)


def test_validator_blocks_foreground_audio_collision():
    report = TimelineValidator().validate(
        _timeline(narration_volume=0.9, original_volume=0.8)
    )
    assert report.status == "FAIL"
    assert any(issue.check_id == "AUDIO_LANGUAGE_COLLISION" for issue in report.issues)
