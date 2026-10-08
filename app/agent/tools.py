"""LangChain tools the LLM can choose during the internship agent run.

These are deliberately small, ordinary Python functions. The important teaching
point is that the LLM decides *when* to call them; Python still does the actual
work once a tool call is requested.
"""

from langchain_core.tools import tool

from app.agent import heuristic
from app.models import Email, Internship
from app.sources import fetch_emails as load_emails

URGENCY_ORDER = {"high": 0, "medium": 1, "low": 2}


@tool
def fetch_emails_tool() -> list[dict]:
    """Fetch recent emails from the configured source and return them as JSON-ready dictionaries."""
    emails = load_emails()
    return [email.model_dump() for email in emails]


@tool
def filter_internship_candidates_tool(emails: list[dict]) -> list[dict]:
    """Return only emails that look related to internships, co-ops, new-grad roles, or career events."""
    parsed = [Email(**email) for email in emails]
    candidates = [email for email in parsed if heuristic.looks_internship_related(email)]
    return [email.model_dump() for email in candidates]


@tool
def classify_email_tool(email: dict) -> dict:
    """Classify one email and extract company, role, deadline, urgency, and the recommended action."""
    parsed = Email(**email)
    result = heuristic.classify(parsed)
    internship = Internship(
        **result.model_dump(),
        email_id=parsed.id,
        sender=parsed.sender,
        subject=parsed.subject,
        date=parsed.date,
    )
    return internship.model_dump()


@tool
def rank_internships_tool(internships: list[dict]) -> list[dict]:
    """Drop unrelated classifications and rank internship emails by urgency, then deadline."""
    items = [Internship(**item) for item in internships]
    related = [item for item in items if item.is_internship_related]
    related.sort(key=lambda item: (URGENCY_ORDER[item.urgency], item.deadline or "9999-99-99"))
    return [item.model_dump() for item in related]


tools = [
    fetch_emails_tool,
    filter_internship_candidates_tool,
    classify_email_tool,
    rank_internships_tool,
]
