# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""MiniMax T2A v2 provider.

The official MiniMax HTTP endpoint returns audio as a hexadecimal string.  The
pipeline contract is an MP3 file at ``output_path``, so this adapter decodes
the response and converts non-MP3 formats when necessary.  API credentials
are read from settings and are never included in cache keys or error text.
"""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path
from typing import Final, Any

from pydub import AudioSegment

from ..config import Settings
from ..utils.errors import ConfigError
from .base import BaseTTSProvider

MINIMAX_TTS_ENDPOINT: Final[str] = "/t2a_v2"
MINIMAX_TTS_MODELS: Final[frozenset[str]] = frozenset(
    {
        "speech-2.8-hd",
        "speech-2.8-turbo",
        "speech-2.6-hd",
        "speech-2.6-turbo",
        "speech-02-hd",
        "speech-02-turbo",
        "speech-01-hd",
        "speech-01-turbo",
    }
)
MINIMAX_AUDIO_FORMATS: Final[frozenset[str]] = frozenset({"mp3", "wav", "pcm", "flac"})


class MiniMaxTTSProvider(BaseTTSProvider):
    """MiniMax Speech 2.x T2A over the official ``/v1/t2a_v2`` endpoint."""

    def __init__(self, settings: Settings):
        # Do not fall back to the project's LLM key: a MiniMax credential is a
        # different account boundary and silently using another provider key
        # makes configuration failures hard to diagnose.
        api_key = settings.minimax_api_key
        if not api_key:
            raise ConfigError("MiniMax TTS requires MN_MINIMAX_API_KEY to be set.")

        model = settings.minimax_tts_model.strip()
        if model not in MINIMAX_TTS_MODELS:
            raise ConfigError(
                "MN_MINIMAX_TTS_MODEL must be one of: "
                + ", ".join(sorted(MINIMAX_TTS_MODELS))
            )

        audio_format = settings.minimax_tts_format.strip().lower()
        if audio_format not in MINIMAX_AUDIO_FORMATS:
            raise ConfigError(
                "MN_MINIMAX_TTS_FORMAT must be one of: "
                + ", ".join(sorted(MINIMAX_AUDIO_FORMATS))
            )
        if not 0.5 <= settings.minimax_tts_speed <= 2.0:
            raise ConfigError("MN_MINIMAX_TTS_SPEED must be between 0.5 and 2.0.")
        if not 0.0 < settings.minimax_tts_volume <= 10.0:
            raise ConfigError("MN_MINIMAX_TTS_VOLUME must be greater than 0 and at most 10.")
        if settings.minimax_tts_sample_rate <= 0 or settings.minimax_tts_bitrate <= 0:
            raise ConfigError("MiniMax sample rate and bitrate must be positive integers.")
        if settings.minimax_tts_channel not in {1, 2}:
            raise ConfigError("MN_MINIMAX_TTS_CHANNEL must be 1 or 2.")

        self._api_key = api_key
        self._base_url = settings.minimax_base_url.rstrip("/")
        self._model = model
        self._speed = settings.minimax_tts_speed
        self._volume = settings.minimax_tts_volume
        self._pitch = settings.minimax_tts_pitch
        self._emotion = (settings.minimax_tts_emotion or "").strip() or None
        self._sample_rate = settings.minimax_tts_sample_rate
        self._bitrate = settings.minimax_tts_bitrate
        self._format = audio_format
        self._channel = settings.minimax_tts_channel
        self._aigc_watermark = settings.minimax_tts_aigc_watermark
        self._timeout = settings.minimax_tts_timeout

    async def _real_synthesize(self, text: str, voice: str, output_path: Path) -> None:
        if not text.strip():
            raise ConfigError("MiniMax TTS input text must not be empty.")
        # The HTTP API accepts fewer than 10,000 characters per request.  The
        # pipeline normally sends short phrase-level segments, but keep this
        # guard here for direct provider use as well.
        if len(text) >= 10000:
            raise ConfigError("MiniMax T2A input text must be shorter than 10000 characters.")
        if not voice.strip():
            raise ConfigError("MiniMax TTS voice must be selected before synthesis.")

        audio_hex = await asyncio.to_thread(self._request_audio_hex, text, voice)
        try:
            raw = bytes.fromhex(audio_hex)
        except ValueError as exc:
            raise RuntimeError("MiniMax TTS returned invalid hexadecimal audio data.") from exc
        if not raw:
            raise RuntimeError("MiniMax TTS returned empty audio data.")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        if self._format == "mp3":
            output_path.write_bytes(raw)
            return

        try:
            if self._format == "pcm":
                audio = AudioSegment(
                    data=raw,
                    sample_width=2,
                    frame_rate=self._sample_rate,
                    channels=self._channel,
                )
            else:
                audio = AudioSegment.from_file(BytesIO(raw), format=self._format)
            audio.export(output_path, format="mp3", bitrate="128k")
        except Exception as exc:  # noqa: BLE001 - malformed remote audio needs a provider error
            raise RuntimeError(
                f"MiniMax TTS returned an unreadable {self._format.upper()} response."
            ) from exc

    def _request_audio_hex(self, text: str, voice: str) -> str:
        voice_setting: dict[str, Any] = {
            "voice_id": voice,
            "speed": self._speed,
            "vol": self._volume,
            "pitch": self._pitch,
        }
        if self._emotion:
            voice_setting["emotion"] = self._emotion

        payload = {
            "model": self._model,
            "text": text,
            "stream": False,
            "voice_setting": voice_setting,
            "audio_setting": {
                "sample_rate": self._sample_rate,
                "bitrate": self._bitrate,
                "format": self._format,
                "channel": self._channel,
            },
            "subtitle_enable": False,
            "output_format": "hex",
            "aigc_watermark": self._aigc_watermark,
        }
        request = urllib.request.Request(
            f"{self._base_url}{MINIMAX_TTS_ENDPOINT}",
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
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            message = f"MiniMax TTS request failed (HTTP {exc.code}): {detail[:500]}"
            if exc.code == 429 or exc.code >= 500:
                raise ConnectionError(message) from exc
            raise ConfigError(message) from exc
        except urllib.error.URLError as exc:
            raise ConnectionError(f"MiniMax TTS endpoint unreachable: {exc.reason}") from exc

        try:
            response_data = json.loads(body.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            raise RuntimeError("MiniMax TTS returned a non-JSON response.") from exc

        base_resp = response_data.get("base_resp") or {}
        status_code = str(base_resp.get("status_code", "0"))
        if status_code != "0":
            status_msg = base_resp.get("status_msg") or "unknown MiniMax API error"
            raise ConfigError(f"MiniMax TTS returned an error: {status_msg}")

        audio_hex = ((response_data.get("data") or {}).get("audio") or "").strip()
        if not audio_hex:
            raise RuntimeError("MiniMax TTS response did not contain data.audio.")
        return audio_hex
