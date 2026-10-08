"""The agent, written as a LangGraph workflow.

Think of a LangGraph graph as a flowchart that your code actually runs:

    START -> fetch_emails -> filter_candidates --(any candidates?)--> classify -> rank -> summarize -> END
                                    |
                                    +--(none)--> END

* STATE   : one shared dictionary that flows through the graph (AgentState below).
* NODES   : plain Python functions. Each reads the state and returns the keys it wants to update.
* EDGES   : arrows saying which node runs next. A *conditional* edge picks the next node at runtime.

Only two nodes (classify, summarize) talk to an LLM. The rest is ordinary code, which is how
most real agents are built: use the LLM where judgment is needed, use code everywhere else.
"""

import operator
import time
from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from app import config
from app.agent import heuristic
from app.models import Email, EmailClassification, Internship, RunResult
from app.sources import fetch_emails as load_emails

URGENCY_ORDER = {
    "high": 0,
    "medium": 1,
    "low": 2,
}  # urgency level of what email that I should respond to

# system classifier prompt, helps w/ classifing the emails that get recieved
CLASSIFY_SYSTEM = (
    "You help college students track internship-related email. "
    "Read the email and fill in the requested fields. "
    "Marketing, receipts, class announcements and other unrelated mail is NOT internship related. "
    "Express any deadline as YYYY-MM-DD. Judge urgency relative to the date the email was received."
)

# system summary prompt, telling the agent how to structure the output it gives
SUMMARY_SYSTEM = (
    "You write a short, friendly internship digest for a college student. "
    "Start with the single most urgent thing, then list the rest in priority order as short bullets. "
    "Use plain text and at most 120 words. Do not invent anything that is not in the data."
)


# --------------------------------------------------------------------------- state
"""
AgentState stores the agent memory (normally i'd use a DB even SQLite but just
wanted to show this as a demo for now.
"""


class AgentState(TypedDict, total=False):
    emails: list[Email]  # everything we fetched
    candidates: list[Email]  # emails that passed the cheap keyword filter
    classified: list[Internship]  # candidates after classification
    internships: list[Internship]  # final, ranked list
    summary: str
    # Annotated[..., operator.add] is a "reducer": when two updates arrive, LangGraph joins them
    # with + instead of overwriting. That is how every node can append lines to the trace.
    trace: Annotated[list[str], operator.add]


# --------------------------------------------------------------------------- LLM
@lru_cache(maxsize=1)
def get_llm():
    """Build the OpenAI chat model once. Returns None when there is no API key."""
    if not config.OPENAI_API_KEY:
        return None
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=config.OPENAI_MODEL, temperature=0, timeout=30, max_retries=2
    )


def _email_prompt(email: Email) -> str:
    return f"Received: {email.date}\nFrom: {email.sender}\nSubject: {email.subject}\n\n{email.body[:2000]}"


def _to_internship(email: Email, result: EmailClassification) -> Internship:
    return Internship(
        **result.model_dump(),
        email_id=email.id,
        sender=email.sender,
        subject=email.subject,
        date=email.date,
    )


# --------------------------------------------------------------------------- nodes
# function to get email from email
def fetch_emails(state: AgentState) -> dict:
    emails = load_emails()
    return {
        "emails": emails,
        "trace": [
            f"fetch_emails: pulled {len(emails)} emails from source '{config.EMAIL_SOURCE}'"
        ],
    }


# filter the emails into category if email cannot be categorized
def filter_candidates(state: AgentState) -> dict:
    """Cheap pre-filter in plain code, so we only pay the LLM for emails that might matter."""
    candidates = [e for e in state["emails"] if heuristic.looks_internship_related(e)]
    skipped = len(state["emails"]) - len(candidates)
    update: dict = {
        "candidates": candidates,
        "trace": [
            f"filter_candidates: {len(candidates)} look internship-related, {skipped} skipped (no LLM cost)"
        ],
    }
    if not candidates:
        update["internships"] = []
        update["summary"] = "No internship-related emails found."
    return update


def route_after_filter(state: AgentState) -> str:
    """The conditional edge: a normal function that returns the NAME of the next step."""
    return "classify" if state["candidates"] else "done"


def classify(state: AgentState) -> dict:
    candidates = state["candidates"]
    llm = get_llm()
    trace: list[str] = []
    results: list[EmailClassification | None]

    if llm is None:
        trace.append(
            f"classify: no OPENAI_API_KEY, using keyword rules on {len(candidates)} emails"
        )
        results = [heuristic.classify(e) for e in candidates]
    else:
        trace.append(
            f"classify: asking {config.OPENAI_MODEL} to read {len(candidates)} emails"
        )
        # with_structured_output forces the model to answer in the shape of EmailClassification.
        structured = llm.with_structured_output(EmailClassification)
        prompts = [
            [("system", CLASSIFY_SYSTEM), ("human", _email_prompt(e))]
            for e in candidates
        ]
        raw = structured.batch(
            prompts, config={"max_concurrency": 5}, return_exceptions=True
        )
        results = []
        failures = 0
        for email, item in zip(candidates, raw):
            if isinstance(item, EmailClassification):
                results.append(item)
            else:  # network error, bad output, etc: fall back instead of crashing the whole run
                failures += 1
                results.append(heuristic.classify(email))
        if failures:
            trace.append(
                f"classify: {failures} email(s) failed, used keyword rules for those"
            )

    classified = [_to_internship(e, r) for e, r in zip(candidates, results)]
    return {"classified": classified, "trace": trace}


