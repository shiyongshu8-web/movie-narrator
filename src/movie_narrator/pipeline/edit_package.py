# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Export an editable audio-stem and timeline package.

The normal renderer intentionally produces one delivery mix.  This module
keeps that behaviour intact while exporting a second, editor-facing package
when ``edit_package_export`` is enabled:

* WAV audio files with stable role names (narration, BGM, ambience, source
  audio and the final master mix when available);
* a backend-neutral ``master_timeline.json`` containing video, audio and text
  tracks; and
* a flat ``timeline.csv`` for quick inspection or spreadsheet import.

The source movie's audio is never presented as an isolated dialogue stem.  If
it is extracted from a movie file, the manifest records
``SOURCE_MIXED_AUDIO / STEM_SEPARATION_UNAVAILABLE`` as required by the
editorial audio contract.
"""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any, Optional

from pydub import AudioSegment

from ..models import Context

logger = logging.getLogger(__name__)

_SCHEMA = "movie-narrator.edit-package/v1"
_DEFAULT_SAMPLE_RATE = 48_000


def _round(value: float) -> float:
    return round(float(value), 3)


def _timeline_duration_ms(ctx: Context) -> int:
    """Resolve the actual output duration without inventing source timing."""
    for path in (ctx.final_audio_path, ctx.audio_path):
        if not path or not Path(path).is_file():
            continue
        try:
            return max(1, len(AudioSegment.from_file(path)))
        except Exception:
            logger.debug("Cannot probe audio duration for %s", path, exc_info=True)

    if ctx.timed_segments:
        return max(1, int(max(seg.end for seg in ctx.timed_segments) * 1000))
    return max(1, int(max(ctx.duration, 1) * 1000))


def _fit_to_duration(segment: AudioSegment, target_ms: int) -> AudioSegment:
    """Loop/trim an audio segment to the master duration."""
    if target_ms <= 0:
        return AudioSegment.empty()
    if len(segment) == 0:
        return AudioSegment.silent(duration=target_ms, frame_rate=_DEFAULT_SAMPLE_RATE)
    if len(segment) < target_ms:
        repeats = target_ms // len(segment) + 1
        segment = segment * repeats
    return segment[:target_ms]


def _export_wav(
    source_path: str,
    output_path: Path,
    target_ms: int,
    *,
    gain_db: float = 0.0,
) -> None:
    """Load an input media file, fit it to the timeline and export editor WAV."""
    segment = AudioSegment.from_file(source_path)
    segment = _fit_to_duration(segment, target_ms)
    if gain_db:
        segment = segment.apply_gain(float(gain_db))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    segment.export(output_path, format="wav")


def _relative(path: Path, root: Path) -> str:
    """Return a portable slash-separated path inside the package."""
    return path.relative_to(root).as_posix()


def _source_audio_record(
    ctx: Context,
    stems_dir: Path,
    package_dir: Path,
    target_ms: int,
) -> Optional[dict[str, Any]]:
    """Export supplied or source-movie audio with an explicit provenance state."""
    supplied = ctx.metadata.get("original_audio_path")
    source_path = str(supplied) if supplied else ctx.source_video_path
    if not source_path or not Path(source_path).is_file():
        return None

    if supplied:
        filename = "original_audio.wav"
        status = (
            "VERIFIED_SOURCE_AUDIO"
            if ctx.metadata.get("original_audio_verified", False)
            else "SOURCE_AUDIO_UNVERIFIED"
        )
    else:
        filename = "original_audio_source_mix.wav"
        status = "SOURCE_MIXED_AUDIO / STEM_SEPARATION_UNAVAILABLE"

    output_path = stems_dir / filename
    try:
        _export_wav(source_path, output_path, target_ms)
    except Exception as exc:  # noqa: BLE001 - an optional source stem is soft
        logger.warning("Source audio stem export failed for %s: %s", source_path, exc)
        return {
            "id": "original_audio",
            "role": "ORIGINAL_AUDIO",
            "status": f"UNAVAILABLE: {exc}",
            "source_path": source_path,
        }

    return {
        "id": "original_audio",
        "role": "ORIGINAL_AUDIO",
        "path": _relative(output_path, package_dir),
        "source_path": source_path,
        "start": 0.0,
        "end": _round(target_ms / 1000.0),
        "status": status,
        "verified": bool(ctx.metadata.get("original_audio_verified", False))
        if supplied
        else False,
        "editable": True,
    }


def _build_video_clips(ctx: Context) -> list[dict[str, Any]]:
    clips: list[dict[str, Any]] = []
    for index, clip in enumerate(ctx.matched_clips):
        timeline_duration = max(float(clip.narr_end) - float(clip.narr_start), 0.0)
        source_duration = max(float(clip.src_end) - float(clip.src_start), 0.0)
        speed = source_duration / timeline_duration if timeline_duration > 0 else 1.0
        clips.append(
            {
                "id": f"video_clip_{index:04d}",
                "segment_index": clip.segment_index,
                "scene_index": clip.scene_index,
                "timeline_start": _round(clip.narr_start),
                "timeline_end": _round(clip.narr_end),
                "source_start": _round(clip.src_start),
                "source_end": _round(clip.src_end),
                "duration": _round(timeline_duration),
                "speed": _round(speed),
                "match_score": _round(clip.score),
                "match_source": clip.source,
                "label": clip.text,
            }
        )
    return clips


def _build_text_items(ctx: Context) -> list[dict[str, Any]]:
    return [
        {
            "id": f"subtitle_{index:04d}",
            "role": "SUBTITLE",
            "text": segment.text,
            "start": _round(segment.start),
            "end": _round(segment.end),
        }
        for index, segment in enumerate(ctx.timed_segments)
    ]


def _write_csv(path: Path, timeline: dict[str, Any]) -> None:
    """Write a deliberately flat audit/export view of all timeline lanes."""
    rows: list[dict[str, Any]] = []
    video_track = timeline["video_track"]
    for clip in video_track["clips"]:
        rows.append(
            {
                "track": video_track["id"],
                "role": "VIDEO",
                "item_id": clip["id"],
                "start": clip["timeline_start"],
                "end": clip["timeline_end"],
                "source_start": clip["source_start"],
                "source_end": clip["source_end"],
                "path": timeline["source_video_path"] or "",
                "text": clip["label"],
            }
        )
    for track in timeline["audio_tracks"]:
        rows.append(
            {
                "track": track["id"],
                "role": track["role"],
                "item_id": track["id"],
                "start": track.get("start", 0.0),
                "end": track.get("end", timeline["duration_sec"]),
                "source_start": "",
                "source_end": "",
                "path": track.get("path", ""),
                "text": track.get("status", ""),
            }
        )
    for item in timeline["text_track"]:
        rows.append(
            {
                "track": "subtitles",
                "role": item["role"],
                "item_id": item["id"],
                "start": item["start"],
                "end": item["end"],
                "source_start": "",
                "source_end": "",
                "path": timeline.get("subtitle_path") or "",
                "text": item["text"],
            }
        )

    fieldnames = [
        "track",
        "role",
        "item_id",
        "start",
        "end",
        "source_start",
        "source_end",
        "path",
        "text",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def export_edit_package(ctx: Context) -> Context:
    """Export stems and a backend-neutral multi-track timeline package."""
    package_dir = Path(ctx.output_dir) / "edit_package"
    stems_dir = package_dir / "stems"
    package_dir.mkdir(parents=True, exist_ok=True)
    stems_dir.mkdir(parents=True, exist_ok=True)
    target_ms = _timeline_duration_ms(ctx)
    duration_sec = _round(target_ms / 1000.0)

    audio_tracks: list[dict[str, Any]] = []

    if ctx.audio_path and Path(ctx.audio_path).is_file():
        path = stems_dir / "narration.wav"
        try:
            _export_wav(ctx.audio_path, path, target_ms)
            audio_tracks.append(
                {
                    "id": "narration",
                    "role": "NARRATION",
                    "path": _relative(path, package_dir),
                    "source_path": ctx.audio_path,
                    "start": 0.0,
                    "end": duration_sec,
                    "gain_db": 0.0,
                    "editable": True,
                }
            )
        except Exception as exc:  # noqa: BLE001 - package export is soft
            audio_tracks.append(
                {"id": "narration", "role": "NARRATION", "status": f"UNAVAILABLE: {exc}"}
            )

    bgm_path = ctx.assets.bgm
    if bgm_path and Path(bgm_path).is_file():
        path = stems_dir / "bgm.wav"
        # Match the level used by the production mixer.  The file remains an
        # independent pre-ducking stem; the ducking contract is recorded below
        # so an NLE can replace it with its own automation if desired.
        gain_db = float(ctx.metadata.get("bgm_gain_db", -18.0))
        try:
            _export_wav(bgm_path, path, target_ms, gain_db=gain_db)
            audio_tracks.append(
                {
                    "id": "bgm",
                    "role": "BGM",
                    "path": _relative(path, package_dir),
                    "source_path": bgm_path,
                    "start": 0.0,
                    "end": duration_sec,
                    "gain_db": gain_db,
                    "ducking": {
                        "enabled": True,
                        "backend": ctx.metadata.get("bgm_ducking_backend", "envelope"),
                        "duck_db": float(ctx.metadata.get("bgm_duck_db", -10.0)),
                    },
                    "editable": True,
                }
            )
        except Exception as exc:  # noqa: BLE001 - optional BGM stem
            audio_tracks.append({"id": "bgm", "role": "BGM", "status": f"UNAVAILABLE: {exc}"})

    ambient_path = ctx.metadata.get("bgm_ambient_path")
    if ambient_path and Path(ambient_path).is_file():
        path = stems_dir / "ambience.wav"
        gain_db = float(ctx.metadata.get("bgm_ambient_gain_db", -12.0))
        try:
            _export_wav(str(ambient_path), path, target_ms, gain_db=gain_db)
            audio_tracks.append(
                {
                    "id": "ambience",
                    "role": "AMBIENCE",
                    "path": _relative(path, package_dir),
                    "source_path": str(ambient_path),
                    "start": 0.0,
                    "end": duration_sec,
                    "gain_db": gain_db,
                    "ducking": {
                        "enabled": True,
                        "duck_db": float(ctx.metadata.get("bgm_duck_db", -10.0)),
                    },
                    "editable": True,
                }
            )
        except Exception as exc:  # noqa: BLE001 - optional ambience stem
            audio_tracks.append(
                {"id": "ambience", "role": "AMBIENCE", "status": f"UNAVAILABLE: {exc}"}
            )

    source_record = _source_audio_record(ctx, stems_dir, package_dir, target_ms)
    if source_record:
        audio_tracks.append(source_record)

    master_source = ctx.final_audio_path or ctx.audio_path
    master_record: dict[str, Any] = {"role": "MASTER", "status": "UNAVAILABLE"}
    if master_source and Path(master_source).is_file():
        master_path = package_dir / "master.wav"
        try:
            _export_wav(master_source, master_path, target_ms)
            master_record = {
                "role": "MASTER",
                "path": _relative(master_path, package_dir),
                "source_path": master_source,
                "start": 0.0,
                "end": duration_sec,
                "editable": False,
            }
        except Exception as exc:  # noqa: BLE001 - master is a reference copy
            master_record["status"] = f"UNAVAILABLE: {exc}"

    timeline = {
        "schema": _SCHEMA,
        "movie": ctx.movie_name,
        "duration_sec": duration_sec,
        "frame_rate": int(ctx.metadata.get("render_fps", 24)),
        "video_format": ctx.metadata.get("video_format", "16:9"),
        "source_video_path": ctx.source_video_path,
        "video_track": {"id": "video", "role": "VIDEO", "clips": _build_video_clips(ctx)},
        "audio_tracks": audio_tracks,
        "master": master_record,
        "text_track": _build_text_items(ctx),
        "subtitle_path": ctx.render_subtitle_path or ctx.subtitle_path,
        "mix_contract": {
            "priority": ["NARRATION", "D3_DIALOGUE", "ENVIRONMENT", "BGM", "ADDITIONAL_SFX"],
            "source_audio_status": (
                source_record.get("status") if source_record else "NOT_PROVIDED"
            ),
            "final_delivery_is_mixed": True,
        },
    }

    timeline_path = package_dir / "master_timeline.json"
    timeline_path.write_text(
        json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    csv_path = package_dir / "timeline.csv"
    _write_csv(csv_path, timeline)

    manifest = {
        "schema": _SCHEMA,
        "movie": ctx.movie_name,
        "duration_sec": duration_sec,
        "package_dir": str(package_dir),
        "timeline": str(timeline_path),
        "timeline_csv": str(csv_path),
        "stems": audio_tracks,
        "master": master_record,
    }
    manifest_path = package_dir / "stem_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    ctx.metadata["edit_package_path"] = str(package_dir)
    ctx.metadata["edit_package_timeline"] = str(timeline_path)
    ctx.metadata["edit_package_stem_manifest"] = str(manifest_path)
    ctx.metadata["edit_package_stems"] = [track["id"] for track in audio_tracks]
    return ctx


__all__ = ["export_edit_package"]
