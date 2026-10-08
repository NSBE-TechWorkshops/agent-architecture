"""Mock email source: reads sample emails from a JSON file.

This lets the demo run anywhere with zero setup (no Google account, no internet).
"""
import json

from app import config
from app.models import Email


def fetch_emails(limit: int = 25) -> list[Email]:
    raw = json.loads(config.SAMPLE_EMAILS_PATH.read_text(encoding="utf-8"))
    return [Email(**item) for item in raw][:limit]
