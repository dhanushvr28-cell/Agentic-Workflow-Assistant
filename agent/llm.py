"""LLM adapter for any OpenAI-compatible endpoint, returning a provider-neutral reply."""
import openai
from openai import OpenAI


class ToolCallingUnsupported(Exception):
    """The provider rejected the native tool-calling request (the agent then uses its JSON protocol)."""


class LLMClient:
    def __init__(self, base_url: str, api_key: str, model: str):
        self.model = model
        self.client = OpenAI(base_url=base_url, api_key=api_key or "missing", timeout=90, max_retries=6)

    def complete(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        """Returns {"content": str, "tool_calls": [{"id", "name", "arguments"}]}."""
        kwargs = {"tools": tools, "tool_choice": "auto"} if tools else {}
        try:
            res = self.client.chat.completions.create(model=self.model, messages=messages, temperature=0, **kwargs)
        except openai.BadRequestError as exc:
            if tools:
                raise ToolCallingUnsupported(str(exc)) from exc
            raise
        message = res.choices[0].message
        return {"content": (message.content or "").strip(),
                "tool_calls": [{"id": c.id, "name": c.function.name, "arguments": c.function.arguments}
                               for c in (message.tool_calls or [])]}
