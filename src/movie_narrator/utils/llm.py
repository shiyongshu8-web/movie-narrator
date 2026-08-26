# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""LLM client factory backed by the provider registry.

The built-in ``"openai"`` provider is registered at import time.
External plugins can register additional LLM providers via
:func:`register_llm`.

``get_llm_client()`` remains a zero-argument callable that returns a
context manager yielding :class:`LLMClient`. This preserves backward
compatibility with all existing call sites and test patches.

Since v0.9.1 the yielded client context runs under the shared ``"llm"``
circuit breaker: when the circuit is open, entering ``with
get_llm_client() as llm:`` raises :class:`CircuitOpenError` (retryable)
without creating a client or touching the network.
"""

import json
from dataclasses import dataclass
from contextlib import contextmanager
from typing import Any, Iterator

import httpx
from openai import OpenAI

from ..config import Settings, get_settings
from ..providers import llm_registry, register_llm
from ..reliability import CIRCUIT_REGISTRY
from .errors import ConfigError


@dataclass
class LLMClient:
    """LLM client wrapper with model reference."""

    client: OpenAI
    model: str


def get_llm_extra_body(settings: Settings | None = None) -> dict[str, Any] | None:
    """Parse the optional generic OpenAI-compatible request body extension.

    ``MN_LLM_EXTRA_BODY_JSON`` is intentionally a JSON object rather than a
    provider-specific setting. Empty/unset values preserve the original
    request shape by returning ``None``. Invalid JSON and non-object JSON are
    configuration errors, not silently ignored request mutations.
    """
    settings = settings or get_settings()
    raw_value = getattr(settings, "llm_extra_body_json", "")
    # A few downstream integrations pass lightweight Settings stand-ins.
    # Treat a missing/non-string optional field as unset while real Settings
    # instances always provide the declared string field.
    raw = raw_value.strip() if isinstance(raw_value, str) else ""
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ConfigError("MN_LLM_EXTRA_BODY_JSON must be valid JSON object") from exc
    if not isinstance(value, dict):
        raise ConfigError("MN_LLM_EXTRA_BODY_JSON must decode to a JSON object")
    return value


def get_llm_request_kwargs(settings: Settings | None = None) -> dict[str, Any]:
    """Return optional kwargs for an OpenAI-compatible chat completion call."""
    extra_body = get_llm_extra_body(settings)
    return {"extra_body": extra_body} if extra_body is not None else {}


# ── Built-in "openai" provider ───────────────────────────


@register_llm("openai")
def _make_openai_llm():
    """Factory for the OpenAI-compatible LLM provider.

    Returns:
        A context manager that yields an :class:`LLMClient`
        backed by a managed ``httpx.Client`` (closed on exit).
    """

    @contextmanager
    def _cm():
        settings = get_settings()
        http_client = httpx.Client(timeout=settings.llm_timeout)
        try:
            client = OpenAI(
                base_url=settings.llm_base_url,
                api_key=settings.llm_api_key,
                http_client=http_client,
            )
            yield LLMClient(client=client, model=settings.llm_model)
        finally:
            http_client.close()

    return _cm()


# ── Public factory function ──────────────────────────────


@contextmanager
def get_llm_client() -> Iterator[LLMClient]:
    """Yield an LLMClient via the llm_registry.

    Dispatches to the provider configured by ``settings.llm_provider``
    (default: ``"openai"``). The returned object is a context manager
    that must be used in a ``with`` statement.

    Since v0.9.1 the client context runs under the shared ``"llm"``
    circuit breaker: when the circuit is open, entering the ``with``
    block raises :class:`CircuitOpenError` (retryable) before the
    provider factory is invoked, so no client is created and no network
    request is attempted. Exceptions raised inside the ``with`` body are
    recorded as breaker failures before propagating unchanged.

    This function's module path (``movie_narrator.utils.llm``) and
    zero-argument signature are preserved for backward compatibility
    with existing call sites and test patches.
    """
    settings = get_settings()
    breaker = CIRCUIT_REGISTRY["llm"]
    with breaker.guard():
        cm = llm_registry.create(settings.llm_provider)
        with cm as llm:
            yield llm
