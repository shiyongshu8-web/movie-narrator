# SPDX-License-Identifier: AGPL-3.0-or-later

"""End-to-end cinematic V2 orchestration with versioned artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

from ..audio_director import AudioDirector
from ..movie_analyzer import MovieAnalyzer
from ..scene_memory import SceneMemory
from ..scene_memory.embeddings import VisualEmbedder
from ..timeline import CinematicRenderer, TimelineBuilder, TimelineValidator
from ..alignment import build_sync_map, write_sync_map
from ..alignment.qc import evaluate_alignment
from ..narration import load_narration_segments, write_narration_segments
from ..visual_events import build_visual_event_index, load_visual_event_index
from .models import (
    MatchesDocument,
    NarrationSegment,
    QualityReport,
    SceneDatabase,
    SceneMatch,
)
from .script_generator import CinematicScriptGenerator
from .state import RunStateStore


class NarrationSynthesizer(Protocol):
    def synthesize(
        self,
        segments: Sequence[NarrationSegment],
        output_dir: str | Path,
        *,
        enabled_ids: set[str] | None = None,
    ) -> list[NarrationSegment]: ...


@dataclass(frozen=True)
class CinematicResult:
    output_dir: Path
    final_video: Path
    scene_database: Path
    matches: Path
    timeline: Path
    audio_mix: Path
    quality_report: Path
    quality_status: str
    run_state: Path
    post_render_quality: Path | None = None
    visual_event_index: Path | None = None
    bound_narration_segments: Path | None = None
    sync_map: Path | None = None
    alignment_report: Path | None = None


class CinematicPipeline:
    def __init__(
        self,
        *,
        analyzer: MovieAnalyzer,
        script_generator: CinematicScriptGenerator,
        narration_synthesizer: NarrationSynthesizer,
        audio_director: AudioDirector | None = None,
        timeline_builder: TimelineBuilder | None = None,
        timeline_validator: TimelineValidator | None = None,
        renderer: CinematicRenderer | None = None,
        visual_embedder: VisualEmbedder | None = None,
    ) -> None:
        self.analyzer = analyzer
        self.script_generator = script_generator
        self.narration_synthesizer = narration_synthesizer
        self.audio_director = audio_director or AudioDirector()
        self.timeline_builder = timeline_builder or TimelineBuilder()
        self.timeline_validator = timeline_validator or TimelineValidator()
        self.renderer = renderer or CinematicRenderer()
        self.visual_embedder = visual_embedder

    def run(
        self,
        *,
        source_video: str | Path,
        output_dir: str | Path,
        style: str,
        target_duration: int,
        bgm_asset: str | None = None,
        top_k: int = 5,
        story_context: str = "",
        resume: bool = False,
        locked_matches_path: str | Path | None = None,
    ) -> CinematicResult:
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        locked_matches = Path(locked_matches_path).resolve() if locked_matches_path else None
        if locked_matches is not None and not locked_matches.is_file():
            raise FileNotFoundError(f"locked matches not found: {locked_matches}")
        request = {
            "style": style,
            "target_duration": target_duration,
            "bgm_asset": str(Path(bgm_asset).resolve()) if bgm_asset else None,
            "top_k": top_k,
            "story_context": story_context,
            "locked_matches_path": str(locked_matches) if locked_matches else None,
            "locked_matches_sha256": (
                RunStateStore.sha256(locked_matches) if locked_matches else None
            ),
            "visual_embedder": getattr(self.visual_embedder, "name", "none"),
            "visual_embedding_model": getattr(
                self.visual_embedder, "model_name", None
            ),
        }
        state = RunStateStore.open(
            output / "cinematic_run_state.json",
            source_video=source_video,
            request=request,
            resume=resume,
        )
        try:
            result = self._run_stages(
                source_video=source_video,
                output=output,
                style=style,
                target_duration=target_duration,
                bgm_asset=bgm_asset,
                top_k=top_k,
                story_context=story_context,
                resume=resume,
                state=state,
                locked_matches_path=locked_matches,
            )
        except Exception as exc:
            state.fail(exc)
            raise
        state.complete()
        return result

    def _run_stages(
        self,
        *,
        source_video: str | Path,
        output: Path,
        style: str,
        target_duration: int,
        bgm_asset: str | None,
        top_k: int,
        story_context: str,
        resume: bool,
        state: RunStateStore,
        locked_matches_path: Path | None,
    ) -> CinematicResult:
        scene_path = output / "scene_database.json"
        if resume and state.reusable("scene_database", scene_path):
            database = SceneDatabase.model_validate_json(
                scene_path.read_text(encoding="utf-8")
            )
        else:
            database = self.analyzer.analyze(source_video, scene_path)
            state.record("scene_database", scene_path, "ANALYZE")

        # Keep the visual evidence layer between source analysis and script
        # generation.  It is derived from the existing scene database and is
        # never a free-form story reconstruction.
        event_index_path = output / "VISUAL_EVENT_INDEX.json"
        if resume and event_index_path.is_file():
            event_index = load_visual_event_index(event_index_path)
        else:
            event_index = build_visual_event_index(database, event_index_path)
        state.record("visual_event_index", event_index_path, "EVENT_INDEX")

        narration_path = output / "narration_segments.json"
        if resume and state.reusable("narration_segments", narration_path):
            narration_payload = json.loads(narration_path.read_text(encoding="utf-8"))
            narrations = [
                NarrationSegment.model_validate(item)
                for item in narration_payload.get("segments", [])
            ]
            if not narrations:
                raise ValueError("resume narration_segments.json contains no segments")
        else:
            narrations = self.script_generator.generate(
                database,
                style=style,
                target_duration=target_duration,
                story_context=story_context,
            )
        memory = SceneMemory(database, visual_embedder=self.visual_embedder)
        matches_path = output / "matches.json"
        if locked_matches_path is not None:
            match_document = MatchesDocument.model_validate_json(
                locked_matches_path.read_text(encoding="utf-8")
            )
            matches = match_document.matches
            narration_ids = {item.id for item in narrations}
            match_ids = {item.narration_segment_id for item in matches}
            if narration_ids != match_ids:
                raise ValueError("locked matches do not cover the current narration segments")
        elif resume and state.reusable("matches", matches_path):
            match_document = MatchesDocument.model_validate_json(
                matches_path.read_text(encoding="utf-8")
            )
            matches = match_document.matches
        else:
            matches = memory.match_all(narrations, top_k=top_k)

        # Editorial audio intent must be known before spending time/money on TTS.
        # This preliminary pass uses the first retrieval result; the definitive
        # pass below runs again after duration-aware scene fitting.
        preliminary_decisions = self.audio_director.direct(narrations, matches, database)
        narration_enabled_ids = {
            item.narration_segment_id
            for item in preliminary_decisions
            if item.narration_enabled
        }
        narrations = self.narration_synthesizer.synthesize(
            narrations,
            output / "narration_segments",
            enabled_ids=narration_enabled_ids,
        )
        self.script_generator.write_segments(narrations, narration_path)
        state.record("narration_segments", narration_path, "TTS")

        # Preserve the legacy v2 narration file for compatibility while also
        # writing the event-bound contract used by semantic alignment.
        bound_narration = load_narration_segments(
            narration_path,
            visual_events=event_index,
        )
        bound_narration_path = write_narration_segments(
            bound_narration,
            # Windows paths are case-insensitive; keep the stable legacy
            # narration_segments.json untouched for resume compatibility.
            output / "NARRATION_SEGMENTS.v3.json",
        )
        state.record("bound_narration_segments", bound_narration_path, "NARRATION_BIND")
        matches = self._fit_scene_durations(matches, narrations, database)
        matches_path = memory.write_matches(matches, matches_path)
        state.record("matches", matches_path, "MATCH")

        decisions = self.audio_director.direct(narrations, matches, database)
        audio_mix_path = self.audio_director.write(decisions, output / "audio_mix.json")
        state.record("audio_mix", audio_mix_path, "AUDIO_DIRECTOR")
        timeline = self.timeline_builder.build(
            source_video=str(Path(source_video).resolve()),
            narrations=narrations,
            matches=matches,
            decisions=decisions,
            scene_database=database,
            bgm_asset=bgm_asset,
        )
        timeline_path = self.timeline_builder.write(timeline, output / "timeline.json")
        state.record("timeline", timeline_path, "TIMELINE")
        sync_document = build_sync_map(
            bound_narration,
            event_index,
            timeline=timeline.model_dump(mode="json"),
        )
        sync_map_path = write_sync_map(sync_document, output / "SYNC_MAP.json")
        state.record("sync_map", sync_map_path, "SYNC_MAP")
        alignment_report = evaluate_alignment(sync_document)
        alignment_report_path = output / "ALIGNMENT_REPORT.json"
        alignment_report_path.write_text(
            json.dumps(alignment_report.model_dump(mode="json"), ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        state.record("alignment_report", alignment_report_path, "SEMANTIC_ALIGNMENT_QC")
        report = self.timeline_validator.validate_or_raise(timeline)
        report_path = self.timeline_validator.write(report, output / "quality_report.json")
        state.record("quality_report", report_path, "TIMELINE_QA")
        final_path = self.renderer.render(
            timeline,
            output / "preview_unverified.mp4",
            manifest_path=output / "render_manifest.json",
        )
        state.record("preview", final_path, "RENDER")
        state.record("render_manifest", output / "render_manifest.json", "POST_RENDER_QA")
        post_render_quality = output / "post_render_quality.json"
        if post_render_quality.is_file():
            state.record(
                "post_render_quality", post_render_quality, "POST_RENDER_QA"
            )
        else:
            post_render_quality = None
        return CinematicResult(
            output_dir=output,
            final_video=final_path,
            scene_database=scene_path,
            matches=matches_path,
            timeline=timeline_path,
            audio_mix=audio_mix_path,
            quality_report=report_path,
            quality_status=report.status,
            run_state=state.path,
            post_render_quality=post_render_quality,
            visual_event_index=event_index_path,
            bound_narration_segments=bound_narration_path,
            sync_map=sync_map_path,
            alignment_report=alignment_report_path,
        )

    @staticmethod
    def _fit_scene_durations(
        matches: Sequence[SceneMatch],
        narrations: Sequence[NarrationSegment],
        database: SceneDatabase,
    ) -> list[SceneMatch]:
        narration_by_id = {item.id: item for item in narrations}
        scene_by_id = {item.scene_id: item for item in database.scenes}
        fitted: list[SceneMatch] = []
        for match in matches:
            narration = narration_by_id[match.narration_segment_id]
            if narration.audio_priority == "dialogue" or narration.tts_duration is None:
                fitted.append(match)
                continue
            if match.selection_status == "LOCKED":
                selected_scene = scene_by_id[match.selected_scene_id]
                selected_duration = selected_scene.end_time - selected_scene.start_time
                if selected_duration + 1e-6 < narration.tts_duration:
                    raise ValueError(
                        f"locked scene {selected_scene.scene_id} is too short for "
                        f"narration {narration.id}"
                    )
                fitted.append(match)
                continue
            compatible = [
                candidate
                for candidate in match.candidates
                if scene_by_id[candidate.scene_id].end_time
                - scene_by_id[candidate.scene_id].start_time
                >= narration.tts_duration
            ]
            if not compatible:
                raise ValueError(
                    f"no retrieved scene is long enough for narration {narration.id}; "
                    "shorten the segment or increase top_k"
                )
            fitted.append(match.model_copy(update={"selected_scene_id": compatible[0].scene_id}))
        return fitted
