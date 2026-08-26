import json

import pytest

from movie_narrator.cinematic.state import RunStateStore


def test_run_state_records_hashes_and_validates_resume(tmp_path):
    source = tmp_path / "movie.mp4"
    source.write_bytes(b"movie")
    artifact = tmp_path / "scene_database.json"
    artifact.write_text("{}", encoding="utf-8")
    state_path = tmp_path / "cinematic_run_state.json"
    request = {"style": "克制", "target_duration": 60}

    store = RunStateStore.open(
        state_path,
        source_video=source,
        request=request,
        resume=False,
    )
    store.record("scene_database", artifact, "ANALYZE")
    store.complete()

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["status"] == "PREVIEW_READY"
    assert len(payload["artifacts"]["scene_database"]["sha256"]) == 64

    resumed = RunStateStore.open(
        state_path,
        source_video=source,
        request=request,
        resume=True,
    )
    assert resumed.reusable("scene_database", artifact) is True


def test_run_state_refuses_changed_source_or_options(tmp_path):
    source = tmp_path / "movie.mp4"
    source.write_bytes(b"movie")
    state_path = tmp_path / "state.json"
    RunStateStore.open(
        state_path,
        source_video=source,
        request={"style": "A"},
        resume=False,
    )

    with pytest.raises(ValueError, match="options"):
        RunStateStore.open(
            state_path,
            source_video=source,
            request={"style": "B"},
            resume=True,
        )

    source.write_bytes(b"changed")
    with pytest.raises(ValueError, match="source hash"):
        RunStateStore.open(
            state_path,
            source_video=source,
            request={"style": "A"},
            resume=True,
        )
