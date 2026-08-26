import json
from types import SimpleNamespace

import pytest

from movie_narrator.cinematic.models import SceneDatabase, SceneRecord
from movie_narrator.cinematic.script_generator import CinematicScriptGenerator


class StubCompletions:
    def __init__(self, content):
        self.content = content
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))]
        )


def _client(content):
    completions = StubCompletions(content)
    return SimpleNamespace(chat=SimpleNamespace(completions=completions)), completions


def _database():
    return SceneDatabase(
        source_video="movie.mp4",
        source_sha256="abc",
        scene_detector="stub",
        asr_backend="none",
        visual_backend="stub",
        scenes=[
            SceneRecord(
                scene_id="SCN-0001",
                start_time=0,
                end_time=5,
                location="舞台",
                action="第一次登台",
                emotion="紧张",
                visual_description="演员站在舞台中央",
            )
        ],
    )


def test_generator_returns_structured_narration_segments(tmp_path):
    content = json.dumps(
        [
            {
                "id": "NAR-0001",
                "narration": "他第一次站在所有人面前。",
                "target_scene": "第一次登台",
                "emotion": "紧张",
                "audio_priority": "narration",
            }
        ],
        ensure_ascii=False,
    )
    client, completions = _client(content)
    generator = CinematicScriptGenerator(client, "test-model")
    segments = generator.generate(_database(), style="克制", target_duration=60)

    assert segments[0].target_scene == "第一次登台"
    assert completions.last_kwargs["temperature"] == 0.4
    target = generator.write_segments(segments, tmp_path / "narration_segments.json")
    assert target.exists()


def test_generator_rejects_free_form_text():
    client, _ = _client("这是一整段没有结构的旁白。")
    with pytest.raises(json.JSONDecodeError):
        CinematicScriptGenerator(client, "test-model").generate(
            _database(), style="克制", target_duration=60
        )


def test_generator_rejects_duplicate_ids():
    item = {
        "id": "NAR-0001",
        "narration": "文本",
        "target_scene": "舞台",
        "emotion": "紧张",
        "audio_priority": "narration",
    }
    client, _ = _client(json.dumps([item, item], ensure_ascii=False))
    with pytest.raises(ValueError, match="unique"):
        CinematicScriptGenerator(client, "test-model").generate(
            _database(), style="克制", target_duration=60
        )
