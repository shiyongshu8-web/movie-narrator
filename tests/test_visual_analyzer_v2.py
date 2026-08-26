import json
from types import SimpleNamespace

from movie_narrator.cinematic.models import SceneRecord
from movie_narrator.movie_analyzer.visual import OpenAICompatibleVisualAnalyzer


def test_visual_analyzer_sends_early_middle_and_late_frames(monkeypatch):
    captured = {}

    class Completions:
        def create(self, **kwargs):
            captured.update(kwargs)
            payload = {
                "characters": [],
                "location": "走廊",
                "action": "人物走过走廊",
                "emotion": "紧张",
                "visual_description": "人物从入口走向门边",
                "importance_score": 0.6,
            }
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    analyzer = OpenAICompatibleVisualAnalyzer(client, "vision-model")
    timestamps = []

    def fake_extract(_media_path, timestamp):
        timestamps.append(timestamp)
        return f"frame-{timestamp}".encode()

    monkeypatch.setattr(analyzer, "_extract_frame", fake_extract)
    result = analyzer.analyze(
        "movie.mp4", SceneRecord(scene_id="S1", start_time=10, end_time=20)
    )

    assert timestamps == [12.0, 15.0, 18.0]
    content = captured["messages"][1]["content"]
    assert sum(item["type"] == "image_url" for item in content) == 3
    assert result.action == "人物走过走廊"
