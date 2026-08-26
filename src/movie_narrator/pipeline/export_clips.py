# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Clip export step — export matched scenes as individual files."""

import subprocess
from pathlib import Path

from tqdm import tqdm

from ..models import Context, StepResult
from ..utils.ffmpeg_bin import ffmpeg_bin
from ..utils.optional_deps import probe
from ..utils.warnings import append_warning


def _export_edit_package_if_requested(ctx: Context) -> bool:
    """Export the optional editor package without changing clip semantics."""
    if not ctx.metadata.get("edit_package_export", False):
        return True
    try:
        from .edit_package import export_edit_package

        export_edit_package(ctx)
        return True
    except Exception as exc:  # noqa: BLE001 - optional delivery is soft
        append_warning(ctx, f"edit package export failed: {exc}", prefix="edit_package")
        ctx.metadata["edit_package_error"] = str(exc)
        return False


def _finish_edit_package_only(ctx: Context, reason: str) -> Context:
    """Handle an edit-package request when standalone clip export is unavailable."""
    ok = _export_edit_package_if_requested(ctx)
    if ok and ctx.metadata.get("edit_package_export", False):
        ctx.status.export = "success"
        ctx.step_state.result = StepResult.SUCCESS
        ctx.step_state.message = f"edit package exported ({reason})"
    else:
        ctx.status.export = "skipped"
        ctx.step_state.result = StepResult.SKIPPED
        ctx.step_state.message = reason
    return ctx


def export_clips(ctx: Context) -> Context:
    """Export matched scenes as individual video clips.

    Args:
        ctx: Pipeline execution context.

    Returns:
        Updated pipeline context with exported clips.
    """
    edit_package_requested = bool(ctx.metadata.get("edit_package_export", False))
    if not ctx.metadata.get("export_clips", True) and edit_package_requested:
        return _finish_edit_package_only(ctx, "standalone clip export disabled")
    if not ctx.metadata.get("export_clips", True):
        ctx.status.export = "skipped"
        ctx.step_state.result = StepResult.SKIPPED
        ctx.step_state.message = "disabled by flag"
        return ctx
    ok, hint = probe("scenedetect")
    if not ok:
        if edit_package_requested:
            return _finish_edit_package_only(ctx, "scene detection unavailable")
        ctx.status.export = "disabled"
        ctx.step_state.result = StepResult.SKIPPED
        ctx.step_state.message = hint
        return ctx
    if not ctx.scenes and not ctx.matched_clips:
        if edit_package_requested:
            return _finish_edit_package_only(ctx, "no scenes; audio/text package only")
        ctx.status.export = "skipped"
        ctx.step_state.result = StepResult.SKIPPED
        ctx.step_state.message = "nothing to export"
        return ctx
    if not ctx.source_video_path:
        if edit_package_requested:
            return _finish_edit_package_only(ctx, "no source video; audio/text package only")
        ctx.status.export = "skipped"
        ctx.step_state.result = StepResult.SKIPPED
        ctx.step_state.message = "no source video"
        return ctx

    ffmpeg = ffmpeg_bin()
    if not ffmpeg or ffmpeg == "ffmpeg":
        if edit_package_requested:
            return _finish_edit_package_only(ctx, "ffmpeg unavailable for standalone clips")
        ctx.status.export = "disabled"
        ctx.step_state.result = StepResult.SKIPPED
        ctx.step_state.message = "ffmpeg not found on PATH"
        return ctx

    output_dir = Path(ctx.output_dir)
    clips_dir = output_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    video_codec = ctx.metadata.get("render_video_codec", "libx264")
    audio_codec = ctx.metadata.get("render_audio_codec", "aac")
    ffmpeg_timeout = ctx.metadata.get("render_ffmpeg_timeout", 300)
    failed = 0
    for scene in tqdm(ctx.scenes, desc="Exporting clips", unit="clip"):
        try:
            clip_path = clips_dir / f"scene_{scene.index:04d}.mp4"
            # Direct ffmpeg invocation — export_clips only does seek+cut+encode,
            # so MoviePy adds unnecessary overhead.  Direct subprocess gives
            # precise control over codec params, timeout, and error handling.
            cmd = [
                ffmpeg,
                "-y",
                "-ss",
                str(scene.start),
                "-to",
                str(scene.end),
                "-i",
                ctx.source_video_path,
                "-c:v",
                video_codec,
                "-c:a",
                audio_codec,
                "-movflags",
                "+faststart",
                str(clip_path),
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=ffmpeg_timeout,
            )
            if result.returncode != 0:
                stderr_tail = result.stderr.decode(errors="replace")[-300:]
                raise RuntimeError(f"ffmpeg exited {result.returncode}: {stderr_tail}")
            scene.clip_path = str(clip_path)
        except Exception as e:
            failed += 1
            tqdm.write(f"  ⚠ skip scene {scene.index}: {e}")

    if failed:
        append_warning(ctx, f"{failed} clip(s) failed to export", prefix="export_clips")
    ctx.clips_dir = str(clips_dir)
    package_ok = _export_edit_package_if_requested(ctx)
    ctx.status.export = "success" if not failed and package_ok else "partial"
    if edit_package_requested and not package_ok:
        ctx.step_state.result = StepResult.WARNING
        ctx.step_state.message = "clips exported; edit package export failed"
    return ctx
