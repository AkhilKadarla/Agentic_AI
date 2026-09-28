"""FinSight as a web API, following the Amazon Bedrock AgentCore Runtime HTTP contract.

  GET  /ping         health check -> {"status": "Healthy"}
  POST /invocations  {"prompt": "...", "action": "chat" | "note" | "reset"}
                     chat  -> a stream of server-sent events (SSE), one per agent event
                     note  -> the research note for this session as JSON
                     reset -> forget this session's conversation

The agent is unchanged: this module only translates its events (TextDelta, ToolCall, ...)
into SSE, just as the CLI prints them and the Streamlit UI renders them.

Sessions: AgentCore sends a session id header and runs each session in its own isolated
micro-VM, so an in-memory agent per session keeps the conversation. Authentication
(Cognito OAuth tokens) is enforced by AgentCore before a request reaches this code, so
run it locally only on localhost:

    uv run uvicorn finsight.api:app --host 127.0.0.1 --port 8080
"""

import json
from collections.abc import Callable, Iterator
from dataclasses import asdict
from typing import Literal

import anthropic
from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from finsight import __version__, config
from finsight.agent import (
    Done,
    GuardrailBlocked,
    GuardrailReport,
    ResearchAgent,
    TextDelta,
    ToolCall,
    ToolResult,
)
from finsight.providers import AWS_CREDENTIAL_ERRORS, describe

SESSION_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"
MAX_SESSIONS = 50  # locally; on AgentCore each micro-VM holds a single session

app = FastAPI(title="FinSight", version=__version__)
_sessions: dict[str, ResearchAgent] = {}
agent_factory: Callable[[], ResearchAgent] = ResearchAgent  # tests swap in a fake


class Invocation(BaseModel):
    prompt: str = Field(default="", max_length=4000)
    action: Literal["chat", "note", "reset"] = "chat"


def session_agent(session_id: str) -> ResearchAgent:
    if session_id not in _sessions:
        if len(_sessions) >= MAX_SESSIONS:
            _sessions.pop(next(iter(_sessions)))  # drop the oldest session
        _sessions[session_id] = agent_factory()
    return _sessions[session_id]


def event_to_dict(event) -> dict:
    """One agent event as a JSON-friendly dict with a "type" field."""
    match event:
        case TextDelta(text):
            return {"type": "text", "text": text}
        case ToolCall(name, tool_input):
            return {"type": "tool_call", "name": name, "input": tool_input}
        case ToolResult(name, is_error):
            return {"type": "tool_result", "name": name, "is_error": is_error}
        case GuardrailBlocked(message, reasons):
            return {"type": "guardrail_blocked", "message": message, "reasons": reasons}
        case GuardrailReport():
            return {"type": "guardrail_report", **asdict(event)}
        case Done(text, usage, model, stop_reason):
            return {
                "type": "done",
                "text": text,
                "model": model,
                "stop_reason": stop_reason,
                "usage": asdict(usage),
                "cost_usd": usage.cost_usd(),
            }
    raise TypeError(f"unknown event: {event!r}")


def sse(events: Iterator) -> Iterator[str]:
    """Server-sent events: one `data: <json>` line per event. Errors become an event
    too, because the HTTP status (200) was already sent when streaming started."""
    try:
        for event in events:
            yield _data(event_to_dict(event))
    except anthropic.APIError as e:
        yield _data({"type": "error", "message": f"Claude API error: {e.message}"})
    except AWS_CREDENTIAL_ERRORS:
        yield _data({"type": "error", "message": "AWS credentials unavailable"})


def _data(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


@app.get("/ping")
def ping() -> dict:
    return {"status": "Healthy"}


@app.get("/info")
def info() -> dict:
    """Which provider/model this deployment runs (no secrets)."""
    return {
        "version": __version__,
        "provider": describe(),
        "guardrail": bool(config.GUARDRAIL_ID),
        "knowledge_base": bool(config.KB_ID),
    }


@app.post("/invocations")
def invocations(
    body: Invocation,
    session_id: str = Header(default="local", alias=SESSION_HEADER),
):
    agent = session_agent(session_id)
    if body.action == "reset":
        agent.reset()
        return {"status": "reset"}
    if body.action == "note":
        try:
            note, usage = agent.write_note()
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        return {"note": note.model_dump(), "cost_usd": usage.cost_usd()}
    if not body.prompt.strip():
        return JSONResponse({"error": "prompt is required"}, status_code=400)
    return StreamingResponse(sse(agent.send(body.prompt)), media_type="text/event-stream")
