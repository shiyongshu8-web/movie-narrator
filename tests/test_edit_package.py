# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests for the opt-in editable stem/timeline delivery package."""

import csv
import json
import math
import struct
from pathlib import Path

from pydub import AudioSegment

from movie_narrator.models import Assets, Context, MatchedClip, TimedSegment
from movie_narrator.pipeline.edit_package import export_edit_package
from movie_narrator.pipeline.export_clips import export_clips
from movie_narrator.workflow.load import load_job_config


def _tone(path: Path, duration_ms: int, frequency: int) -> Path:
    sample_rate = 8000
    samples = int(sample_rate * duration_ms / 1000)
    data = bytearray()
    for index in range(samples):
        value = int(8000 * math.sin(2 * math.pi * frequency * index / sample_rate))
        data.extend(struct.pack("<h", value))
    AudioSegment(
        data=bytes(data),
        sample_width=2,
        frame_rate=sample_rate,
        channels=1,
    ).export(path, format="wav")
    return path


def _context(tmp_path: Path, *, original_audio: Path | None = None) -> Context:
    narration = _tone(tmp_path / "narration.wav", 1200, 440)
    master = _tone(tmp_path / "master_source.wav", 1200, 330)
    bgm = _tone(tmp_path / "bgm.wav", 400, 880)
    ctx = Context(
        movie_name="测试电影",
        output_dir=str(tmp_path),
        duration=1,
        audio_path=str(narration),
        final_audio_path=str(master),
        assets=Assets(bgm=str(bgm)),
        timed_segments=[
            TimedSegment(text="第一段旁白", start=0.0, end=0.6),
            TimedSegment(text="第二段旁白", start=0.6, end=1.2),
        ],
        matched_clips=[
            MatchedClip(
                segment_index=0,
                text="开场",
                narr_start=0.0,
                narr_end=0.6,
                src_start=10.0,
                src_end=12.0,
                score=0.9,
                scene_index=2,
                source="embedding_topk",
            )
        ],
    )
    ctx.metadata.update(
        {
            "edit_package_export": True,
            "video_format": "16:9",
            "bgm_gain_db": -18.0,
            "bgm_duck_db": -10.0,
        }
    )
    if original_audio:
        ctx.metadata["original_audio_path"] = str(original_audio)
        ctx.metadata["original_audio_verified"] = True
    return ctx


def test_export_edit_package_writes_stems_and_multitrack_timeline(tmp_path):
    source_audio = _tone(tmp_path / "source.wav", 900, 220)
    ctx = _context(tmp_path, original_audio=source_audio)

    export_edit_package(ctx)

    package = tmp_path / "edit_package"
    assert (package / "stems" / "narration.wav").exists()
    assert (package / "stems" / "bgm.wav").exists()
    assert (package / "stems" / "original_audio.wav").exists()
    assert (package / "master.wav").exists()
    assert (package / "timeline.csv").exists()
    assert (package / "stem_manifest.json").exists()

    timeline = json.loads((package / "master_timeline.json").read_text(encoding="utf-8"))
    assert timeline["schema"] == "movie-narrator.edit-package/v1"
    assert timeline["video_track"]["clips"][0]["source_start"] == 10.0
    roles = {track["role"] for track in timeline["audio_tracks"]}
    assert roles == {"NARRATION", "BGM", "ORIGINAL_AUDIO"}
    original = next(track for track in timeline["audio_tracks"] if track["role"] == "ORIGINAL_AUDIO")
    assert original["status"] == "VERIFIED_SOURCE_AUDIO"

    with (package / "timeline.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert {row["role"] for row in rows} >= {"VIDEO", "NARRATION", "BGM", "SUBTITLE"}
    assert ctx.metadata["edit_package_timeline"] == str(package / "master_timeline.json")


def test_export_clips_can_run_package_without_standalone_clips(tmp_path):
    ctx = _context(tmp_path)
    ctx.metadata["export_clips"] = False

    export_clips(ctx)

    assert ctx.status.export == "success"
    assert ctx.step_state.result.value == "success"
    assert (tmp_path / "edit_package" / "master_timeline.json").exists()


def test_edit_package_paths_are_resolved_relative_to_job(tmp_path):
    source_audio = _tone(tmp_path / "source.wav", 300, 220)
    config = tmp_path / "job.yaml"
    config.write_text(
        "\n".join(
            [
                "movie: 测试电影",
                "params:",
                "  edit_package_export: true",
                "  original_audio_path: ./source.wav",
                "  original_audio_verified: true",
            ]
        ),
        encoding="utf-8",
    )

    job = load_job_config(config)

    assert job.params is not None
    assert job.params.edit_package_export is True
    assert job.params.original_audio_path == str(source_audio.resolve())
    assert job.params.original_audio_verified is True
