# SPDX-License-Identifier: AGPL-3.0-or-later

"""ASR adapters for extracting source-dialogue candidates."""

from __future__ import annotations

from typing import Protocol

from ..cinematic.models import DialogueCue, VerificationStatus


class ASRBackend(Protocol):
    name: str

    def transcribe(self, media_path: str) -> list[DialogueCue]: ...


def _to_cues(segments: list[dict], source: str) -> list[DialogueCue]:
    cues: list[DialogueCue] = []
    for segment in segments:
        text = str(segment.get("text", "")).strip()
        if not text:
            continue
        start = float(segment.get("start", 0.0))
        end = float(segment.get("end", 0.0))
        if end <= start:
            continue
        cues.append(
            DialogueCue(
                start_time=start,
                end_time=end,
                text=text,
                verification_status=VerificationStatus.UNVERIFIED,
                source=source,
            )
        )
    return cues


class NullASRBackend:
    name = "none"

    def transcribe(self, media_path: str) -> list[DialogueCue]:
        return []


class AutoASRBackend:
    """Try configured ASR backends in order without relabeling ASR as verified dialogue."""

    def __init__(
        self,
        preferred: tuple[str, ...] = ("whisperx", "faster-whisper", "funasr"),
        *,
        language: str = "zh",
        device: str = "cpu",
        model: str = "small",
    ) -> None:
        self.preferred = preferred
        self.language = language
        self.device = device
        self.model = model
        self.resolved_backend = "none"

    @property
    def name(self) -> str:
        return self.resolved_backend if self.resolved_backend != "none" else "auto"

    def transcribe(self, media_path: str) -> list[DialogueCue]:
        failures: list[str] = []
        for backend in self.preferred:
            try:
                segments = self._run_backend(backend, media_path)
            except Exception as exc:  # optional backends degrade explicitly
                failures.append(f"{backend}: {type(exc).__name__}: {exc}")
                continue
            self.resolved_backend = backend
            return _to_cues(segments, backend)
        if failures:
            raise RuntimeError("all ASR backends failed: " + " | ".join(failures))
        return []

    def _run_backend(self, backend: str, media_path: str) -> list[dict]:
        if backend == "faster-whisper":
            from ..pipeline._align_backend import transcribe_with_faster_whisper

            return transcribe_with_faster_whisper(
                audio_path=media_path,
                device=self.device,
                language=self.language,
                model_size=self.model,
            )
        if backend == "funasr":
            from ..providers.asr.funasr import transcribe_with_funasr

            return transcribe_with_funasr(
                audio_path=media_path,
                device=self.device,
                model=self.model if self.model not in {"small", "medium"} else None,
            )
        if backend == "whisperx":
            import whisperx

            audio = whisperx.load_audio(media_path)
            model = whisperx.load_model(self.model, device=self.device)
            result = model.transcribe(audio, language=self.language)
            return list((result or {}).get("segments", []))
        raise ValueError(f"unsupported ASR backend: {backend}")
