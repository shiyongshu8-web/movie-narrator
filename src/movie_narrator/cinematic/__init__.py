"""Cinematic V2 contracts and orchestration."""

from typing import TYPE_CHECKING, Any

from .models import (
    AudioDecision,
    DialogueCue,
    NarrationSegment,
    SceneCandidate,
    SceneDatabase,
    SceneMatch,
    SceneRecord,
    TimelineDocument,
    TimelineItem,
)
from .script_generator import CinematicScriptGenerator

if TYPE_CHECKING:
    from .narration import CinematicNarrationSynthesizer
    from .pipeline import CinematicPipeline, CinematicResult

__all__ = [
    "AudioDecision",
    "CinematicScriptGenerator",
    "CinematicNarrationSynthesizer",
    "CinematicPipeline",
    "CinematicResult",
    "DialogueCue",
    "NarrationSegment",
    "SceneCandidate",
    "SceneDatabase",
    "SceneMatch",
    "SceneRecord",
    "TimelineDocument",
    "TimelineItem",
]


def __getattr__(name: str) -> Any:
    """Keep convenient exports without importing the orchestrator during model loads."""
    if name == "CinematicNarrationSynthesizer":
        from .narration import CinematicNarrationSynthesizer

        return CinematicNarrationSynthesizer
    if name in {"CinematicPipeline", "CinematicResult"}:
        from .pipeline import CinematicPipeline, CinematicResult

        return {"CinematicPipeline": CinematicPipeline, "CinematicResult": CinematicResult}[name]
    raise AttributeError(name)
