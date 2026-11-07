"""Redeem a one-use Google GIS popup code. Identity comes only from Google's UserInfo."""

from dataclasses import dataclass

import httpx

from protohub.domain.models import LoginRequest
from protohub.domain.settings import Settings
from protohub.persistence.auth import validate_subject

TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


class GoogleDenied(Exception):
    """An invalid grant or unverified identity."""


class GoogleUnavailable(Exception):
    """Configuration or provider failure. Never echo provider payloads."""


@dataclass(frozen=True)
class GoogleIdentity:
    email: str
    subject: str
    authoritative: bool


def provider_response(response: httpx.Response) -> dict:
    if response.status_code != 200:
        if response.status_code in {400, 401, 403}:
            try:
                detail = response.json()
            except ValueError:
                raise GoogleUnavailable from None
            config_errors = (
                "invalid_client",
                "unauthorized_client",
                "redirect_uri_mismatch",
                "invalid_scope",
            )
            if not isinstance(detail, dict) or detail.get("error") in config_errors:
                raise GoogleUnavailable
            raise GoogleDenied
        raise GoogleUnavailable
    try:
        data = response.json()
    except ValueError:
        raise GoogleUnavailable from None
    if not isinstance(data, dict):
        raise GoogleUnavailable
    return data


def exchange_code(settings: Settings, code: str) -> GoogleIdentity:
    secret = settings.google_client_secret
    if not settings.google_ready or secret is None:
        raise GoogleUnavailable
    try:
        with httpx.Client(timeout=8, follow_redirects=False, trust_env=False) as client:
            grant = provider_response(
                client.post(
                    TOKEN_URL,
                    data={
                        "code": code,
                        "client_id": settings.google_client_id,
                        "client_secret": secret.get_secret_value(),
                        "grant_type": "authorization_code",
                        "redirect_uri": settings.console_origin,
                    },
                )
            )
            access = grant.get("access_token")
            if (
                not isinstance(access, str)
                or not access
                or not access.isascii()
                or any(ord(c) < 33 or ord(c) == 127 for c in access)
            ):
                raise GoogleUnavailable
            claims = provider_response(
                client.get(USERINFO_URL, headers={"Authorization": f"Bearer {access}"})
            )
    except httpx.HTTPError:
        raise GoogleUnavailable from None
    sub = claims.get("sub")
    raw_email = claims.get("email")
    if (
        claims.get("email_verified") is not True
        or not isinstance(sub, str)
        or not isinstance(raw_email, str)
    ):
        raise GoogleDenied
    try:
        validate_subject(sub)
        email = LoginRequest(email=raw_email).email
    except ValueError:
        raise GoogleDenied from None
    hosted = claims.get("hd")
    authoritative = email.endswith("@gmail.com") or (
        isinstance(hosted, str) and bool(hosted.strip())
    )
    return GoogleIdentity(email, sub, authoritative)
