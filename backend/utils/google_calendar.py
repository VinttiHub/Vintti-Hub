from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
DEFAULT_SCOPES = ("https://www.googleapis.com/auth/calendar",)


def _parse_scopes(raw: str | None) -> list[str]:
    if not raw:
        return list(DEFAULT_SCOPES)
    if "," in raw:
        return [part.strip() for part in raw.split(",") if part.strip()]
    return [part.strip() for part in raw.split() if part.strip()]


def get_google_oauth_config() -> dict:
    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
    redirect_uri = os.getenv("GOOGLE_OAUTH_REDIRECT_URI")
    scopes = _parse_scopes(os.getenv("GOOGLE_CALENDAR_SCOPES"))

    if not client_id or not client_secret or not redirect_uri:
        raise RuntimeError(
            "Missing GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET, or GOOGLE_OAUTH_REDIRECT_URI",
        )

    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "scopes": scopes,
    }


def build_auth_url(state: str, redirect_uri: str | None = None, scopes: list[str] | None = None) -> str:
    config = get_google_oauth_config()
    params = {
        "client_id": config["client_id"],
        "redirect_uri": redirect_uri or config["redirect_uri"],
        "response_type": "code",
        "scope": " ".join(scopes or config["scopes"]),
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code_for_tokens(code: str) -> dict:
    config = get_google_oauth_config()
    resp = requests.post(
        TOKEN_URL,
        data={
            "code": code,
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
            "redirect_uri": config["redirect_uri"],
            "grant_type": "authorization_code",
        },
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def refresh_access_token(refresh_token: str) -> dict:
    config = get_google_oauth_config()
    resp = requests.post(
        TOKEN_URL,
        data={
            "refresh_token": refresh_token,
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
            "grant_type": "refresh_token",
        },
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def build_calendar_service(tokens: dict) -> tuple[Credentials, object]:
    config = get_google_oauth_config()
    creds = Credentials(
        token=tokens.get("access_token"),
        refresh_token=tokens.get("refresh_token"),
        token_uri=TOKEN_URL,
        client_id=config["client_id"],
        client_secret=config["client_secret"],
        scopes=config["scopes"],
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    return creds, service


def token_expiry_from_seconds(expires_in: int | None) -> datetime | None:
    if not expires_in:
        return None
    return datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))


def new_state_token() -> str:
    return secrets.token_urlsafe(24)
