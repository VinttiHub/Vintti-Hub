import os

_DEFAULT_EDITOR_EMAIL = "pgonzales@vintti.com"


def editor_email() -> str:
    return (os.getenv("DASHBOARD_EDITOR_EMAIL") or _DEFAULT_EDITOR_EMAIL).strip().lower()


def is_editor(email: str | None) -> bool:
    if not email:
        return False
    return email.strip().lower() == editor_email()
