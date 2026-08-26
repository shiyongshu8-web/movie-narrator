"""Event-bound narration contracts."""

from .segments import (
    BoundNarrationSegment,
    NarrationSegmentsDocument,
    load_narration_segments,
    write_narration_segments,
)

__all__ = [
    "BoundNarrationSegment",
    "NarrationSegmentsDocument",
    "load_narration_segments",
    "write_narration_segments",
]
