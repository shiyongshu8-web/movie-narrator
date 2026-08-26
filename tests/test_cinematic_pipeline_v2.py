import json
from pathlib import Path

from movie_narrator.cinematic.models import (
    AnalysisStatus,
    NarrationSegment,
    SceneDatabase,
    SceneRecord,
)
from movie_narrator.cinematic.pipeline import CinematicPipeline
from movie_narrator.cinematic.script_generator import CinematicScriptGenerator


class FakeAnalyzer:
    def analyze(self, source_video, output_path):
        database = SceneDatabase(
            source_video=str(source_video),
            source_sha256="0" * 64,
            scene_detector="fake",
            asr_backend="fake",
            visual_backend="fake",
            visual_status=AnalysisStatus.COMPLETE,
            scenes=[
                SceneRecord(
                    scene_id="SCN-0001",
                    start_time=0,
                    end_time=4,
                    action="第一次登台",
                    emotion="落寞",
                    visual_description="演员独自站在舞台中央",
                    analysis_status=AnalysisStatus.COMPLETE,
                ),
                SceneRecord(
                    scene_id="SCN-0002",
                    start_time=4,
                    end_time=9,
                    action="离开剧院",
                    emotion="平静",
                    visual_description="演员走出剧院",
                    analysis_status=AnalysisStatus.COMPLETE,
                ),
            ],
        )
        Path(output_path).write_text(
            json.dumps(database.model_dump(mode="json")), encoding="utf-8"
        )
        return database


class FakeScriptGenerator:
    def generate(self, database, **kwargs):
        return [
            NarrationSegment(
                id="001",
                narration="他第一次站上舞台。",
                target_scene="第一次登台",
                emotion="落寞",
                audio_priority="narration",
            )
        ]

    write_segments = staticmethod(CinematicScriptGenerator.write_segments)


class FakeSynthesizer:
    def __init__(self):
        self.enabled_ids = None

    def synthesize(self, segments, output_dir, *, enabled_ids=None):
        self.enabled_ids = enabled_ids
        path = Path(output_dir) / "001.mp3"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        return [
            item.model_copy(update={"tts_asset": str(path), "tts_duration": 1.5})
            for item in segments
        ]


class FakeRenderer:
    def render(self, timeline, output_path, *, manifest_path=None):
        path = Path(output_path)
        path.write_bytes(b"preview")
        Path(manifest_path).write_text("{}", encoding="utf-8")
        (path.parent / "post_render_quality.json").write_text(
            '{"status":"PASS"}', encoding="utf-8"
        )
        return path


def test_pipeline_writes_required_cinematic_artifacts(tmp_path):
    source = tmp_path / "movie.mp4"
    source.touch()
    output = tmp_path / "output"
    synthesizer = FakeSynthesizer()
    pipeline = CinematicPipeline(
        analyzer=FakeAnalyzer(),
        script_generator=FakeScriptGenerator(),
        narration_synthesizer=synthesizer,
        renderer=FakeRenderer(),
    )

    result = pipeline.run(
        source_video=source,
        output_dir=output,
        style="克制",
        target_duration=60,
        top_k=2,
    )

    assert result.final_video.is_file()
    assert result.quality_status == "PASS_WITH_UNKNOWN"
    for name in (
        "scene_database.json",
        "VISUAL_EVENT_INDEX.json",
        "NARRATION_SEGMENTS.v3.json",
        "SYNC_MAP.json",
        "ALIGNMENT_REPORT.json",
        "matches.json",
        "timeline.json",
        "audio_mix.json",
        "quality_report.json",
        "preview_unverified.mp4",
        "post_render_quality.json",
        "cinematic_run_state.json",
    ):
        assert (output / name).is_file(), name
    timeline = json.loads((output / "timeline.json").read_text(encoding="utf-8"))
    assert timeline["items"][0]["video"]["source_start"] == 0
    assert timeline["items"][0]["audio"]["original"]["enabled"] is True
    assert synthesizer.enabled_ids == {"001"}
    state = json.loads((output / "cinematic_run_state.json").read_text(encoding="utf-8"))
    assert state["status"] == "PREVIEW_READY"
    assert state["artifacts"]["preview"]["sha256"]


def test_pipeline_resume_reuses_hashed_analysis_script_and_matches(tmp_path):
    source = tmp_path / "movie.mp4"
    source.touch()
    output = tmp_path / "output"
    first = CinematicPipeline(
        analyzer=FakeAnalyzer(),
        script_generator=FakeScriptGenerator(),
        narration_synthesizer=FakeSynthesizer(),
        renderer=FakeRenderer(),
    )
    first.run(
        source_video=source,
        output_dir=output,
        style="克制",
        target_duration=60,
    )

    class FailAnalyzer:
        def analyze(self, *_args, **_kwargs):
            raise AssertionError("resume must reuse scene database")

    class FailGenerator(FakeScriptGenerator):
        def generate(self, *_args, **_kwargs):
            raise AssertionError("resume must reuse narration segments")

    resumed = CinematicPipeline(
        analyzer=FailAnalyzer(),
        script_generator=FailGenerator(),
        narration_synthesizer=FakeSynthesizer(),
        renderer=FakeRenderer(),
    ).run(
        source_video=source,
        output_dir=output,
        style="克制",
        target_duration=60,
        resume=True,
    )

    assert resumed.final_video.is_file()


def test_duration_fit_rejects_narration_longer_than_all_candidates():
    database = SceneDatabase(
        source_video="movie.mp4",
        source_sha256="0" * 64,
        scene_detector="fake",
        asr_backend="fake",
        visual_backend="fake",
        scenes=[SceneRecord(scene_id="S1", start_time=0, end_time=1)],
    )
    narration = NarrationSegment(
        id="001",
        narration="过长旁白",
        target_scene="镜头",
        tts_duration=2,
    )
    from movie_narrator.scene_memory import SceneMemory

    match = SceneMemory(database).retrieve(narration)
    try:
        CinematicPipeline._fit_scene_durations([match], [narration], database)
    except ValueError as exc:
        assert "no retrieved scene is long enough" in str(exc)
    else:
        raise AssertionError("expected duration fitting to reject the narration")


def test_duration_fit_never_replaces_a_locked_scene():
    database = SceneDatabase(
        source_video="movie.mp4",
        source_sha256="0" * 64,
        scene_detector="fake",
        asr_backend="fake",
        visual_backend="fake",
        scenes=[SceneRecord(scene_id="S1", start_time=0, end_time=1)],
    )
    narration = NarrationSegment(
        id="001",
        narration="过长旁白",
        target_scene="镜头",
        tts_duration=2,
    )
    from movie_narrator.cinematic.models import SceneCandidate, SceneMatch

    match = SceneMatch(
        narration_segment_id="001",
        candidates=[SceneCandidate(scene_id="S1", text_score=1, similarity_score=1)],
        selected_scene_id="S1",
        selection_status="LOCKED",
    )
    try:
        CinematicPipeline._fit_scene_durations([match], [narration], database)
    except ValueError as exc:
        assert "locked scene" in str(exc)
    else:
        raise AssertionError("locked scenes must fail instead of being silently replaced")
