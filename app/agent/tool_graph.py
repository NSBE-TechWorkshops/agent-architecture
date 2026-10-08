"""A true LangGraph tool-calling agent.

This graph is intentionally small:

    START -> agent -> tools -> agent -> END

The LLM in the `agent` node decides which tool to call. LangGraph only manages
the loop and hands tool results back to the model.
"""

import json
import time
from collections.abc import Iterator
from functools import lru_cache
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import START, StateGraph
from langgraph.graph.message import MessagesState
from langgraph.prebuilt import ToolNode, tools_condition

from app import config
from app.agent.tools import tools
from app.models import Internship, RunResult

# System prompt
AGENT_SYSTEM = """You are an internship email assistant for college students.

Your job:
1. Fetch emails.
2. Find internship-related messages.
3. Classify them.
4. Rank them by urgency and deadline.
5. Produce a short friendly digest.

Use tools when you need data or computation.
Do not invent emails, companies, deadlines, or action items.
After ranking internships, write the final digest in plain text and do not call more tools.
"""

USER_TASK = (
    "Read my emails, find internship-related messages, classify them, "
    "rank them by urgency and deadline, and write a short friendly digest."
)


@lru_cache(maxsize=1)
def get_llm():
    """Build the OpenAI chat model once. Returns None when there is no API key."""
    if not config.OPENAI_API_KEY:
        return None
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=config.OPENAI_MODEL, temperature=0, timeout=30, max_retries=2
    )


# function to call the model
def call_model(state: MessagesState) -> dict:
    """Ask the model what to do next: call a tool or produce the final answer."""
    llm = get_llm()
    if llm is None:
        raise RuntimeError(
            "Tool-calling mode requires OPENAI_API_KEY. Set one in .env to let "
            "the LLM choose tools."
        )

    model = llm.bind_tools(tools)
    response = model.invoke([SystemMessage(content=AGENT_SYSTEM), *state["messages"]])
    return {"messages": [response]}


def build_graph():
    g = StateGraph(MessagesState)
    g.add_node("agent", call_model)
    g.add_node("tools", ToolNode(tools))
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", tools_condition)
    g.add_edge("tools", "agent")
    return g.compile()


graph = build_graph()


def graph_mermaid() -> str:
    """The graph as a Mermaid diagram. Paste it into https://mermaid.live."""
    return graph.get_graph().draw_mermaid()


def graph_edges() -> list[dict]:
    """The graph's arrows as simple JSON for the TUI."""
    edges = graph.get_graph().edges
    ordered, queue, seen = [], ["__start__"], set()
    while queue:
        node = queue.pop(0)
        if node in seen:
            continue
        seen.add(node)
        for edge in edges:
            if edge.source == node:
                ordered.append(
                    {
                        "from": edge.source,
                        "to": edge.target,
                        "conditional": bool(edge.conditional),
                    }
                )
                queue.append(edge.target)
    return ordered


def _message_text(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    return json.dumps(content)


def _tool_name(message: ToolMessage, pending_tool_names: dict[str, str]) -> str:
    name = getattr(message, "name", None)
    if name:
        return str(name)
    return pending_tool_names.get(message.tool_call_id, "unknown_tool")


def _parse_tool_payload(message: ToolMessage) -> Any:
    content = message.content
    if not isinstance(content, str):
        return content
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return content


def _update_result_state(
    tool_name: str,
    payload: Any,
    result_state: dict[str, Any],
) -> None:
    if tool_name == "fetch_emails_tool" and isinstance(payload, list):
        result_state["emails_scanned"] = len(payload)
    elif tool_name == "rank_internships_tool" and isinstance(payload, list):
        result_state["internships"] = [Internship(**item) for item in payload]


def _run_result(
    summary: str, trace: list[str], result_state: dict[str, Any]
) -> RunResult:
    return RunResult(
        mode=config.llm_mode(),
        source=config.EMAIL_SOURCE,
        emails_scanned=result_state.get("emails_scanned", 0),
        internships=result_state.get("internships", []),
        summary=summary,
        trace=trace,
    )


def stream_agent(step_delay: float = 0.0) -> Iterator[dict]:
    """Run the tool-calling graph and yield one event per completed graph node."""
    input_state = {"messages": [HumanMessage(content=USER_TASK)]}
    trace: list[str] = []
    result_state: dict[str, Any] = {"emails_scanned": 0, "internships": []}
    pending_tool_names: dict[str, str] = {}
    final_summary = ""

    for chunk in graph.stream(
        input_state, stream_mode="updates", config={"recursion_limit": 40}
    ):
        for node, update in chunk.items():
            messages = (update or {}).get("messages", [])
            lines: list[str] = []

            if node == "agent":
                for message in messages:
                    if isinstance(message, AIMessage) and message.tool_calls:
                        for tool_call in message.tool_calls:
                            pending_tool_names[tool_call["id"]] = tool_call["name"]
                            lines.append(f"agent: requested {tool_call['name']}")
                    else:
                        final_summary = _message_text(message)
                        lines.append("agent: wrote final digest")

            elif node == "tools":
                for message in messages:
                    if isinstance(message, ToolMessage):
                        name = _tool_name(message, pending_tool_names)
                        payload = _parse_tool_payload(message)
                        _update_result_state(name, payload, result_state)
                        lines.append(f"tools: ran {name}")
                    else:
                        lines.append("tools: ran requested tool")

            else:
                lines.append(f"{node}: completed")

            trace.extend(lines)
            yield {"type": "step", "node": node, "messages": lines}
            if step_delay:
                time.sleep(step_delay)

    result = _run_result(final_summary, trace, result_state)
    yield {"type": "result", "data": result.model_dump()}


def run_agent() -> RunResult:
    """Run to completion and return only the final result."""
    final = None
    for event in stream_agent():
        if event["type"] == "result":
            final = event["data"]
    return RunResult(**final)
