import pytest

from aurora.llm.providers import (
    AIProviderConfig,
    AIProviderError,
    is_credit_exhaustion,
)


def test_provider_aliases_and_default_models():
    assert AIProviderConfig(provider="chatgpt").canonical_provider == "openai"
    assert AIProviderConfig(provider="chat").resolved_model == "gpt-4o"
    assert AIProviderConfig(provider="gemini").resolved_model == "gemini-2.5-flash-lite"
    assert AIProviderConfig(provider="openrouter").resolved_key_env == "OPENROUTER_API_KEY"


def test_unknown_provider_has_no_default_model():
    with pytest.raises(KeyError):
        _ = AIProviderConfig(provider="unknown").resolved_model


def test_provider_error_type_is_runtime_error():
    assert issubclass(AIProviderError, RuntimeError)


def test_only_credit_or_quota_errors_trigger_credit_stop():
    assert is_credit_exhaustion("HTTP 402 Payment Required")
    assert is_credit_exhaustion("HTTP 429 rate limit")
    assert is_credit_exhaustion("OpenRouter usage cap reached")
    assert is_credit_exhaustion("insufficient credits")
    assert is_credit_exhaustion("quota exceeded")
    assert not is_credit_exhaustion("HTTP 503 temporary upstream error")
    assert not is_credit_exhaustion("request timed out")
