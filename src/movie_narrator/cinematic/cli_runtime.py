# SPDX-License-Identifier: AGPL-3.0-or-later

"""Thin CLI factory for cinematic V2; classic pipeline remains untouched."""

from __future__ import annotations

from pathlib import Path

from ..movie_analyzer import (
    AutoASRBackend,
    MovieAnalyzer,
    NullASRBackend,
    NullVisualAnalyzer,
    OpenAICompatibleVisualAnalyzer,
)
from ..tts import get_tts_provider
from ..scene_memory import SentenceTransformerVisualEmbedder
from ..tts.voice_map import resolve_voice
from ..utils.llm import get_llm_client
from ..config import get_settings
from .narration import CinematicNarrationSynthesizer
from .pipeline import CinematicPipeline, CinematicResult
from .script_generator import CinematicScriptGenerator


def run_cinematic_create(
    *,
    source_video: str,
    output_dir: str | Path,
    style: str,
    target_duration: int,
    voice: str | None,
    bgm_asset: str | None,
    asr_backend: str = "auto",
    visual_analysis: bool = True,
    top_k: int = 5,
    resume: bool = False,
    locked_matches_path: str | None = None,
    visual_embedding_model: str | None = None,
) -> CinematicResult:
    settings = get_settings()
    provider_name = (
        settings.tts_provider.value
        if hasattr(settings.tts_provider, "value")
        else str(settings.tts_provider)
    )
    resolved_voice = (
        resolve_voice(
            "zh",
            provider_name,
            explicit_voice=voice,
            settings=settings,
        )
        or settings.default_voice
    )
    asr = (
        NullASRBackend()
        if asr_backend == "none"
        else AutoASRBackend(
            preferred=(asr_backend,) if asr_backend != "auto" else (
                "whisperx",
                "faster-whisper",
                "funasr",
            )
        )
    )
    with get_llm_client() as llm:
        visual = (
            OpenAICompatibleVisualAnalyzer(llm.client, llm.model)
            if visual_analysis
            else NullVisualAnalyzer()
        )
        pipeline = CinematicPipeline(
            analyzer=MovieAnalyzer(asr_backend=asr, visual_analyzer=visual),
            script_generator=CinematicScriptGenerator(llm.client, llm.model),
            narration_synthesizer=CinematicNarrationSynthesizer(
                get_tts_provider(settings), resolved_voice
            ),
            visual_embedder=(
                SentenceTransformerVisualEmbedder(visual_embedding_model)
                if visual_embedding_model
                else None
            ),
        )
        return pipeline.run(
            source_video=source_video,
            output_dir=output_dir,
            style=style,
            target_duration=target_duration,
            bgm_asset=bgm_asset,
            top_k=top_k,
            resume=resume,
            locked_matches_path=locked_matches_path,
        )
