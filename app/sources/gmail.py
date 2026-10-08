"""Gmail email source, using the official Gmail API (read-only).

How access works (OAuth in one paragraph):
  1. You create an "OAuth client" in Google Cloud and download credentials.json.
  2. You run scripts/gmail_auth.py ONCE on your own computer. A browser opens, you click
     "Allow", and Google hands back a token that is saved to secrets/token.json.
  3. This code loads that token and calls the Gmail API on your behalf. The token only
     has the "read-only" permission, so the app can never send or delete mail.
"""
import base64
import re

from app import config
from app.models import Email

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

# Gmail search syntax, the same thing you would type into the Gmail search bar.
SEARCH_QUERY = (
    'newer_than:30d (intern OR internship OR co-op OR coop OR "early career" '
    'OR recruiter OR "your application" OR interview OR "online assessment")'
)


def _get_service():
    # Imported here so the app still starts when Gmail libraries/credentials are not needed.
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    if not config.GMAIL_TOKEN_PATH.exists():
        raise RuntimeError(
            "secrets/token.json not found. Run `python scripts/gmail_auth.py` first "
            "(see the README, 'Connect your real Gmail')."
        )
    creds = Credentials.from_authorized_user_file(str(config.GMAIL_TOKEN_PATH), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())  # refreshed in memory only
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def _extract_text(payload: dict) -> str:
    """Gmail messages are nested 'parts'. Walk them and return the first plain-text body."""
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        data = payload["body"]["data"]
        return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")
    for part in payload.get("parts", []) or []:
        text = _extract_text(part)
        if text:
            return text
    return ""


def fetch_emails(limit: int = 25) -> list[Email]:
    service = _get_service()
    listing = (
        service.users().messages().list(userId="me", q=SEARCH_QUERY, maxResults=limit).execute()
    )
    emails: list[Email] = []
    for ref in listing.get("messages", []):
        msg = service.users().messages().get(userId="me", id=ref["id"], format="full").execute()
        headers = msg["payload"].get("headers", [])
        body = _extract_text(msg["payload"]) or msg.get("snippet", "")
        body = re.sub(r"\s+", " ", body).strip()[:2000]  # keep prompts small and cheap
        emails.append(
            Email(
                id=ref["id"],
                sender=_header(headers, "From"),
                subject=_header(headers, "Subject"),
                date=_header(headers, "Date"),
                body=body,
            )
        )
    return emails
