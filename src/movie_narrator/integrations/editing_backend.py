# SPDX-License-Identifier: AGPL-3.0-or-later

"""Backend selection without removing the existing FFmpeg renderer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, Sequence

from ..alignment.repair import RepairOperation
from .chatcut.client import ChatCutClient


class EditingBackend(Protocol):
    name: str

    def apply_operations(self, operations: Sequence[RepairOperation]) -> Any: ...

    def read_timeline(self) -> Any: ...


@dataclass
class FFmpegEditingBackend:
    """Marker/backend boundary for the existing local render path."""

    name: str = "ffmpeg"

    def apply_operations(self, operations: Sequence[RepairOperation]) -> Any:
        raise RuntimeError(
            "FFmpeg backend is a render/debug backend; use the existing timeline builder "
            "or renderer to materialize operations"
        )

    def read_timeline(self) -> Any:
        raise RuntimeError("FFmpeg backend has no live project timeline readback")


@dataclass
class ChatCutEditingBackend:
    client: ChatCutClient
    project_id: str
    timeline_id: str | None = None
    name: str = "chatcut"

    def apply_operations(self, operations: Sequence[RepairOperation]) -> Any:
        results = []
        for operation in operations:
            # The host adapter owns the exact MCP schema.  This wrapper sends
            # one auditable edit at a time and never writes a ChatCut DB.
            results.append(
                self.client.apply_edit(
                    operation.model_dump(mode="json"),
                    project_id=self.project_id,
                )
            )
        return results

    def read_timeline(self) -> Any:
        return self.client.read_timeline(
            project_id=self.project_id,
            timeline_id=self.timeline_id,
            views=["timeline"],
        )


def resolve_editing_backend(
    backend: str,
    *,
    chatcut_client: ChatCutClient | None = None,
    project_id: str | None = None,
    timeline_id: str | None = None,
) -> EditingBackend:
    normalized = backend.strip().lower()
    if normalized == "ffmpeg":
        return FFmpegEditingBackend()
    if normalized == "chatcut":
        if chatcut_client is None or not project_id:
            raise RuntimeError(
                "ChatCut backend requires an authenticated MCP client and an exact project_id"
            )
        return ChatCutEditingBackend(
            client=chatcut_client,
            project_id=project_id,
            timeline_id=timeline_id,
        )
    raise ValueError(f"unknown editing backend: {backend!r}; use chatcut or ffmpeg")


def backend_config() -> dict[str, Any]:
    """Return the documented defaults without changing existing pipeline settings."""

    return {
        "backend": "chatcut",
        "fallback_backend": "ffmpeg",
        "chatcut": {
            "enabled": True,
            "verify_after_edit": True,
            "semantic_qc": True,
        },
    }
