# SPDX-License-Identifier: AGPL-3.0-or-later

"""Crash-safe cinematic run state and artifact provenance hashes."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


class ArtifactRecord(BaseModel):
    path: str
    sha256: str
    size_bytes: int = Field(ge=0)
    stage: str


class CinematicRunState(BaseModel):
    schema_version: Literal["2.1"] = "2.1"
    engine: Literal["cinematic_v2"] = "cinematic_v2"
    source_video: str
    source_sha256: str
    request_sha256: str
    status: Literal["RUNNING", "FAILED", "PREVIEW_READY"] = "RUNNING"
    current_stage: str = "INITIALIZED"
    artifacts: dict[str, ArtifactRecord] = Field(default_factory=dict)
    error: str | None = None
    updated_at: str


class RunStateStore:
    def __init__(self, path: str | Path, state: CinematicRunState) -> None:
        self.path = Path(path)
        self.state = state

    @classmethod
    def open(
        cls,
        path: str | Path,
        *,
        source_video: str | Path,
        request: dict[str, Any],
        resume: bool,
    ) -> "RunStateStore":
        target = Path(path)
        source = Path(source_video).resolve()
        source_sha256 = cls.sha256(source)
        request_sha256 = cls.payload_sha256(request)
        if resume:
            if not target.is_file():
                raise FileNotFoundError(f"cinematic resume state not found: {target}")
            state = CinematicRunState.model_validate_json(
                target.read_text(encoding="utf-8")
            )
            if Path(state.source_video).resolve() != source:
                raise ValueError("cinematic resume source path does not match run state")
            if state.source_sha256 != source_sha256:
                raise ValueError("cinematic resume source hash does not match run state")
            if state.request_sha256 != request_sha256:
                raise ValueError("cinematic resume options do not match run state")
            state.status = "RUNNING"
            state.error = None
            state.updated_at = cls.utc_now()
        else:
            state = CinematicRunState(
                source_video=str(source),
                source_sha256=source_sha256,
                request_sha256=request_sha256,
                updated_at=cls.utc_now(),
            )
        store = cls(target, state)
        store.write()
        return store

    def record(self, name: str, path: str | Path, stage: str) -> None:
        artifact = Path(path).resolve()
        if not artifact.is_file():
            raise FileNotFoundError(f"cannot record missing artifact: {artifact}")
        self.state.artifacts[name] = ArtifactRecord(
            path=str(artifact),
            sha256=self.sha256(artifact),
            size_bytes=artifact.stat().st_size,
            stage=stage,
        )
        self.state.current_stage = stage
        self.state.updated_at = self.utc_now()
        self.write()

    def reusable(self, name: str, expected_path: str | Path) -> bool:
        record = self.state.artifacts.get(name)
        expected = Path(expected_path).resolve()
        if record is None or Path(record.path).resolve() != expected or not expected.is_file():
            return False
        return (
            expected.stat().st_size == record.size_bytes
            and self.sha256(expected) == record.sha256
        )

    def complete(self) -> None:
        self.state.status = "PREVIEW_READY"
        self.state.current_stage = "POST_RENDER_QA"
        self.state.error = None
        self.state.updated_at = self.utc_now()
        self.write()

    def fail(self, exc: Exception) -> None:
        self.state.status = "FAILED"
        self.state.error = f"{type(exc).__name__}: {exc}"
        self.state.updated_at = self.utc_now()
        self.write()

    def write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        temporary.write_text(
            json.dumps(self.state.model_dump(mode="json"), ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)

    @staticmethod
    def sha256(path: str | Path) -> str:
        digest = hashlib.sha256()
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def payload_sha256(payload: dict[str, Any]) -> str:
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    @staticmethod
    def utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()
