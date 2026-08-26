from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from movie_narrator.cli import _configure_cli_stream_errors, app


def test_create_defaults_to_classic_mode_in_help():
    result = CliRunner().invoke(app, ["create", "--help"])

    assert result.exit_code == 0
    assert "--mode" in result.stdout
    assert "classic" in result.stdout


def test_root_help_exposes_cinematic_lock_command():
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "cinematic-lock" in result.stdout


def test_create_cinematic_routes_to_v2_runtime(tmp_path, monkeypatch):
    source = tmp_path / "movie.mp4"
    source.touch()
    output = tmp_path / "cinematic"
    locked = tmp_path / "matches.locked.json"
    locked.write_text("{}", encoding="utf-8")
    captured = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            quality_status="PASS_WITH_UNKNOWN",
            scene_database=output / "scene_database.json",
            matches=output / "matches.json",
            timeline=output / "timeline.json",
            audio_mix=output / "audio_mix.json",
            quality_report=output / "quality_report.json",
            final_video=output / "preview_unverified.mp4",
        )

    monkeypatch.setattr(
        "movie_narrator.cinematic.cli_runtime.run_cinematic_create", fake_run
    )
    result = CliRunner().invoke(
        app,
        [
            "create",
            "--mode",
            "cinematic",
            "--video",
            str(source),
            "--output-dir",
            str(output),
            "--no-bgm",
            "--cinematic-asr",
            "none",
            "--no-cinematic-visual-analysis",
            "--cinematic-top-k",
            "7",
            "--cinematic-resume",
            "--cinematic-locked-matches",
            str(locked),
            "--cinematic-visual-embedding-model",
            "clip-test",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert captured["source_video"] == str(source.resolve())
    assert captured["output_dir"] == output
    assert captured["bgm_asset"] is None
    assert captured["asr_backend"] == "none"
    assert captured["visual_analysis"] is False
    assert captured["top_k"] == 7
    assert captured["resume"] is True
    assert captured["locked_matches_path"] == str(locked)
    assert captured["visual_embedding_model"] == "clip-test"
    assert "PASS_WITH_UNKNOWN" in result.stdout
    assert str(output / "preview_unverified.mp4") in result.stdout


def test_cinematic_mode_requires_source_video():
    result = CliRunner().invoke(app, ["create", "--mode", "cinematic"])

    assert result.exit_code != 0
    assert "requires --video" in result.stderr


def test_cinematic_mode_rejects_classic_only_options_instead_of_ignoring(tmp_path):
    source = tmp_path / "movie.mp4"
    source.touch()
    result = CliRunner().invoke(
        app,
        [
            "create",
            "--mode",
            "cinematic",
            "--video",
            str(source),
            "--subtitle-lang",
            "en",
        ],
        env={"COLUMNS": "200"},
    )

    assert result.exit_code != 0
    assert "does not support these options yet" in result.stderr
    assert "--subtitle-lang" in result.stderr


def test_cli_configures_safe_stream_error_handling(monkeypatch):
    class Stream:
        errors = None

        def reconfigure(self, *, errors):
            self.errors = errors

    stdout = Stream()
    stderr = Stream()
    monkeypatch.setattr("movie_narrator.cli.sys.stdout", stdout)
    monkeypatch.setattr("movie_narrator.cli.sys.stderr", stderr)

    _configure_cli_stream_errors()

    assert stdout.errors == "replace"
    assert stderr.errors == "replace"
