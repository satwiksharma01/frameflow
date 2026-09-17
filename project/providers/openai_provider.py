"""Any OpenAI-compatible chat completions endpoint.

Uses Chat Completions rather than the newer Responses API deliberately: it is
the surface OpenAI-compatible servers (OpenRouter, Ollama, LM Studio, vLLM,
most gateways) actually implement, so one adapter reaches all of them.
"""
import json

from project.providers import Checker, ProviderError, ToolSpec


class OpenAICompatibleProvider:
    name = "openai"

    def __init__(self, model: str | None = None, base_url: str | None = None, client=None):
        if not model:
            raise ProviderError(
                "the openai provider needs a model: pass --model or set FRAMEFLOW_MODEL "
                "(names differ between OpenAI, OpenRouter, Ollama and other endpoints)"
            )
        self.model = model
        if client is None:
            from openai import OpenAI
            client = OpenAI(base_url=base_url) if base_url else OpenAI()
        self.client = client
        self.served_by = None

    def submit(self, system: str, user: str, tool: ToolSpec, check: Checker,
               max_attempts: int = 4) -> dict:
        tools = [{
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            },
        }]
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        for _ in range(max_attempts):
            completion = self.client.chat.completions.create(
                model=self.model, messages=messages, tools=tools,
            )
            self.served_by = completion.model
            choice = completion.choices[0]
            if choice.finish_reason == "length":
                raise ProviderError("response hit the output limit before the plan was complete")
            if choice.finish_reason == "content_filter":
                raise ProviderError(f"{completion.model} declined the request (content filter)")

            message = choice.message
            calls = [c for c in (message.tool_calls or [])
                     if c.type == "function" and c.function.name == tool.name]

            # Rebuilt by hand rather than dumping the SDK object: compatible
            # servers often reject fields only OpenAI itself understands.
            assistant = {"role": "assistant", "content": message.content or ""}
            if message.tool_calls:
                assistant["tool_calls"] = [
                    {"id": c.id, "type": "function",
                     "function": {"name": c.function.name, "arguments": c.function.arguments}}
                    for c in message.tool_calls if c.type == "function"
                ]
            messages.append(assistant)

            if not calls:
                messages.append({"role": "user", "content": f"Submit the plan by calling {tool.name}."})
                continue

            for call in calls:
                try:
                    submission = json.loads(call.function.arguments)
                except json.JSONDecodeError as e:
                    problems = [f"arguments were not valid JSON: {e}"]
                else:
                    problems = check(submission) if isinstance(submission, dict) else [
                        "arguments must be a JSON object"
                    ]
                if not problems:
                    return submission
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps({"errors": problems}),
                })

        raise ProviderError(f"{self.model} did not produce a valid submission in {max_attempts} attempts")
