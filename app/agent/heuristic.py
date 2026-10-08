"""A simple rule-based classifier: the fallback when there is no OpenAI key.

It is deliberately basic (keywords + regex). Run the demo once in this mode and once with an
LLM, and the difference shows why LLMs are so useful for messy, human-written text.
"""
import re
from datetime import date, datetime

from app.models import Email, EmailClassification

INTERNSHIP_WORDS = ("intern", "co-op", "coop", "early career", "career fair", "new grad")

# Order matters: the first matching rule wins.
CATEGORY_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("offer", ("offer letter", "pleased to offer", "thrilled to offer", "offer:", "congratulations")),
    ("rejection", ("not move forward", "decided not to", "unfortunately", "other candidates")),
    ("assessment", ("online assessment", "coding assessment", "coding challenge", "hackerrank", "codesignal")),
    ("interview", ("interview",)),
    ("application_update", ("application received", "received your application", "thank you for applying")),
    ("deadline_reminder", ("reminder", "closes soon", "closing soon", "last chance")),
    ("event", ("career fair", "info session", "networking", "workshop")),
    ("new_posting", ("applications open", "now accepting", "new internship", "now hiring", "new posting")),
]

ACTIONS = {
    "offer": "Review the offer and respond before the deadline.",
    "rejection": "No action needed. Consider applying to similar roles.",
    "assessment": "Complete the online assessment before the link expires.",
    "interview": "Pick an interview slot and prepare.",
    "application_update": "Nothing to do yet. Wait for the recruiter to reply.",
    "deadline_reminder": "Finish and submit your application before it closes.",
    "event": "Add the event to your calendar and bring your resume.",
    "new_posting": "Read the posting and apply if it fits.",
    "other": "Review when you have time.",
}

GENERIC_WORDS = {"careers", "career", "talent", "jobs", "recruiting", "hiring", "mail", "noreply"}
ROLE_PATTERN = re.compile(r"((?:[A-Z][A-Za-z&/+-]*\s){1,5}(?:Internship|Intern|Co-op))")
DATE_PATTERN = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


def looks_internship_related(email: Email) -> bool:
    text = f"{email.subject} {email.body}".lower()
    return any(word in text for word in INTERNSHIP_WORDS)


def _company_from_sender(sender: str) -> str:
    match = re.search(r"@([\w.-]+)", sender)
    if not match:
        return "Unknown"
    labels = match.group(1).split(".")
    label = labels[-2] if len(labels) >= 2 else labels[0]
    words = [w for w in label.split("-") if w not in GENERIC_WORDS] or label.split("-")
    name = " ".join(words)
    return name.upper() if len(name) <= 4 else name.title()


def _parse_day(value: str) -> date | None:
    for fmt in ("%Y-%m-%d", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            return datetime.strptime(value[:31].strip(), fmt).date()
        except ValueError:
            continue
    return None


def _urgency(category: str, deadline: str | None, received: str) -> str:
    if not deadline:
        return "low"
    due, start = _parse_day(deadline), _parse_day(received) or date.today()
    if due is None:
        return "low"
    days = (due - start).days
    if days <= 3:
        return "high"
    if days <= 14 or category == "offer":
        return "medium"
    return "low"


def classify(email: Email) -> EmailClassification:
    text = f"{email.subject}\n{email.body}"
    lowered = text.lower()

    category = "other"
    for name, keywords in CATEGORY_RULES:
        if any(k in lowered for k in keywords):
            category = name
            break

    role_match = ROLE_PATTERN.search(email.subject) or ROLE_PATTERN.search(email.body)
    date_match = DATE_PATTERN.search(email.body)
    deadline = date_match.group(1) if date_match else None

    return EmailClassification(
        is_internship_related=looks_internship_related(email),
        category=category,
        company=_company_from_sender(email.sender),
        role=role_match.group(1).strip() if role_match else "Unknown",
        deadline=deadline,
        urgency=_urgency(category, deadline, email.date),
        action_needed=ACTIONS[category],
    )
