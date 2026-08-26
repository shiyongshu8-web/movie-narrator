# SPDX-License-Identifier: AGPL-3.0-or-later

"""Render a cinematic master timeline with an inspectable FFmpeg graph."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path

from ..cinematic.models import TimelineDocument
from ..utils.ffmpeg_bin import ffmpeg_bin


@dataclass(frozen=True)
class RenderPlan:
    command: list[str]
    filter_complex: str
    subtitle_path: Path
    output_path: Path


class CinematicRenderer:
    """Translate the master timeline into five FFmpeg tracks."""

    def __init__(self, *, enable_ducking: bool = True) -> None:
        self.enable_ducking = enable_ducking

    def build_plan(
        self,
        timeline: TimelineDocument,
        output_path: str | Path,
        *,
        subtitle_path: str | Path | None = None,
    ) -> RenderPlan:
        source = Path(timeline.source_video)
        if not source.is_file():
            raise FileNotFoundError(f"source video not found: {source}")
        source_has_audio = self._source_has_audio(source)
        needs_source_audio = any(
            item.audio.original.enabled and item.audio.original.volume > 0
            for item in timeline.items
        )
        if needs_source_audio and not source_has_audio:
            raise ValueError(
                "timeline requests original audio but the source has no audio stream"
            )
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        subtitles = Path(subtitle_path or output.with_suffix(".cinematic.srt"))
        self.write_srt(timeline, subtitles)

        command = [ffmpeg_bin(), "-hide_banner", "-y", "-i", str(source)]
        narration_inputs: dict[str, int] = {}
        for item in timeline.items:
            track = item.audio.narration
            if not track.enabled:
                continue
            if not track.asset:
                raise ValueError(f"missing narration asset for {item.timeline_id}")
            asset = Path(track.asset)
            if not asset.is_file():
                raise FileNotFoundError(f"narration asset not found: {asset}")
            narration_inputs[item.timeline_id] = len(narration_inputs) + 1
            command.extend(["-i", str(asset)])

        bgm_assets = {
            item.audio.bgm.asset
            for item in timeline.items
            if item.audio.bgm.enabled and item.audio.bgm.asset
        }
        if len(bgm_assets) > 1:
            raise ValueError("one cinematic timeline may reference only one BGM asset")
        bgm_input: int | None = None
        if bgm_assets:
            bgm_path = Path(next(iter(bgm_assets)))
            if not bgm_path.is_file():
                raise FileNotFoundError(f"BGM asset not found: {bgm_path}")
            bgm_input = len(narration_inputs) + 1
            command.extend(["-stream_loop", "-1", "-i", str(bgm_path)])

        graph = self._build_filter_graph(
            timeline,
            narration_inputs=narration_inputs,
            bgm_input=bgm_input,
            subtitle_path=subtitles,
            source_has_audio=source_has_audio,
        )
        command.extend(
            [
                "-filter_complex",
                graph,
                "-map",
                "[video_out]",
                "-map",
                "[audio_out]",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "18",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-movflags",
                "+faststart",
                "-t",
                self._number(timeline.duration),
                str(output),
            ]
        )
        return RenderPlan(command, graph, subtitles, output)

    def render(
        self,
        timeline: TimelineDocument,
        output_path: str | Path,
        *,
        manifest_path: str | Path | None = None,
    ) -> Path:
        plan = self.build_plan(timeline, output_path)
        manifest = Path(manifest_path or plan.output_path.with_suffix(".render.json"))
        manifest_data = {
            "renderer": "ffmpeg-filter-complex",
            "ducking_enabled": self.enable_ducking,
            "command": plan.command,
            "filter_complex": plan.filter_complex,
            "subtitle_path": str(plan.subtitle_path),
            "output_path": str(plan.output_path),
            "status": "RUNNING",
            "started_at": self._utc_now(),
        }
        self._write_json(manifest, manifest_data)
        try:
            subprocess.run(plan.command, check=True)
            self._full_decode(plan.output_path)
            if not plan.output_path.is_file() or plan.output_path.stat().st_size <= 0:
                raise RuntimeError("renderer did not create a non-empty output")
        except Exception as exc:
            manifest_data.update(
                {
                    "status": "FAILED",
                    "finished_at": self._utc_now(),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            self._write_json(manifest, manifest_data)
            raise

        digest = self._sha256(plan.output_path)
        finished_at = self._utc_now()
        manifest_data.update(
            {
                "status": "PASS",
                "finished_at": finished_at,
                "full_decode": True,
                "output_sha256": digest,
                "output_size_bytes": plan.output_path.stat().st_size,
            }
        )
        self._write_json(manifest, manifest_data)
        self._write_json(
            plan.output_path.with_name("post_render_quality.json"),
            {
                "schema_version": "2.0",
                "status": "PASS",
                "artifact_label": "UNVERIFIED_PREVIEW",
                "full_decode": True,
                "expected_duration": timeline.duration,
                "output_path": str(plan.output_path),
                "output_sha256": digest,
                "output_size_bytes": plan.output_path.stat().st_size,
                "checked_at": finished_at,
            },
        )
        return plan.output_path

    def _build_filter_graph(
        self,
        timeline: TimelineDocument,
        *,
        narration_inputs: dict[str, int],
        bgm_input: int | None,
        subtitle_path: Path,
        source_has_audio: bool,
    ) -> str:
        filters: list[str] = []
        video_labels: list[str] = []
        original_labels: list[str] = []
        narration_labels: list[str] = []

        for index, item in enumerate(timeline.items):
            video_label = f"video_{index}"
            original_label = f"original_{index}"
            video_labels.append(f"[{video_label}]")
            original_labels.append(f"[{original_label}]")
            filters.append(
                f"[0:v]trim=start={self._number(item.video.source_start)}:"
                f"end={self._number(item.video.source_end)},setpts=PTS-STARTPTS,"
                f"setsar=1[{video_label}]"
            )
            original_volume = item.audio.original.volume if item.audio.original.enabled else 0
            if source_has_audio:
                filters.append(
                    f"[0:a]atrim=start={self._number(item.video.source_start)}:"
                    f"end={self._number(item.video.source_end)},asetpts=PTS-STARTPTS,"
                    f"volume={self._number(original_volume)},aresample=async=1:first_pts=0"
                    f"[{original_label}]"
                )
            else:
                filters.append(
                    "anullsrc=r=48000:cl=stereo,"
                    f"atrim=duration={self._number(item.end - item.start)}"
                    f"[{original_label}]"
                )

            input_index = narration_inputs.get(item.timeline_id)
            if input_index is not None:
                narration_label = f"narration_{index}"
                narration_labels.append(f"[{narration_label}]")
                delay_ms = round(item.start * 1000)
                filters.append(
                    f"[{input_index}:a]atrim=duration={self._number(item.end - item.start)},"
                    f"asetpts=PTS-STARTPTS,volume={self._number(item.audio.narration.volume)},"
                    f"adelay={delay_ms}:all=1[{narration_label}]"
                )

        item_count = len(timeline.items)
        filters.append(
            "".join(video_labels)
            + f"concat=n={item_count}:v=1:a=0[video_master]"
        )
        filters.append(
            "".join(original_labels)
            + f"concat=n={item_count}:v=0:a=1[original_master]"
        )
        self._mix_or_silence(filters, narration_labels, "narration_master", timeline.duration)
        self._build_bgm(filters, timeline, bgm_input)

        if self.enable_ducking:
            filters.append("[narration_master]asplit=2[narration_mix][narration_key]")
            dialogue_windows = self._verified_dialogue_windows(timeline)
            original_for_mix = "[original_master]"
            if dialogue_windows:
                filters.append("[original_master]asplit=2[original_mix][dialogue_source]")
                original_for_mix = "[original_mix]"
                self._build_dialogue_key(filters, timeline.duration, dialogue_windows)
            filters.append(
                f"{original_for_mix}[narration_key]sidechaincompress="
                "threshold=0.04:ratio=8:attack=20:release=250[original_ducked]"
            )
            if dialogue_windows:
                filters.append(
                    "[narration_mix][dialogue_key]sidechaincompress="
                    "threshold=0.12:ratio=4:attack=10:release=180[narration_ducked]"
                )
                narration_output = "[narration_ducked]"
            else:
                narration_output = "[narration_mix]"
            audio_inputs = f"[original_ducked]{narration_output}[bgm_master]"
        else:
            audio_inputs = "[original_master][narration_master][bgm_master]"
        filters.append(
            f"{audio_inputs}amix=inputs=3:duration=longest:normalize=0,"
            f"atrim=duration={self._number(timeline.duration)},alimiter=limit=0.95[audio_out]"
        )
        if any(item.subtitle and item.subtitle.text.strip() for item in timeline.items):
            escaped_subtitles = self._escape_filter_path(subtitle_path)
            filters.append(
                f"[video_master]subtitles=filename='{escaped_subtitles}'[video_out]"
            )
        else:
            filters.append("[video_master]null[video_out]")
        return ";".join(filters)

    def _build_bgm(
        self,
        filters: list[str],
        timeline: TimelineDocument,
        bgm_input: int | None,
    ) -> None:
        if bgm_input is None:
            self._mix_or_silence(filters, [], "bgm_master", timeline.duration)
            return
        labels = [f"bgm_input_{index}" for index in range(len(timeline.items))]
        filters.append(
            f"[{bgm_input}:a]asplit={len(labels)}"
            + "".join(f"[{label}]" for label in labels)
        )
        mixed: list[str] = []
        for index, (label, item) in enumerate(zip(labels, timeline.items, strict=True)):
            output_label = f"bgm_{index}"
            mixed.append(f"[{output_label}]")
            volume = item.audio.bgm.volume if item.audio.bgm.enabled else 0
            delay_ms = round(item.start * 1000)
            filters.append(
                f"[{label}]atrim=start={self._number(item.start)}:"
                f"end={self._number(item.end)},"
                f"asetpts=PTS-STARTPTS,volume={self._number(volume)},"
                f"adelay={delay_ms}:all=1[{output_label}]"
            )
        self._mix_or_silence(filters, mixed, "bgm_master", timeline.duration)

    def _build_dialogue_key(
        self,
        filters: list[str],
        duration: float,
        windows: list[tuple[float, float]],
    ) -> None:
        if len(windows) == 1:
            input_labels = ["dialogue_source"]
        else:
            input_labels = [f"dialogue_input_{index}" for index in range(len(windows))]
            filters.append(
                f"[dialogue_source]asplit={len(input_labels)}"
                + "".join(f"[{label}]" for label in input_labels)
            )
        mixed: list[str] = []
        for index, (label, window) in enumerate(zip(input_labels, windows, strict=True)):
            start, end = window
            output_label = f"dialogue_window_{index}"
            mixed.append(f"[{output_label}]")
            filters.append(
                f"[{label}]atrim=start={self._number(start)}:end={self._number(end)},"
                "asetpts=PTS-STARTPTS,"
                f"adelay={round(start * 1000)}:all=1[{output_label}]"
            )
        self._mix_or_silence(filters, mixed, "dialogue_key", duration)

    @staticmethod
    def _verified_dialogue_windows(
        timeline: TimelineDocument,
    ) -> list[tuple[float, float]]:
        from ..cinematic.models import VerificationStatus

        windows: list[tuple[float, float]] = []
        for item in timeline.items:
            for cue in item.protected_dialogue:
                if cue.verification_status is not VerificationStatus.VERIFIED:
                    continue
                local_start = max(0.0, cue.start_time - item.video.source_start)
                local_end = min(
                    item.end - item.start,
                    cue.end_time - item.video.source_start,
                )
                if local_end > local_start:
                    windows.append((item.start + local_start, item.start + local_end))
        return windows

    @staticmethod
    def _mix_or_silence(
        filters: list[str], labels: list[str], output_label: str, duration: float
    ) -> None:
        if labels:
            filters.append(
                "".join(labels)
                + f"amix=inputs={len(labels)}:duration=longest:normalize=0,"
                f"apad,atrim=duration={CinematicRenderer._number(duration)}[{output_label}]"
            )
        else:
            filters.append(
                "anullsrc=r=48000:cl=stereo,"
                f"atrim=duration={CinematicRenderer._number(duration)}[{output_label}]"
            )

    @staticmethod
    def write_srt(timeline: TimelineDocument, output_path: str | Path) -> Path:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        blocks: list[str] = []
        sequence = 1
        for item in timeline.items:
            if not item.subtitle or not item.subtitle.text.strip():
                continue
            blocks.extend(
                [
                    str(sequence),
                    f"{CinematicRenderer._srt_time(item.subtitle.start)} --> "
                    f"{CinematicRenderer._srt_time(item.subtitle.end)}",
                    item.subtitle.text.strip(),
                    "",
                ]
            )
            sequence += 1
        target.write_text("\n".join(blocks), encoding="utf-8-sig")
        return target

    @staticmethod
    def _full_decode(path: Path) -> None:
        command = [
            ffmpeg_bin(),
            "-v",
            "error",
            "-i",
            str(path),
            "-f",
            "null",
            os.devnull,
        ]
        subprocess.run(command, check=True)

    @staticmethod
    def _source_has_audio(path: Path) -> bool:
        try:
            result = subprocess.run(
                [ffmpeg_bin(), "-hide_banner", "-i", str(path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return "Audio:" in (result.stderr or "")

    @staticmethod
    def _write_json(path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _escape_filter_path(path: Path) -> str:
        value = str(path.resolve()).replace("\\", "/")
        value = value.replace(":", r"\:").replace("'", r"\'")
        return value

    @staticmethod
    def _number(value: float) -> str:
        return f"{value:.6f}".rstrip("0").rstrip(".") or "0"

    @staticmethod
    def _srt_time(value: float) -> str:
        millis = max(0, round(value * 1000))
        hours, millis = divmod(millis, 3_600_000)
        minutes, millis = divmod(millis, 60_000)
        seconds, millis = divmod(millis, 1000)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"
