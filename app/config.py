"""
This helps so that we can configure and get all the nessesary .env variables
needed for the project so that we can use it in the other files that may need
to call it.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # no-op if there is no .env file

ROOT = Path(__file__).resolve().parent.parent

OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
EMAIL_SOURCE: str = os.getenv("EMAIL_SOURCE", "mock").strip().lower()
GMAIL_MAX_RESULTS: int = int(os.getenv("GMAIL_MAX_RESULTS", "25"))
DEMO_STEP_DELAY: float = float(os.getenv("DEMO_STEP_DELAY", "0.8"))

SAMPLE_EMAILS_PATH = ROOT / "data" / "sample_emails.json"
GMAIL_TOKEN_PATH = ROOT / "secrets" / "token.json"
GMAIL_CREDENTIALS_PATH = ROOT / "secrets" / "credentials.json"


def llm_mode() -> str:
    """'llm' if we can call OpenAI, otherwise 'heuristic' (simple keyword rules)."""
    return "llm" if OPENAI_API_KEY else "heuristic"
