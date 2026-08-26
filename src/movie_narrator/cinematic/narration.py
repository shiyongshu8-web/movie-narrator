# SPDX-License-Identifier: AGPL-3.0-or-later

"""Synthesize independent narration assets for timeline placement."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Sequence

from pydub import AudioSegment

from ..tts.protocol import TTSProvider
from ..utils.async_utils import run_async
from .models import NarrationSegment


class CinematicNarrationSynthesizer:
    def __init__(self, provider: TTSProvider, voice: str) -> None:
        self.provider = provider
        self.voice = voice

    def synthesize(
        self,
        segments: Sequence[NarrationSegment],
        output_dir: str | Path,
        *,
        enabled_ids: set[str] | None = None,
    ) -> list[NarrationSegment]:
        target = Path(output_dir)
        target.mkdir(parents=True, exist_ok=True)
        rendered: list[NarrationSegment] = []
        for index, segment in enumerate(segments, start=1):
            if (
                segment.audio_priority == "dialogue"
                or enabled_ids is not None
                and segment.id not in enabled_ids
            ):
                rendered.append(segment)
                continue
            if (
                segment.tts_asset
                and segment.tts_duration is not None
                and Path(segment.tts_asset).is_file()
                and Path(segment.tts_asset).stat().st_size > 0
            ):
                rendered.append(segment)
                continue
            safe_id = re.sub(r"[^A-Za-z0-9_-]+", "_", segment.id).strip("_")
            path = target / f"{index:04d}_{safe_id or 'segment'}.mp3"
            run_async(
                self.provider.synthesize(segment.narration, self.voice, path),
                timeout=300,
            )
            if not path.is_file() or path.stat().st_size <= 0:
                raise RuntimeError(f"TTS provider did not create audio for {segment.id}")
            duration = len(AudioSegment.from_file(path)) / 1000.0
            if duration <= 0:
                raise RuntimeError(f"TTS duration is invalid for {segment.id}")
            rendered.append(
                segment.model_copy(
                    update={"tts_asset": str(path.resolve()), "tts_duration": duration}
                )
            )
        return rendered
