"""Provider-neutral LLM client wrappers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal, Protocol


ProviderName = Literal["anthropic", "openai", "groq", "gemini"]

DEFAULT_PROVIDER: ProviderName = "anthropic"
DEFAULT_MODELS: dict[ProviderName, str] = {
    "anthropic": "claude-haiku-4-5-20251001",
    "openai": "gpt-5.4-mini",
    "groq": "llama-3.3-70b-versatile",
    "gemini": "gemini-2.5-flash",
}


@dataclass(frozen=True)
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int
    model: str

    @property
    def tokens_used(self) -> int:
        return self.input_tokens + self.output_tokens


class LLMClient(Protocol):
    model: str

    def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float | None = None,
    ) -> LLMResponse:
        ...


class AnthropicLLM:
    def __init__(self, client: Any, model: str) -> None:
        self.client = client
        self.model = model

    def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float | None = None,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature

        response = self.client.messages.create(**kwargs)
        return LLMResponse(
            text=response.content[0].text.strip(),
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=self.model,
        )


class OpenAIChatLLM:
    def __init__(
        self,
        client: Any,
        model: str,
        *,
        token_limit_parameter: str = "max_completion_tokens",
    ) -> None:
        self.client = client
        self.model = model
        self.token_limit_parameter = token_limit_parameter

    def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float | None = None,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *messages],
            self.token_limit_parameter: max_tokens,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature

        response = self.client.chat.completions.create(**kwargs)
        usage = response.usage
        return LLMResponse(
            text=(response.choices[0].message.content or "").strip(),
            input_tokens=usage.prompt_tokens if usage is not None else 0,
            output_tokens=usage.completion_tokens if usage is not None else 0,
            model=self.model,
        )


def resolve_model(provider: ProviderName, model: str | None = None) -> str:
    if provider not in DEFAULT_MODELS:
        raise ValueError(f"Unsupported provider: {provider}")
    return model or DEFAULT_MODELS[provider]


def create_llm_client(provider: ProviderName = DEFAULT_PROVIDER, model: str | None = None) -> LLMClient:
    resolved_model = resolve_model(provider, model)

    if provider == "anthropic":
        import anthropic

        return AnthropicLLM(anthropic.Anthropic(), resolved_model)

    if provider == "openai":
        from openai import OpenAI

        return OpenAIChatLLM(OpenAI(api_key=os.getenv("OPENAI_API_KEY")), resolved_model)

    if provider == "groq":
        from openai import OpenAI

        return OpenAIChatLLM(
            OpenAI(api_key=os.getenv("GROQ_API_KEY"), base_url="https://api.groq.com/openai/v1"),
            resolved_model,
            token_limit_parameter="max_tokens",
        )

    if provider == "gemini":
        from openai import OpenAI

        return OpenAIChatLLM(
            OpenAI(
                api_key=os.getenv("GEMINI_API_KEY"),
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            ),
            resolved_model,
        )

    raise ValueError(f"Unsupported provider: {provider}")
