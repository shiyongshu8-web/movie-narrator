"""Tests for the official Zhipu GLM-TTS adapter."""

import asyncio
import io
import json
import urllib.error
import wave
from pathlib import Path
from unittest.mock import patch

import pytest

from movie_narrator.config import Settings, TTSProviderType
from movie_narrator.tts.factory import get_tts_provider
from movie_narrator.tts.zhipu_provider import ZhipuTTSProvider
from movie_narrator.utils.errors import ConfigError


def _wav_bytes() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(24000)
        handle.writeframes(b"\x00\x00" * 2400)
    return buf.getvalue()


class _Response:
    def __init__(self, body: bytes):
        self._body = body
        self.headers = {"Content-Type": "audio/wav"}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


def test_factory_constructs_zhipu_without_network():
    settings = Settings(
        tts_provider=TTSProviderType.ZHIPU,
        llm_api_key="test-key",
        zhipu_tts_api_key=None,
    )
    provider = get_tts_provider(settings)
    assert isinstance(provider, ZhipuTTSProvider)


def test_private_voice_id_is_sent_and_wav_is_converted(tmp_path: Path):
    settings = Settings(
        llm_api_key="test-key",
        zhipu_tts_speed=1.1,
        zhipu_tts_volume=0.8,
        zhipu_tts_watermark_enabled=False,
    )
    provider = ZhipuTTSProvider(settings)
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return _Response(_wav_bytes())

    output = tmp_path / "segment.mp3"
    with patch("movie_narrator.tts.zhipu_provider.urllib.request.urlopen", fake_urlopen):
        asyncio.run(provider._real_synthesize("李和他的侄子", "private-voice-123", output))

    payload = json.loads(captured["request"].data.decode("utf-8"))
    assert payload == {
        "model": "glm-tts",
        "input": "李和他的侄子",
        "voice": "private-voice-123",
        "response_format": "wav",
        "speed": 1.1,
        "volume": 0.8,
        "watermark_enabled": False,
    }
    assert captured["request"].headers["Authorization"] == "Bearer test-key"
    assert captured["timeout"] == 60
    assert output.exists()
    assert output.stat().st_size > 0


def test_empty_or_oversized_input_is_rejected(tmp_path: Path):
    provider = ZhipuTTSProvider(Settings(llm_api_key="test-key"))
    output = tmp_path / "segment.mp3"
    with pytest.raises(ConfigError, match="must not be empty"):
        asyncio.run(provider._real_synthesize(" ", "tongtong", output))
    with pytest.raises(ConfigError, match="1024"):
        asyncio.run(provider._real_synthesize("字" * 1025, "tongtong", output))


def test_retryable_http_errors_are_connection_errors(monkeypatch):
    provider = ZhipuTTSProvider(Settings(llm_api_key="test-key"))
    error = urllib.error.HTTPError(
        url="https://example.invalid",
        code=429,
        msg="too many requests",
        hdrs=None,
        fp=io.BytesIO(b'{"error":"rate limit"}'),
    )

    def fail_urlopen(*args, **kwargs):
        raise error

    monkeypatch.setattr(
        "movie_narrator.tts.zhipu_provider.urllib.request.urlopen", fail_urlopen
    )
    with pytest.raises(ConnectionError, match="HTTP 429"):
        provider._request_wav("你好", "tongtong")
