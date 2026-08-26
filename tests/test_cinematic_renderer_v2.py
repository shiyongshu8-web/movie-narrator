from pathlib import Path
import subprocess

import pytest

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
from movie_narrator.timeline.renderer import CinematicRenderer
from movie_narrator.utils.ffmpeg_bin import ffmpeg_bin


def _timeline(tmp_path: Path, *, bgm: bool = True) -> TimelineDocument:
    source = tmp_path / "movie.mp4"
    narration = tmp_path / "narration.wav"
    music = tmp_path / "music.wav"
    source.touch()
    narration.touch()
    music.touch()
    items = [
        TimelineItem(
            timeline_id="TL-0001",
            narration_segment_id="001",
            start=0,
            end=5,
            video=VideoTrack(scene_id="SC-0001", source_start=10, source_end=15),
            audio=AudioTracks(
                narration=TrackState(enabled=True, volume=1, asset=str(narration)),
                original=TrackState(enabled=True, volume=0.2),
                bgm=TrackState(
                    enabled=bgm,
                    volume=0.3,
                    asset=str(music) if bgm else None,
                ),
            ),
            subtitle=SubtitleTrack(text="第一句", start=0, end=3),
            match=TimelineMatchInfo(similarity_score=0.9, selection_status="LOCKED"),
        ),
        TimelineItem(
            timeline_id="TL-0002",
            narration_segment_id="002",
            start=5,
            end=9,
            video=VideoTrack(scene_id="SC-0002", source_start=20, source_end=24),
            audio=AudioTracks(
                narration=TrackState(enabled=False, volume=0),
                original=TrackState(enabled=True, volume=1),
                bgm=TrackState(
                    enabled=bgm,
                    volume=0.1,
                    asset=str(music) if bgm else None,
                ),
            ),
            match=TimelineMatchInfo(similarity_score=0.8, selection_status="LOCKED"),
            protected_dialogue=[
                DialogueCue(
                    start_time=21,
                    end_time=23,
                    text="别走。",
                    verification_status=VerificationStatus.VERIFIED,
                )
            ],
        ),
    ]
    return TimelineDocument(source_video=str(source), duration=9, items=items)


def test_build_plan_contains_all_tracks_and_ducking(tmp_path, monkeypatch):
    monkeypatch.setattr("movie_narrator.timeline.renderer.ffmpeg_bin", lambda: "ffmpeg")
    monkeypatch.setattr(
        CinematicRenderer, "_source_has_audio", staticmethod(lambda _path: True)
    )
    timeline = _timeline(tmp_path)
    plan = CinematicRenderer().build_plan(timeline, tmp_path / "final.mp4")

    assert "concat=n=2:v=1:a=0[video_master]" in plan.filter_complex
    assert "concat=n=2:v=0:a=1[original_master]" in plan.filter_complex
    assert "sidechaincompress" in plan.filter_complex
    assert "[original_key]" not in plan.filter_complex
    assert "atrim=start=6:end=8" in plan.filter_complex
    assert "atrim=start=5:end=9" in plan.filter_complex
    assert "[bgm_master]" in plan.filter_complex
    assert "subtitles=filename=" in plan.filter_complex
    assert plan.command.count("-i") == 3
    assert plan.command[-1] == str(tmp_path / "final.mp4")


def test_build_plan_can_disable_ducking_and_bgm(tmp_path, monkeypatch):
    monkeypatch.setattr("movie_narrator.timeline.renderer.ffmpeg_bin", lambda: "ffmpeg")
    monkeypatch.setattr(
        CinematicRenderer, "_source_has_audio", staticmethod(lambda _path: True)
    )
    timeline = _timeline(tmp_path, bgm=False)
    plan = CinematicRenderer(enable_ducking=False).build_plan(
        timeline, tmp_path / "preview.mp4"
    )

    assert "sidechaincompress" not in plan.filter_complex
    assert "anullsrc=r=48000:cl=stereo" in plan.filter_complex
    assert plan.command.count("-i") == 2


def test_build_plan_rejects_requested_original_audio_when_source_has_none(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        CinematicRenderer, "_source_has_audio", staticmethod(lambda _path: False)
    )
    with pytest.raises(ValueError, match="source has no audio stream"):
        CinematicRenderer().build_plan(_timeline(tmp_path), tmp_path / "preview.mp4")


def test_build_plan_handles_silent_source_and_empty_subtitles(tmp_path, monkeypatch):
    monkeypatch.setattr(
        CinematicRenderer, "_source_has_audio", staticmethod(lambda _path: False)
    )
    timeline = _timeline(tmp_path, bgm=False)
    for item in timeline.items:
        item.audio.original.enabled = False
        item.audio.original.volume = 0
        item.audio.narration.enabled = False
        item.audio.narration.volume = 0
        item.audio.narration.asset = None
        item.subtitle = None
    plan = CinematicRenderer().build_plan(timeline, tmp_path / "silent.mp4")
    assert "[video_master]null[video_out]" in plan.filter_complex
    assert "subtitles=filename=" not in plan.filter_complex
    assert "anullsrc=r=48000:cl=stereo" in plan.filter_complex


def test_srt_uses_timeline_subtitle_timing(tmp_path):
    timeline = _timeline(tmp_path)
    path = CinematicRenderer.write_srt(timeline, tmp_path / "timeline.srt")
    content = path.read_text(encoding="utf-8-sig")

    assert "00:00:00,000 --> 00:00:03,000" in content
    assert "第一句" in content
    assert "别走" not in content


@pytest.mark.integration
def test_renderer_executes_filter_complex_and_full_decode(tmp_path):
    ffmpeg = ffmpeg_bin()
    source = tmp_path / "source.mp4"
    narration = tmp_path / "narration.wav"
    music = tmp_path / "music.wav"
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=duration=2:size=320x180:rate=24",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-shortest",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(source),
        ],
        check=True,
    )
    for path, frequency, duration in (
        (narration, 700, 0.7),
        (music, 220, 2),
    ):
        subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={frequency}:duration={duration}",
                str(path),
            ],
            check=True,
        )
    timeline = _timeline(tmp_path)
    timeline.source_video = str(source)
    timeline.duration = 2
    timeline.items = [timeline.items[0]]
    timeline.items[0].end = 2
    timeline.items[0].video.source_start = 0
    timeline.items[0].video.source_end = 2
    timeline.items[0].subtitle.end = 0.7
    timeline.items[0].audio.narration.asset = str(narration)
    timeline.items[0].audio.bgm.asset = str(music)
    timeline.items[0].protected_dialogue = [
        DialogueCue(
            start_time=0.2,
            end_time=0.4,
            text="verified key window",
            verification_status=VerificationStatus.VERIFIED,
        )
    ]

    output = CinematicRenderer().render(timeline, tmp_path / "final.mp4")

    assert output.stat().st_size > 0
    assert output.with_suffix(".render.json").is_file()
    assert (tmp_path / "post_render_quality.json").is_file()
