import hashlib
import json
import re

import numpy as np
import pytest

from agent.core import Agent
from agent.seed import seed
from agent.tools import KnowledgeBase, Toolbox

TODAY = "2026-11-01"


class FakeEmbedder:
    """Deterministic bag-of-words hashing embedder: no model download needed."""

    def embed(self, texts):
        out = np.zeros((len(texts), 512))
        for i, text in enumerate(texts):
            for tok in re.findall(r"[a-z0-9]+", text.lower()):
                out[i, int(hashlib.md5(tok.encode()).hexdigest(), 16) % 512] += 1
            out[i] /= np.linalg.norm(out[i]) or 1
        return out


class ScriptedLLM:
    """Replays a list of replies. A reply is a final string, or a list of (tool, arguments) calls."""

    def __init__(self, script):
        self.script, self.requests = list(script), []

    def complete(self, messages, tools=None):
        self.requests.append({"messages": [dict(m) for m in messages], "tools": tools})
        reply = self.script.pop(0)
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, str):
            return {"content": reply, "tool_calls": []}
        return {"content": "", "tool_calls": [
            {"id": f"call_{len(self.requests)}_{i}", "name": name,
             "arguments": args if isinstance(args, str) else json.dumps(args)}
            for i, (name, args) in enumerate(reply)]}


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "shop.db")
    seed(path, TODAY)
    return path


@pytest.fixture
def toolbox(db_path):
    return Toolbox(db_path, KnowledgeBase(FakeEmbedder()), TODAY)


@pytest.fixture
def make_agent(toolbox):
    def _make(script, max_steps=6):
        llm = ScriptedLLM(script)
        return Agent(llm, toolbox, max_steps), llm
    return _make
