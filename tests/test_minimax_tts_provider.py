"""Tests for the official MiniMax T2A adapter without network calls."""

import asyncio
import io
import json
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest
from pydub import AudioSegment

from movie_narrator.config import Settings, TTSProviderType
from movie_narrator.tts.factory import get_tts_provider
from movie_narrator.tts.minimax_provider import MiniMaxTTSProvider
from movie_narrator.utils.errors import ConfigError


def _mp3_hex() -> str:
    output = io.BytesIO()
    AudioSegment.silent(duration=100).export(output, format="mp3")
    return output.getvalue().hex()


class _Response:
    def __init__(self, body: bytes):
        self._body = body
        self.headers = {"Content-Type": "application/json"}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


def test_factory_constructs_minimax_without_network():
    settings = Settings(
        tts_provider=TTSProviderType.MINIMAX,
        minimax_api_key="minimax-test-key",
    )
    provider = get_tts_provider(settings)
    assert isinstance(provider, MiniMaxTTSProvider)


def test_request_payload_decodes_hex_audio(tmp_path: Path):
    settings = Settings(
        tts_provider=TTSProviderType.MINIMAX,
        minimax_api_key="minimax-test-key",
        minimax_tts_speed=0.9,
        minimax_tts_volume=0.8,
        minimax_tts_pitch=-1,
        minimax_tts_emotion="sadness",
        minimax_tts_aigc_watermark=False,
    )
    provider = MiniMaxTTSProvider(settings)
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        body = {"data": {"audio": _mp3_hex()}, "base_resp": {"status_code": 0}}
        return _Response(json.dumps(body).encode("utf-8"))

    output = tmp_path / "segment.mp3"
    with patch("movie_narrator.tts.minimax_provider.urllib.request.urlopen", fake_urlopen):
        asyncio.run(provider._real_synthesize("李和他的侄子", "voice-123", output))

    payload = json.loads(captured["request"].data.decode("utf-8"))
    assert payload == {
        "model": "speech-2.8-hd",
        "text": "李和他的侄子",
        "stream": False,
        "voice_setting": {
            "voice_id": "voice-123",
            "speed": 0.9,
            "vol": 0.8,
            "pitch": -1,
            "emotion": "sadness",
        },
        "audio_setting": {
            "sample_rate": 32000,
            "bitrate": 128000,
            "format": "mp3",
            "channel": 1,
        },
        "subtitle_enable": False,
        "output_format": "hex",
        "aigc_watermark": False,
    }
    assert captured["request"].headers["Authorization"] == "Bearer minimax-test-key"
    assert captured["timeout"] == 60
    assert output.exists() and output.stat().st_size > 0


def test_missing_key_and_invalid_input_are_rejected(tmp_path: Path):
    with pytest.raises(ConfigError, match="MN_MINIMAX_API_KEY"):
        MiniMaxTTSProvider(Settings(tts_provider=TTSProviderType.MINIMAX))

    provider = MiniMaxTTSProvider(Settings(minimax_api_key="test-key"))
    output = tmp_path / "segment.mp3"
    with pytest.raises(ConfigError, match="must not be empty"):
        asyncio.run(provider._real_synthesize(" ", "voice-123", output))
    with pytest.raises(ConfigError, match="shorter than 10000"):
        asyncio.run(provider._real_synthesize("字" * 10000, "voice-123", output))
    with pytest.raises(ConfigError, match="voice must be selected"):
        asyncio.run(provider._real_synthesize("你好", " ", output))


def test_retryable_http_errors_are_connection_errors(monkeypatch):
    provider = MiniMaxTTSProvider(Settings(minimax_api_key="test-key"))
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
        "movie_narrator.tts.minimax_provider.urllib.request.urlopen", fail_urlopen
    )
    with pytest.raises(ConnectionError, match="HTTP 429"):
        provider._request_audio_hex("你好", "voice-123")
