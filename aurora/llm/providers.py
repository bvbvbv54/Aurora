from __future__ import annotations

import base64
import json
import mimetypes
import os
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


class AIProviderError(RuntimeError):
    pass


PROVIDER_ALIASES = {
    "chat": "openai",
    "chatgpt": "openai",
    "gpt": "openai",
    "google": "gemini",
}

DEFAULT_MODELS = {
    "openai": "gpt-4o",
    "gemini": "gemini-3.6-flash",
    "openrouter": "openai/gpt-4o-mini",
}

DEFAULT_KEY_ENVS = {
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


@dataclass(frozen=True)
class AIProviderConfig:
    provider: str = "openai"
    model: str | None = None
    api_key_env: str | None = None
    base_url: str | None = None
    temperature: float = 0.4
    max_tokens: int = 16000
    json_mode: bool = False

    @property
    def canonical_provider(self) -> str:
        return PROVIDER_ALIASES.get(self.provider.lower(), self.provider.lower())

    @property
    def resolved_model(self) -> str:
        return self.model or DEFAULT_MODELS[self.canonical_provider]

    @property
    def resolved_key_env(self) -> str:
        return self.api_key_env or DEFAULT_KEY_ENVS[self.canonical_provider]


def _api_key(config: AIProviderConfig) -> str:
    value = os.getenv(config.resolved_key_env)
    if not value and config.canonical_provider == "gemini":
        value = os.getenv("GOOGLE_API_KEY")
    if not value:
        raise AIProviderError(
            f"missing API key environment variable: {config.resolved_key_env}"
        )
    return value


def _generate_openai_compatible(prompt: str, config: AIProviderConfig) -> str:
    try:
        from openai import OpenAI, OpenAIError
    except ImportError as exc:
        raise AIProviderError(
            'OpenAI-compatible providers require: pip install -e ".[llm]"'
        ) from exc
    provider = config.canonical_provider
    base_url = config.base_url
    if provider == "openrouter" and not base_url:
        base_url = "https://openrouter.ai/api/v1"
    try:
        client = OpenAI(api_key=_api_key(config), base_url=base_url)
        request_options = {
            "model": config.resolved_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
        }
        if config.json_mode:
            request_options["response_format"] = {"type": "json_object"}
        response = client.chat.completions.create(
            **request_options
        )
        value = (response.choices[0].message.content or "").strip()
        if not value:
            raise AIProviderError(
                f"{config.resolved_model} returned an empty text response"
            )
        return value
    except OpenAIError as exc:
        raise AIProviderError(str(exc)) from exc


def _generate_gemini(prompt: str, config: AIProviderConfig) -> str:
    key = _api_key(config)
    base = config.base_url or "https://generativelanguage.googleapis.com/v1beta"
    url = f"{base.rstrip('/')}/models/{quote(config.resolved_model)}:generateContent"
    generation_config = {
        "temperature": config.temperature,
        "maxOutputTokens": config.max_tokens,
    }
    if config.json_mode:
        generation_config["responseMimeType"] = "application/json"
    body = json.dumps(
        {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": generation_config,
        }
    ).encode()
    request = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
        method="POST",
    )
    try:
        with urlopen(request, timeout=90) as response:
            payload = json.loads(response.read().decode())
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise AIProviderError(str(exc)) from exc
    try:
        value = "".join(
            part.get("text", "")
            for part in payload["candidates"][0]["content"]["parts"]
        ).strip()
        if not value:
            raise AIProviderError(
                f"{config.resolved_model} returned an empty text response"
            )
        return value
    except (KeyError, IndexError, TypeError) as exc:
        raise AIProviderError(f"unexpected Gemini response: {payload}") from exc


def generate_text(prompt: str, config: AIProviderConfig) -> str:
    provider = config.canonical_provider
    if provider in {"openai", "openrouter"}:
        return _generate_openai_compatible(prompt, config)
    if provider == "gemini":
        return _generate_gemini(prompt, config)
    raise AIProviderError(
        f"unsupported provider {config.provider!r}; choose openai/chatgpt, gemini, or openrouter"
    )


def generate_image_json(
    image_path: str,
    prompt: str,
    config: AIProviderConfig,
) -> dict:
    """Classify one local image with a very short multimodal JSON response."""
    if config.canonical_provider not in {"openai", "openrouter"}:
        raise AIProviderError("image classification currently uses an OpenAI-compatible API")
    try:
        from openai import OpenAI, OpenAIError
    except ImportError as exc:
        raise AIProviderError(
            'Image classification requires: pip install -e ".[llm]"'
        ) from exc
    mime = mimetypes.guess_type(image_path)[0] or "image/png"
    with open(image_path, "rb") as handle:
        encoded = base64.b64encode(handle.read()).decode("ascii")
    base_url = config.base_url
    if config.canonical_provider == "openrouter" and not base_url:
        base_url = "https://openrouter.ai/api/v1"
    try:
        client = OpenAI(api_key=_api_key(config), base_url=base_url)
        response = client.chat.completions.create(
            model=config.resolved_model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime};base64,{encoded}",
                                "detail": "low",
                            },
                        },
                    ],
                }
            ],
            temperature=0,
            max_tokens=min(60, config.max_tokens),
            response_format={"type": "json_object"},
        )
        value = (response.choices[0].message.content or "").strip()
        result = json.loads(value)
        if not isinstance(result, dict):
            raise AIProviderError("vision classifier returned a non-object")
        return result
    except (OpenAIError, OSError, json.JSONDecodeError) as exc:
        raise AIProviderError(str(exc)) from exc
