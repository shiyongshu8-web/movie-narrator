from unittest.mock import MagicMock

import pytest

from movie_narrator.config import Settings
from movie_narrator.utils.errors import ConfigError
from movie_narrator.utils.llm import get_llm_extra_body, get_llm_request_kwargs


def test_unset_extra_body_is_not_injected():
    settings = Settings(_env_file=None, llm_extra_body_json="")

    assert get_llm_extra_body(settings) is None

    client = MagicMock()
    client.chat.completions.create(model="test", messages=[], **get_llm_request_kwargs(settings))
    assert "extra_body" not in client.chat.completions.create.call_args.kwargs


def test_valid_extra_body_json_becomes_dict_and_is_forwarded():
    settings = Settings(
        _env_file=None,
        llm_extra_body_json='{"thinking":{"type":"disabled"}}',
    )

    expected = {"thinking": {"type": "disabled"}}
    assert get_llm_extra_body(settings) == expected

    client = MagicMock()
    client.chat.completions.create(model="test", messages=[], **get_llm_request_kwargs(settings))
    assert client.chat.completions.create.call_args.kwargs["extra_body"] == expected


def test_invalid_extra_body_json_is_a_configuration_error():
    settings = Settings(_env_file=None, llm_extra_body_json="not-json")

    with pytest.raises(ConfigError, match="MN_LLM_EXTRA_BODY_JSON"):
        get_llm_extra_body(settings)


@pytest.mark.parametrize("raw", ["[]", '"text"', "123"])
def test_extra_body_json_must_be_an_object(raw):
    settings = Settings(_env_file=None, llm_extra_body_json=raw)

    with pytest.raises(ConfigError, match="JSON object"):
        get_llm_extra_body(settings)
