# SPDX-License-Identifier: AGPL-3.0-or-later

"""Build a rich, provenance-aware scene database from a source movie."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Protocol

from ..cinematic.models import (
    AnalysisStatus,
    DialogueCue,
    SceneDatabase,
    SceneRecord,
    VerificationStatus,
)
from ..utils.deliverable_qa import probe_media
from ..utils.ffmpeg_bin import ffmpeg_bin
from .asr import ASRBackend, NullASRBackend
from .visual import NullVisualAnalyzer, VisualAnalyzer


class SceneDetector(Protocol):
    name: str

    def detect(self, media_path: str) -> list[tuple[float, float]]: ...


class PySceneDetector:
    name = "PySceneDetect.ContentDetector"

    def __init__(self, threshold: float = 27.0, frame_skip: int = 10) -> None:
        self.threshold = threshold
        self.frame_skip = frame_skip

    def detect(self, media_path: str) -> list[tuple[float, float]]:
        from scenedetect import SceneManager, open_video
        from scenedetect.detectors import ContentDetector

        video = open_video(media_path)
        manager = SceneManager()
        manager.add_detector(ContentDetector(threshold=self.threshold))
        manager.detect_scenes(video, show_progress=False, frame_skip=self.frame_skip)
        boundaries = [
            (start.get_seconds(), end.get_seconds()) for start, end in manager.get_scene_list()
        ]
        if boundaries:
            return boundaries
        duration = float(probe_media(media_path).get("duration", 0.0))
        if duration <= 0:
            raise RuntimeError("scene detection returned no scenes and duration is unavailable")
        return [(0.0, duration)]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assign_dialogue(
    boundaries: list[tuple[float, float]], cues: list[DialogueCue]
) -> list[list[DialogueCue]]:
    assigned: list[list[DialogueCue]] = [[] for _ in boundaries]
    for cue in cues:
        overlaps = [
            max(0.0, min(end, cue.end_time) - max(start, cue.start_time))
            for start, end in boundaries
        ]
        if overlaps and max(overlaps) > 0:
            assigned[overlaps.index(max(overlaps))].append(cue)
    return assigned


class MovieAnalyzer:
    def __init__(
        self,
        scene_detector: SceneDetector | None = None,
        asr_backend: ASRBackend | None = None,
        visual_analyzer: VisualAnalyzer | None = None,
        extract_thumbnails: bool = True,
    ) -> None:
        self.scene_detector = scene_detector or PySceneDetector()
        self.asr_backend = asr_backend or NullASRBackend()
        self.visual_analyzer = visual_analyzer or NullVisualAnalyzer()
        self.extract_thumbnails = extract_thumbnails

    def analyze(self, media_path: str | Path, output_path: str | Path) -> SceneDatabase:
        source = Path(media_path).resolve()
        if not source.is_file():
            raise FileNotFoundError(f"source movie not found: {source}")
        boundaries = self.scene_detector.detect(str(source))
        if not boundaries:
            raise RuntimeError("scene detector returned an empty scene list")

        asr_error: str | None = None
        try:
            dialogue = self.asr_backend.transcribe(str(source))
        except Exception as exc:
            dialogue = []
            asr_error = f"{type(exc).__name__}: {exc}"
        assigned_dialogue = _assign_dialogue(boundaries, dialogue)

        scenes: list[SceneRecord] = []
        visual_statuses: list[AnalysisStatus] = []
        thumbnail_dir = Path(output_path).parent / "scene_thumbnails"
        for index, ((start, end), cues) in enumerate(zip(boundaries, assigned_dialogue)):
            base = SceneRecord(
                scene_id=f"SCN-{index + 1:04d}",
                start_time=start,
                end_time=end,
                dialogue=cues,
            )
            try:
                visual = self.visual_analyzer.analyze(str(source), base)
            except Exception:
                visual = NullVisualAnalyzer().analyze(str(source), base)
            visual_statuses.append(visual.status)
            thumbnail_path = self._extract_thumbnail(
                source,
                base,
                thumbnail_dir,
            ) if self.extract_thumbnails else None
            scenes.append(
                base.model_copy(
                    update={
                        "characters": visual.characters,
                        "location": visual.location,
                        "action": visual.action,
                        "emotion": visual.emotion,
                        "visual_description": visual.visual_description,
                        "importance_score": visual.importance_score,
                        "analysis_status": visual.status,
                        "thumbnail_path": str(thumbnail_path) if thumbnail_path else None,
                    }
                )
            )

        resolved_asr = getattr(self.asr_backend, "resolved_backend", None)
        asr_name = resolved_asr or getattr(self.asr_backend, "name", "unknown")
        asr_status = (
            VerificationStatus.UNVERIFIED
            if dialogue
            else VerificationStatus.UNKNOWN
        )
        visual_status = (
            AnalysisStatus.COMPLETE
            if visual_statuses
            and all(value is AnalysisStatus.COMPLETE for value in visual_statuses)
            else AnalysisStatus.PARTIAL
            if any(value is not AnalysisStatus.UNVERIFIED for value in visual_statuses)
            else AnalysisStatus.UNVERIFIED
        )
        database = SceneDatabase(
            source_video=str(source),
            source_sha256=_sha256(source),
            scene_detector=self.scene_detector.name,
            asr_backend=asr_name if not asr_error else f"{asr_name}:FAILED",
            asr_status=asr_status,
            visual_backend=getattr(self.visual_analyzer, "name", "unknown"),
            visual_status=visual_status,
            scenes=scenes,
        )
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(database.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return database

    @staticmethod
    def _extract_thumbnail(
        source: Path,
        scene: SceneRecord,
        thumbnail_dir: Path,
    ) -> Path | None:
        thumbnail_dir.mkdir(parents=True, exist_ok=True)
        target = thumbnail_dir / f"{scene.scene_id}.jpg"
        timestamp = (scene.start_time + scene.end_time) / 2.0
        try:
            result = subprocess.run(
                [
                    ffmpeg_bin(),
                    "-y",
                    "-loglevel",
                    "error",
                    "-ss",
                    f"{timestamp:.3f}",
                    "-i",
                    str(source),
                    "-frames:v",
                    "1",
                    "-q:v",
                    "3",
                    str(target),
                ],
                capture_output=True,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if result.returncode != 0 or not target.is_file() or target.stat().st_size <= 0:
            return None
        return target.resolve()
