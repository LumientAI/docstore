from __future__ import annotations

from types import SimpleNamespace

from docstore.llm import AnthropicLLM, OpenAIChatLLM, create_llm_client


class FakeAnthropicMessages:
    def __init__(self) -> None:
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            content=[SimpleNamespace(text='{"ok": true}')],
            usage=SimpleNamespace(input_tokens=11, output_tokens=7),
        )


class FakeAnthropicClient:
    def __init__(self) -> None:
        self.messages = FakeAnthropicMessages()


class FakeChatCompletions:
    def __init__(self) -> None:
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))],
            usage=SimpleNamespace(prompt_tokens=13, completion_tokens=5),
        )


class FakeOpenAIClient:
    def __init__(self) -> None:
        self.chat = SimpleNamespace(completions=FakeChatCompletions())


def test_anthropic_llm_normalizes_response():
    raw_client = FakeAnthropicClient()
    client = AnthropicLLM(raw_client, "claude-test")

    result = client.complete(
        system="system",
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=123,
        temperature=0,
    )

    assert result.text == '{"ok": true}'
    assert result.input_tokens == 11
    assert result.output_tokens == 7
    assert result.tokens_used == 18
    assert raw_client.messages.kwargs == {
        "model": "claude-test",
        "max_tokens": 123,
        "system": "system",
        "messages": [{"role": "user", "content": "hello"}],
        "temperature": 0,
    }


def test_openai_llm_normalizes_response():
    raw_client = FakeOpenAIClient()
    client = OpenAIChatLLM(raw_client, "gpt-test")

    result = client.complete(
        system="system",
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=456,
    )

    assert result.text == '{"ok": true}'
    assert result.input_tokens == 13
    assert result.output_tokens == 5
    assert result.tokens_used == 18
    assert raw_client.chat.completions.kwargs == {
        "model": "gpt-test",
        "messages": [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "hello"},
        ],
        "max_completion_tokens": 456,
    }


def test_groq_uses_openai_compatible_client(monkeypatch):
    calls = []

    def fake_openai(**kwargs):
        calls.append(kwargs)
        return FakeOpenAIClient()

    import openai

    monkeypatch.setattr(openai, "OpenAI", fake_openai)
    monkeypatch.setenv("GROQ_API_KEY", "groq-test-key")

    client = create_llm_client("groq")

    assert isinstance(client, OpenAIChatLLM)
    assert client.model == "llama-3.3-70b-versatile"
    assert client.token_limit_parameter == "max_tokens"
    assert calls == [
        {"api_key": "groq-test-key", "base_url": "https://api.groq.com/openai/v1"}
    ]


def test_gemini_uses_openai_compatible_client(monkeypatch):
    calls = []

    def fake_openai(**kwargs):
        calls.append(kwargs)
        return FakeOpenAIClient()

    import openai

    monkeypatch.setattr(openai, "OpenAI", fake_openai)
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")

    client = create_llm_client("gemini")

    assert isinstance(client, OpenAIChatLLM)
    assert client.model == "gemini-2.5-flash"
    assert client.token_limit_parameter == "max_completion_tokens"
    assert calls == [
        {
            "api_key": "gemini-test-key",
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        }
    ]
