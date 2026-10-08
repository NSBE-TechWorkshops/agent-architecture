"""Pick where emails come from, based on the EMAIL_SOURCE setting."""
from app import config
from app.models import Email


def fetch_emails(limit: int | None = None) -> list[Email]:
    limit = limit or config.GMAIL_MAX_RESULTS
    if config.EMAIL_SOURCE == "gmail":
        from app.sources import gmail

        return gmail.fetch_emails(limit)
    from app.sources import mock

    return mock.fetch_emails(limit)
