"""The REST API (FastAPI).

These are the routes that are created that handle specific functionality that
the app has.

    GET  /health        -> "are you alive?"            (cloud load balancers call this constantly)
    GET  /emails        -> raw emails from the source
    GET  /internships   -> results of the most recent agent run (cached in memory)
    POST /agent/run     -> run the agent, wait, get the whole result as JSON
    POST /agent/stream  -> run the agent, get a live feed of steps (newline-delimited JSON)
    GET  /agent/graph   -> the agent's flowchart as Mermaid text
    GET  /agent/edges   -> the same flowchart as a JSON list of arrows

FastAPI also builds an interactive docs page at /docs where you can try every endpoint.
"""

import json

from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse, StreamingResponse

from app import config
from app.agent.tool_graph import graph_edges, graph_mermaid, run_agent, stream_agent
from app.models import Email, RunResult
from app.sources import fetch_emails

app = FastAPI(
    title="Internship Agent API",
    description="A small LangGraph agent that finds internship updates in your email.",
    version="1.0.0",
)

# In-memory storage: simple, but it resets when the server restarts and is NOT shared between
# multiple server copies. Real cloud apps put this in a database (Postgres, DynamoDB, ...).
_last_result: RunResult | None = None


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "mode": config.llm_mode(), "source": config.EMAIL_SOURCE}


@app.get("/emails", response_model=list[Email])
def list_emails() -> list[Email]:
    try:
        return fetch_emails()
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Could not fetch emails: {exc}"
        ) from exc


@app.get("/internships", response_model=RunResult)
def last_internships() -> RunResult:
    if _last_result is None:
        raise HTTPException(
            status_code=404, detail="The agent has not run yet. POST /agent/run first."
        )
    return _last_result


@app.post("/agent/run", response_model=RunResult)
def agent_run() -> RunResult:
    global _last_result
    try:
        _last_result = run_agent()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Agent failed: {exc}") from exc
    return _last_result


@app.post("/agent/stream")
def agent_stream() -> StreamingResponse:
    def events():
        global _last_result
        try:
            for event in stream_agent(step_delay=config.DEMO_STEP_DELAY):
                if event["type"] == "result":
                    _last_result = RunResult(**event["data"])
                yield json.dumps(event) + "\n"
        except Exception as exc:
            yield json.dumps(
                {"type": "error", "message": f"{type(exc).__name__}: {exc}"}
            ) + "\n"

    return StreamingResponse(events(), media_type="application/x-ndjson")


@app.get("/agent/graph", response_class=PlainTextResponse)
def agent_graph() -> str:
    return graph_mermaid()


@app.get("/agent/edges")
def agent_edges() -> list[dict]:
    return graph_edges()
