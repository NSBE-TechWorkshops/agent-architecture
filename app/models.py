"""Data shapes shared by the agent, the API and the UI.

Pydantic models give us validation + automatic JSON conversion. FastAPI also uses them
to build the /docs page, and the LLM is forced to answer in the shape of
`EmailClassification` (that's called "structured output").
"""
from typing import Literal

from pydantic import BaseModel, Field

Category = Literal[
    "new_posting",
    "application_update",
    "interview",
    "assessment",
    "offer",
    "rejection",
    "deadline_reminder",
    "event",
    "other",
]
Urgency = Literal["high", "medium", "low"]


class Email(BaseModel):
    """One email, no matter where it came from (mock file or Gmail)."""

    id: str
    sender: str
    subject: str
    date: str
    body: str


class EmailClassification(BaseModel):
    """What we ask the LLM to fill in for each email."""

    is_internship_related: bool = Field(
        description="True only if this email is about an internship, co-op, or early-career program."
    )
    category: Category = Field(description="The best-fitting category for this email.")
    company: str = Field(description="Company or organization name. Use 'Unknown' if unclear.")
    role: str = Field(description="Role or program title. Use 'Unknown' if unclear.")
    deadline: str | None = Field(description="Deadline or event date as YYYY-MM-DD, or null if none.")
    urgency: Urgency = Field(description="high = needs action within ~3 days, medium = within ~2 weeks, low = FYI.")
    action_needed: str = Field(description="One short sentence: what the student should do next.")


class Internship(EmailClassification):
    """A classified email plus the details of the original message."""

    email_id: str
    sender: str
    subject: str
    date: str


class RunResult(BaseModel):
    """Everything the agent produces in one run."""

    mode: str
    source: str
    emails_scanned: int
    internships: list[Internship]
    summary: str
    trace: list[str]
