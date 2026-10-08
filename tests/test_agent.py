"""Tests run in mock mode (no keys, no network)."""

import json

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, ToolMessage

from app.agent import tool_graph as agent_graph
from app.agent.tools import (
    classify_email_tool,
    fetch_emails_tool,
    filter_internship_candidates_tool,
    rank_internships_tool,
)
from app.main import app

client = TestClient(app)


def _payload(message: ToolMessage):
    return json.loads(message.content)


class FakeToolCallingLLM:
    """Small deterministic model that demonstrates the same tool-calling loop offline."""

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        tool_messages = [message for message in messages if isinstance(message, ToolMessage)]
        tool_names = [getattr(message, "name", None) for message in tool_messages]

        if not tool_messages:
            return AIMessage(
                content="",
                tool_calls=[{"name": "fetch_emails_tool", "args": {}, "id": "call_fetch"}],
            )

        if tool_names[-1] == "fetch_emails_tool":
            emails = _payload(tool_messages[-1])
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "filter_internship_candidates_tool",
                        "args": {"emails": emails},
                        "id": "call_filter",
                    }
                ],
            )

        if tool_names[-1] == "filter_internship_candidates_tool":
            candidates = _payload(tool_messages[-1])
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "classify_email_tool",
                        "args": {"email": email},
                        "id": f"call_classify_{index}",
                    }
                    for index, email in enumerate(candidates)
                ],
            )

        if "classify_email_tool" in tool_names and "rank_internships_tool" not in tool_names:
            classified = [
                _payload(message)
                for message in tool_messages
                if getattr(message, "name", None) == "classify_email_tool"
            ]
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "rank_internships_tool",
                        "args": {"internships": classified},
                        "id": "call_rank",
                    }
                ],
            )

        ranked = _payload(tool_messages[-1])
        top = ranked[0]["company"] if ranked else "no companies"
        return AIMessage(content=f"Top priority: {top}. Review the ranked internship emails.")


def test_tools_find_and_rank_internships():
    emails = fetch_emails_tool.invoke({})
    candidates = filter_internship_candidates_tool.invoke({"emails": emails})
    classified = [classify_email_tool.invoke({"email": email}) for email in candidates]
    ranked = rank_internships_tool.invoke({"internships": classified})

    assert len(emails) == 12
    companies = [item["company"] for item in ranked]
    assert "Contoso Cloud" in companies
    assert "Pizza Palace" not in companies
    urgencies = [item["urgency"] for item in ranked]
    assert urgencies == sorted(urgencies, key=["high", "medium", "low"].index)


def test_tool_calling_graph_with_fake_model(monkeypatch):
    monkeypatch.setattr(agent_graph, "get_llm", lambda: FakeToolCallingLLM())
    result = agent_graph.run_agent()

    assert result.emails_scanned == 12
    assert len(result.internships) > 0
    assert result.summary.startswith("Top priority:")
    assert any("agent: requested fetch_emails_tool" in line for line in result.trace)
    assert any("tools: ran rank_internships_tool" in line for line in result.trace)


def test_api_endpoints(monkeypatch):
    monkeypatch.setattr(agent_graph, "get_llm", lambda: FakeToolCallingLLM())

    assert client.get("/health").json()["status"] == "ok"
    assert len(client.get("/emails").json()) == 12
    assert client.post("/agent/run").status_code == 200
    assert len(client.get("/internships").json()["internships"]) > 0
    graph_text = client.get("/agent/graph").text
    assert "graph TD" in graph_text
    assert "agent" in graph_text
    assert "tools" in graph_text


def test_stream_endpoint_emits_steps_then_result(monkeypatch):
    monkeypatch.setattr(agent_graph, "get_llm", lambda: FakeToolCallingLLM())

    with client.stream("POST", "/agent/stream") as resp:
        lines = [line for line in resp.iter_lines() if line]
    assert '"type": "step"' in lines[0]
    assert '"type": "result"' in lines[-1]


def test_graph_edges_start_at_start_and_end_at_end():
    edges = client.get("/agent/edges").json()
    assert edges[0]["from"] == "__start__"
    assert any(edge["to"] == "__end__" for edge in edges)
    assert any(edge["conditional"] for edge in edges)
