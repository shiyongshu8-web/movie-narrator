import json

from movie_narrator.cinematic.models import (
    AnalysisStatus,
    DialogueCue,
    VisualAnalysis,
)
from movie_narrator.movie_analyzer import MovieAnalyzer


class StubDetector:
    name = "stub-detector"

    def detect(self, media_path):
        return [(0.0, 5.0), (5.0, 10.0)]


class StubASR:
    name = "stub-asr"

    def transcribe(self, media_path):
        return [
            DialogueCue(start_time=1.0, end_time=2.0, text="第一句"),
            DialogueCue(start_time=4.5, end_time=6.5, text="跨镜头对白"),
        ]


class StubVisual:
    name = "stub-vision"

    def analyze(self, media_path, scene):
        return VisualAnalysis(
            characters=["杰克"],
            location="舞台",
            action=f"镜头 {scene.scene_id}",
            emotion="紧张",
            visual_description="杰克站在舞台中央",
            importance_score=0.8,
            status=AnalysisStatus.PARTIAL,
        )


def test_analyzer_builds_scene_database_and_assigns_dialogue_once(tmp_path):
    movie = tmp_path / "movie.mp4"
    movie.write_bytes(b"fake-media-for-unit-test")
    output = tmp_path / "scene_database.json"
    analyzer = MovieAnalyzer(StubDetector(), StubASR(), StubVisual())

    database = analyzer.analyze(movie, output)

    assert output.exists()
    assert [scene.scene_id for scene in database.scenes] == ["SCN-0001", "SCN-0002"]
    assert sum(len(scene.dialogue) for scene in database.scenes) == 2
    assert database.scenes[1].dialogue[0].text == "跨镜头对白"
    assert database.scenes[0].visual_description == "杰克站在舞台中央"
    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted["schema_version"] == "2.0"
    assert persisted["asr_status"] == "UNVERIFIED"


def test_analyzer_keeps_unknowns_when_optional_backends_fail(tmp_path):
    class FailingASR:
        name = "broken-asr"

        def transcribe(self, media_path):
            raise RuntimeError("offline")

    movie = tmp_path / "movie.mp4"
    movie.write_bytes(b"fake")
    database = MovieAnalyzer(StubDetector(), FailingASR()).analyze(
        movie, tmp_path / "scene_database.json"
    )
    assert database.asr_status.value == "UNKNOWN"
    assert database.scenes[0].visual_description == "UNKNOWN"
