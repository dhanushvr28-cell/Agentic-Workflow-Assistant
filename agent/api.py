"""REST API for the agent: chat with memory, and inspect the tool trace of every answer."""
import logging
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .config import Settings, get_settings
from .core import Agent
from .store import Store

log = logging.getLogger("agent")


class ChatRequest(BaseModel):
    message: str = Field(min_length=2, max_length=2000)
    session_id: int | None = None


def build_agent(settings: Settings) -> Agent:
    from .llm import LLMClient
    from .seed import seed
    from .tools import KnowledgeBase, SentenceTransformerEmbedder, Toolbox

    if not os.path.exists(settings.db_path):
        seed(settings.db_path, settings.reference_date)
    kb = KnowledgeBase(SentenceTransformerEmbedder(settings.embedding_model))
    toolbox = Toolbox(settings.db_path, kb, settings.reference_date)
    return Agent(LLMClient(settings.llm_base_url, settings.llm_api_key, settings.llm_model), toolbox,
                 settings.max_steps)


def create_app(settings: Settings | None = None, agent: Agent | None = None, store: Store | None = None) -> FastAPI:
    settings = settings or get_settings()
    agent = agent or build_agent(settings)
    store = store or Store(os.path.join(os.path.dirname(os.path.abspath(settings.db_path)), "sessions.db"))
    app = FastAPI(title="Agentic Workflow Assistant", version="1.0.0")

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        log.exception("Unhandled error on %s", request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    @app.get("/health")
    def health():
        return {"status": "ok", "max_steps": agent.max_steps}

    @app.post("/chat")
    def chat(body: ChatRequest):
        if not body.message.strip():
            raise HTTPException(422, "message must not be blank.")
        if body.session_id is not None and not store.exists(body.session_id):
            raise HTTPException(404, "Session not found.")
        session_id = body.session_id or store.new_session()
        try:
            result = agent.run(body.message.strip(), store.history(session_id))
        except Exception as exc:
            log.error("Agent run failed: %s", exc)
            raise HTTPException(502, "The language model request failed. Check LLM_API_KEY and LLM_MODEL.")
        store.add_turn(session_id, body.message.strip(), result)
        return {"session_id": session_id, "answer": result.answer, "tools_used": result.tools_used,
                "steps": result.steps, "llm_calls": result.llm_calls, "protocol": result.protocol,
                "stopped": result.stopped, "latency_ms": result.latency_ms}

    @app.get("/sessions/{session_id}")
    def get_session(session_id: int):
        if not store.exists(session_id):
            raise HTTPException(404, "Session not found.")
        return {"session_id": session_id, "turns": store.turns(session_id)}

    return app


def __getattr__(name: str):
    if name == "app":  # built lazily for `uvicorn agent.api:app`
        globals()["app"] = create_app()
        return globals()["app"]
    raise AttributeError(name)
