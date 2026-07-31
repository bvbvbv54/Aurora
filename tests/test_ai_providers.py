import pytest

from aurora.llm.providers import AIProviderConfig, AIProviderError


def test_provider_aliases_and_default_models():
    assert AIProviderConfig(provider="chatgpt").canonical_provider == "openai"
    assert AIProviderConfig(provider="chat").resolved_model == "gpt-4o"
    assert AIProviderConfig(provider="gemini").resolved_model == "gemini-3.6-flash"
    assert AIProviderConfig(provider="openrouter").resolved_key_env == "OPENROUTER_API_KEY"


def test_unknown_provider_has_no_default_model():
    with pytest.raises(KeyError):
        _ = AIProviderConfig(provider="unknown").resolved_model


def test_provider_error_type_is_runtime_error():
    assert issubclass(AIProviderError, RuntimeError)
