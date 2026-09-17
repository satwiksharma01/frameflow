"""Claude via the official Anthropic SDK."""
import json

from project.providers import Checker, ProviderError, ToolSpec

DEFAULT_MODEL = "claude-opus-5"

# Streaming with a generous ceiling: long recordings mean long transcripts in
# and long plans out, and non-streaming requests at this size hit HTTP timeouts.
MAX_TOKENS = 64000

# Models whose safety classifiers can decline a request. For these, ask the API
# to re-run a declined request on its recommended fallback model instead of
# returning the refusal. Other models reject the parameter.
_FALLBACK_MODELS = {"claude-opus-5", "claude-fable-5-1"}
_FALLBACK_BETA = "server-side-fallback-2026-07-01"

_PRE_BOUNDARY_DROP = {"thinking", "redacted_thinking", "tool_use"}


def _echoable(content: list) -> list:
    """Content that is safe to send back after a mid-output fallback.

    If a fallback happened partway through a response, the declined model's
    thinking and tool_use blocks before the last `fallback` block must not be
    echoed; everything after the boundary belongs to the model that accepted.
    """
    boundaries = [i for i, block in enumerate(content) if block.type == "fallback"]
    if not boundaries:
        return list(content)
    last = boundaries[-1]
    return [b for i, b in enumerate(content) if i > last or b.type not in _PRE_BOUNDARY_DROP]


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model: str | None = None, client=None):
        self.model = model or DEFAULT_MODEL
        if client is None:
            import anthropic
            client = anthropic.Anthropic()
        self.client = client
        self.served_by = None

    def submit(self, system: str, user: str, tool: ToolSpec, check: Checker,
               max_attempts: int = 4) -> dict:
        tool_def = {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_schema,
            # Tool input arrives as it is generated rather than buffered, so
            # the server no longer validates it - `check` is the validator.
            "eager_input_streaming": True,
        }
        request = {
            "model": self.model,
            "max_tokens": MAX_TOKENS,
            "system": system,
            "tools": [tool_def],
        }
        if self.model in _FALLBACK_MODELS:
            request["betas"] = [_FALLBACK_BETA]
            request["fallbacks"] = "default"

        messages = [{"role": "user", "content": user}]
        for _ in range(max_attempts):
            try:
                with self.client.beta.messages.stream(messages=messages, **request) as stream:
                    response = stream.get_final_message()
            except ValueError:
                # The SDK could not parse the streamed tool input at all. There
                # is no tool_use id to answer, so re-issue the same request.
                continue

            self.served_by = response.model
            if response.stop_reason == "refusal":
                category = getattr(response.stop_details, "category", None)
                raise ProviderError(f"{response.model} declined the request (category: {category})")
            if response.stop_reason == "max_tokens":
                raise ProviderError(
                    f"response hit the {MAX_TOKENS}-token limit before the plan was complete; "
                    f"the recording may be too long for a single pass"
                )

            content = _echoable(response.content)
            messages.append({"role": "assistant", "content": content})
            calls = [b for b in content if b.type == "tool_use" and b.name == tool.name]
            if not calls:
                messages.append({"role": "user", "content": f"Submit the plan by calling {tool.name}."})
                continue

            results = []
            for call in calls:
                problems = check(call.input)
                if not problems:
                    return call.input
                results.append({
                    "type": "tool_result",
                    "tool_use_id": call.id,
                    "is_error": True,
                    "content": json.dumps({"errors": problems}),
                })
            messages.append({"role": "user", "content": results})

        raise ProviderError(f"{self.model} did not produce a valid submission in {max_attempts} attempts")
