"""The agent loop: the model picks tools, the loop executes them and feeds results back until it answers.

Two protocols are supported:
- native: the provider's function-calling API (preferred)
- json:   the model replies with a JSON object naming a tool or a final answer (fallback when the
          provider rejects a native tool call)
"""
import json
import time
from dataclasses import dataclass, field

from .llm import ToolCallingUnsupported
from .tools import TOOL_SCHEMAS, ToolError

SYSTEM_PROMPT = """You are an operations assistant for an online shop. Today's date is {today}.
Answer using the tools; never guess data, policy details or arithmetic.
- Use query_database or get_order_status for anything about customers, orders, products or tickets.
- Use search_policies for any rule, time limit, fee or eligibility question.
- Use calculate for every percentage, sum or difference.
- Only call create_ticket when the user asks for a ticket.
- If a tool returns an error, fix the call and try again.
When you have what you need, reply with a short, direct answer that states the key numbers and facts."""

JSON_PROTOCOL = """You cannot call tools directly. Reply with ONE JSON object and nothing else:
- to use a tool: {{"tool": "<name>", "arguments": {{...}}}}
- to finish:     {{"final": "<your answer to the user>"}}

Available tools:
{tools}"""


@dataclass
class AgentResult:
    answer: str
    steps: list[dict] = field(default_factory=list)
    llm_calls: int = 0
    protocol: str = "native"
    stopped: str = "answered"  # answered | max_steps
    latency_ms: int = 0

    @property
    def tools_used(self) -> list[str]:
        return [s["tool"] for s in self.steps]


def _truncate(value, limit: int = 4000) -> str:
    text = json.dumps(value, default=str)
    return text if len(text) <= limit else text[:limit] + "... [truncated]"


def _parse_json_reply(text: str) -> dict | None:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        value = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


class Agent:
    def __init__(self, llm, toolbox, max_steps: int = 8, today: str = ""):
        self.llm, self.toolbox, self.max_steps = llm, toolbox, max_steps
        self.system = SYSTEM_PROMPT.format(today=today or toolbox.today.isoformat())

    def _call_tool(self, name: str, arguments, steps: list[dict]) -> str:
        step = {"tool": name, "arguments": arguments, "error": None}
        try:
            result = self.toolbox.execute(name, arguments)
            step["result"] = result
            content = _truncate(result)
        except ToolError as exc:  # returned to the model so it can correct itself
            step["error"] = str(exc)
            content = json.dumps({"error": str(exc)})
        steps.append(step)
        return content

    def run(self, question: str, history: list[dict] | None = None) -> AgentResult:
        started = time.perf_counter()
        try:
            result = self._run_native(question, history or [])
        except ToolCallingUnsupported:
            result = self._run_json(question, history or [])
        result.latency_ms = int((time.perf_counter() - started) * 1000)
        return result

    def _run_native(self, question: str, history: list[dict]) -> AgentResult:
        messages = [{"role": "system", "content": self.system}, *history, {"role": "user", "content": question}]
        result = AgentResult(answer="", protocol="native")
        for _ in range(self.max_steps):
            reply = self.llm.complete(messages, TOOL_SCHEMAS)
            result.llm_calls += 1
            if not reply["tool_calls"]:
                result.answer = reply["content"]
                return result
            messages.append({"role": "assistant", "content": reply["content"], "tool_calls": [
                {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["arguments"]}}
                for c in reply["tool_calls"]]})
            for call in reply["tool_calls"]:
                content = self._call_tool(call["name"], call["arguments"], result.steps)
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": content})
        return self._finish_at_limit(messages, result)

    def _run_json(self, question: str, history: list[dict]) -> AgentResult:
        tools = "\n".join(f"- {t['function']['name']}({', '.join(t['function']['parameters']['properties'])}): "
                          f"{t['function']['description']}" for t in TOOL_SCHEMAS)
        messages = [{"role": "system", "content": self.system + "\n\n" + JSON_PROTOCOL.format(tools=tools)},
                    *history, {"role": "user", "content": question}]
        result = AgentResult(answer="", protocol="json")
        for _ in range(self.max_steps):
            reply = self.llm.complete(messages)
            result.llm_calls += 1
            parsed = _parse_json_reply(reply["content"])
            messages.append({"role": "assistant", "content": reply["content"]})
            if parsed and isinstance(parsed.get("final"), str):
                result.answer = parsed["final"]
                return result
            if parsed and isinstance(parsed.get("tool"), str):
                content = self._call_tool(parsed["tool"], parsed.get("arguments") or {}, result.steps)
                messages.append({"role": "user", "content": f"Tool result: {content}"})
            elif reply["content"] and not parsed:
                result.answer = reply["content"]  # plain-text answer
                return result
            else:
                messages.append({"role": "user", "content": 'Reply with JSON: {"tool": ...} or {"final": ...}.'})
        return self._finish_at_limit(messages, result)

    def _finish_at_limit(self, messages: list[dict], result: AgentResult) -> AgentResult:
        """Step budget exhausted: ask once for the best answer from what was gathered, without tools."""
        note = "Step limit reached. Give your best final answer now from the information above, in plain text."
        messages.append({"role": "user", "content": note})
        reply = self.llm.complete(messages)
        result.llm_calls += 1
        parsed = _parse_json_reply(reply["content"]) if result.protocol == "json" else None
        result.answer = (parsed or {}).get("final") or reply["content"] or "I could not complete this request."
        result.stopped = "max_steps"
        return result