def rank(state: AgentState) -> dict:
    """Plain code: drop unrelated emails, then sort by urgency and deadline."""
    related = [i for i in state["classified"] if i.is_internship_related]
    related.sort(key=lambda i: (URGENCY_ORDER[i.urgency], i.deadline or "9999-99-99"))
    dropped = len(state["classified"]) - len(related)
    return {
        "internships": related,
        "trace": [
            f"rank: kept {len(related)}, dropped {dropped} false positive(s), sorted by urgency"
        ],
    }


def _template_summary(items: list[Internship]) -> str:
    if not items:
        return "No internship-related emails found."
    lines = [f"You have {len(items)} internship-related emails. Top priorities:"]
    for i in items[:4]:
        due = f" (by {i.deadline})" if i.deadline else ""
        lines.append(f"- {i.company}, {i.role}{due}: {i.action_needed}")
    return "\n".join(lines)


"""function to call the agent to summarize the findings (I made sure that there 
was an alternate summary so that you guys could still understand the concept of an llm
being called)"""


def summarize(state: AgentState) -> dict:
    items = state["internships"]
    llm = get_llm()
    # conditional to handle if there is no llm
    if llm is None or not items:
        return {
            "summary": _template_summary(items),
            "trace": ["summarize: built digest from a template"],
        }
    # otherwise call the actual llm
    try:
        data = "\n".join(
            f"- {i.company} | {i.role} | {i.category} | deadline {i.deadline} | urgency {i.urgency} | {i.action_needed}"
            for i in items
        )
        reply = llm.invoke([("system", SUMMARY_SYSTEM), ("human", data)])
        return {
            "summary": str(reply.content),
            "trace": [f"summarize: {config.OPENAI_MODEL} wrote the digest"],
        }
    except Exception as exc:  # keep the demo alive if the API hiccups
        return {
            "summary": _template_summary(items),
            "trace": [
                f"summarize: LLM call failed ({type(exc).__name__}), used template instead"
            ],
        }


# --------------------------------------------------------------------------- wiring
# function to show you guys the flow in a graph, so you understand the flow of the agents thinking
def build_graph():
    g = StateGraph(AgentState)
    g.add_node("fetch_emails", fetch_emails)
    g.add_node("filter_candidates", filter_candidates)
    g.add_node("classify", classify)
    g.add_node("rank", rank)
    g.add_node("summarize", summarize)

    g.add_edge(START, "fetch_emails")
    g.add_edge("fetch_emails", "filter_candidates")
    g.add_conditional_edges(
        "filter_candidates", route_after_filter, {"classify": "classify", "done": END}
    )
    g.add_edge("classify", "rank")
    g.add_edge("rank", "summarize")
    g.add_edge("summarize", END)
    return g.compile()


graph = build_graph()


def graph_mermaid() -> str:
    """The graph as a Mermaid diagram. Paste it into https://mermaid.live to show students."""
    return graph.get_graph().draw_mermaid()


def graph_edges() -> list[dict]:
    """The graph's arrows as a simple list, in the order the agent walks them (breadth-first)."""
    edges = graph.get_graph().edges
    ordered, queue, seen = [], ["__start__"], set()
    while queue:
        node = queue.pop(0)
        if node in seen:
            continue
        seen.add(node)
        for e in edges:
            if e.source == node:
                ordered.append(
                    {
                        "from": e.source,
                        "to": e.target,
                        "conditional": bool(e.conditional),
                    }
                )
                queue.append(e.target)
    return ordered


# --------------------------------------------------------------------------- running it
# function to stream the agents response (meaning: word by word being displayed as the agent is thinking and then speaking)
def stream_agent(step_delay: float = 0.0) -> Iterator[dict]:
    """Run the graph and yield one event per node as it finishes, then a final 'result' event.

    stream_mode="updates" makes LangGraph hand us each node's output the moment it completes.
    """
    state: dict = {"trace": []}
    for chunk in graph.stream({"trace": []}, stream_mode="updates"):
        for node, update in chunk.items():
            update = update or {}
            new_lines = update.get("trace", [])
            for key, value in update.items():
                if key == "trace":
                    state["trace"] = state["trace"] + value
                else:
                    state[key] = value
            yield {"type": "step", "node": node, "messages": new_lines}
            if step_delay:
                time.sleep(step_delay)

    result = RunResult(
        mode=config.llm_mode(),
        source=config.EMAIL_SOURCE,
        emails_scanned=len(state.get("emails", [])),
        internships=state.get("internships", []),
        summary=state.get("summary", ""),
        trace=state["trace"],
    )
    yield {"type": "result", "data": result.model_dump()}


def run_agent() -> RunResult:
    """Run to completion and return only the final result (no streaming)."""
    final = None
    for event in stream_agent():
        if event["type"] == "result":
            final = event["data"]
    return RunResult(**final)
