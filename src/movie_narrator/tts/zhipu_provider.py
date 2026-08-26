# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""智谱 GLM-TTS provider."""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path
from typing import Final

from pydub import AudioSegment

from ..config import Settings
from ..utils.errors import ConfigError
from .base import BaseTTSProvider

ZHIPU_TTS_MODEL: Final[str] = "glm-tts"
ZHIPU_TTS_ENDPOINT: Final[str] = "/audio/speech"
ZHIPU_SYSTEM_VOICES: Final[frozenset[str]] = frozenset(
    {
        "tongtong",
        "chuichui",
        "xiaochen",
        "jam",
        "kazi",
        "douji",
        "luodo",
        "streamer",
        "streamer_male",
        "douxin",
    }
)


class ZhipuTTSProvider(BaseTTSProvider):
    """智谱 GLM-TTS via the official ``/v4/audio/speech`` endpoint.

    The voice is intentionally not restricted to the system set because the
    account voice-list API can return private or cloned voice IDs.
    """

    def __init__(self, settings: Settings):
        api_key = settings.zhipu_tts_api_key or settings.llm_api_key
        if not api_key:
            raise ConfigError(
                "智谱 TTS requires MN_ZHIPU_TTS_API_KEY or MN_LLM_API_KEY set."
            )
        self._api_key = api_key
        self._base_url = settings.zhipu_tts_base_url.rstrip("/")
        self._model = settings.zhipu_tts_model
        self._speed = settings.zhipu_tts_speed
        self._volume = settings.zhipu_tts_volume
        self._watermark_enabled = settings.zhipu_tts_watermark_enabled
        self._timeout = settings.zhipu_tts_timeout

        if not 0.5 <= self._speed <= 2.0:
            raise ConfigError("MN_ZHIPU_TTS_SPEED must be between 0.5 and 2.0.")
        if not 0.0 < self._volume <= 10.0:
            raise ConfigError("MN_ZHIPU_TTS_VOLUME must be greater than 0 and at most 10.")

    async def _real_synthesize(self, text: str, voice: str, output_path: Path) -> None:
        if not text.strip():
            raise ConfigError("智谱 TTS input text must not be empty.")
        if len(text) > 1024:
            raise ConfigError("智谱 GLM-TTS input text must not exceed 1024 characters per request.")
        if not voice.strip():
            raise ConfigError("智谱 TTS voice must be selected before synthesis.")

        raw = await asyncio.to_thread(self._request_wav, text, voice)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            audio = AudioSegment.from_file(BytesIO(raw), format="wav")
        except Exception as exc:  # noqa: BLE001 - malformed remote audio needs a provider error
            raise RuntimeError("智谱 TTS returned an unreadable WAV response.") from exc
        audio.export(output_path, format="mp3", bitrate="128k")

    def _request_wav(self, text: str, voice: str) -> bytes:
        payload = {
            "model": self._model,
            "input": text,
            "voice": voice,
            "response_format": "wav",
            "speed": self._speed,
            "volume": self._volume,
            "watermark_enabled": self._watermark_enabled,
        }
        request = urllib.request.Request(
            f"{self._base_url}{ZHIPU_TTS_ENDPOINT}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310
                body = response.read()
                content_type = response.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            message = f"智谱 TTS request failed (HTTP {exc.code}): {detail[:500]}"
            if exc.code == 429 or exc.code >= 500:
                raise ConnectionError(message) from exc
            raise ConfigError(message) from exc
        except urllib.error.URLError as exc:
            raise ConnectionError(f"智谱 TTS endpoint unreachable: {exc.reason}") from exc

        if "json" in content_type.lower() or body[:1] in {b"{", b"["}:
            try:
                detail = json.loads(body.decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                detail = body[:500].decode("utf-8", errors="replace")
            raise ConfigError(f"智谱 TTS returned an error: {detail}")
        return body
