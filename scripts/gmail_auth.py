"""One-time Gmail login. Run this on your own computer (NOT inside Docker).

    python scripts/gmail_auth.py

It opens your browser, asks you to allow READ-ONLY access, and saves secrets/token.json.
For you guys to see how it works against live data from your own email
"""

from pathlib import (
    Path,  # incase you guys were wondering this help w file system commands that need to be ran
)

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly"
]  # auth link so that auth is able to be set up
SECRETS = (
    Path(__file__).resolve().parent.parent / "secrets"
)  # saves the secrets into the secrets folder so that the app can access them for email retrieval


def main() -> None:
    creds_file = SECRETS / "credentials.json"
    if not creds_file.exists():
        raise SystemExit(
            f"Missing {creds_file}. Download it from Google Cloud Console first (see README)."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), SCOPES)
    creds = flow.run_local_server(port=0)
    (SECRETS / "token.json").write_text(creds.to_json())
    print("Saved secrets/token.json. Now set EMAIL_SOURCE=gmail in your .env file.")


if __name__ == "__main__":
    main()
