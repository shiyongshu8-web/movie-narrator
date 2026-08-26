# SPDX-License-Identifier: AGPL-3.0-or-later

"""Visual-analysis adapters for cinematic scene enrichment."""

from __future__ import annotations

import base64
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Protocol

from ..cinematic.models import AnalysisStatus, SceneRecord, VisualAnalysis
from ..utils.ffmpeg_bin import ffmpeg_bin


class VisualAnalyzer(Protocol):
    name: str

    def analyze(self, media_path: str, scene: SceneRecord) -> VisualAnalysis: ...


class NullVisualAnalyzer:
    name = "none"

    def analyze(self, media_path: str, scene: SceneRecord) -> VisualAnalysis:
        return VisualAnalysis()


class OpenAICompatibleVisualAnalyzer:
    """Analyze three temporal samples through an injected multimodal client."""

    name = "openai-compatible"

    def __init__(self, client: Any, model: str, *, timeout: int = 60) -> None:
        self.client = client
        self.model = model
        self.timeout = timeout

    def analyze(self, media_path: str, scene: SceneRecord) -> VisualAnalysis:
        duration = scene.end_time - scene.start_time
        timestamps = [
            scene.start_time + duration * fraction for fraction in (0.2, 0.5, 0.8)
        ]
        data_urls = [
            "data:image/jpeg;base64," + base64.b64encode(
                self._extract_frame(media_path, timestamp)
            ).decode("ascii")
            for timestamp in timestamps
        ]
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Return JSON only with characters(list), location, action, emotion, "
                        "visual_description, importance_score(0..1). Use UNKNOWN when uncertain."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Analyze these early/middle/late frames as one film shot. "
                                "Describe visible change and do not invent identity."
                            ),
                        },
                        *[
                            {"type": "image_url", "image_url": {"url": data_url}}
                            for data_url in data_urls
                        ],
                    ],
                },
            ],
        )
        content = response.choices[0].message.content or "{}"
        payload = self._parse_json(content)
        payload["status"] = AnalysisStatus.PARTIAL
        return VisualAnalysis.model_validate(payload)

    def _extract_frame(self, media_path: str, timestamp: float) -> bytes:
        with tempfile.TemporaryDirectory(prefix="mn-cinematic-frame-") as temp:
            target = Path(temp) / "frame.jpg"
            command = [
                ffmpeg_bin(),
                "-y",
                "-loglevel",
                "error",
                "-ss",
                f"{timestamp:.3f}",
                "-i",
                media_path,
                "-frames:v",
                "1",
                "-q:v",
                "2",
                str(target),
            ]
            result = subprocess.run(command, capture_output=True, timeout=self.timeout)
            if result.returncode != 0 or not target.exists():
                raise RuntimeError("visual frame extraction failed")
            return target.read_bytes()

    @staticmethod
    def _parse_json(content: str) -> dict:
        text = content.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1])
            if text.lstrip().startswith("json"):
                text = text.lstrip()[4:].lstrip()
        value = json.loads(text)
        if not isinstance(value, dict):
            raise ValueError("visual response must be a JSON object")
        return value
