"""Model providers for the editing agent.

Frameflow is Claude-native by default but not Claude-only: anyone cloning the
repo brings their own key for whichever provider they use. Each provider runs
the same contract - get a plan submitted through one tool, validate it with
our own code, feed errors back, repeat - in its own native tool-calling API.
The loop is duplicated per provider on purpose: message and tool-result
formats differ enough that a shared conversation abstraction would leak.

Configuration (flags override environment):
    FRAMEFLOW_PROVIDER   anthropic (default) | openai
    FRAMEFLOW_MODEL      model id; defaults to claude-opus-5 for anthropic,
                         required for openai since model names vary by endpoint
    FRAMEFLOW_BASE_URL   openai only: any OpenAI-compatible endpoint
                         (OpenRouter, Ollama, LM Studio, a gateway, ...)

Credentials are read by each provider's own SDK: ANTHROPIC_API_KEY for
anthropic, OPENAI_API_KEY for openai (set it to the endpoint's key, or any
placeholder for local servers that do not check one).
"""
import os
from dataclasses import dataclass
from typing import Callable, Protocol


class ProviderError(Exception):
    pass


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict


# Returns a list of human-readable problems; empty means the input is accepted.
Checker = Callable[[dict], list[str]]


class Provider(Protocol):
    name: str
    model: str

    def submit(self, system: str, user: str, tool: ToolSpec, check: Checker,
               max_attempts: int) -> dict:
        """Run the tool-calling loop until `check` accepts a submission."""
        ...


PROVIDERS = ("anthropic", "openai")


def get_provider(provider: str | None = None, model: str | None = None,
                 base_url: str | None = None) -> Provider:
    name = (provider or os.environ.get("FRAMEFLOW_PROVIDER") or "anthropic").lower()
    model = model or os.environ.get("FRAMEFLOW_MODEL")
    base_url = base_url or os.environ.get("FRAMEFLOW_BASE_URL")

    if name == "anthropic":
        from project.providers.anthropic_provider import AnthropicProvider
        return AnthropicProvider(model=model)
    if name == "openai":
        from project.providers.openai_provider import OpenAICompatibleProvider
        return OpenAICompatibleProvider(model=model, base_url=base_url)
    raise ProviderError(f"unknown provider {name!r}; choose one of: {', '.join(PROVIDERS)}")
