"""Fail-closed consent.

A request is processed only if it carries a valid, unexpired, correctly-scoped
consent token. Anything else fails closed. The token carries scopes + expiry,
never identity. In production the companion app mints the token at the moment
the user grants consent, and withdrawal simply stops minting / revokes.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Optional

_SECRET = os.environ.get("CONSENT_SECRET", "dev-only-change-me").encode()
REQUIRED_SCOPE = "interpret"


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64u_dec(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def mint_consent_token(scopes: Optional[list[str]] = None, ttl_s: int = 3600,
                       device: str = "demo") -> str:
    """DEV ONLY helper to create a token for local testing / the demo."""
    payload = {
        "scopes": scopes or [REQUIRED_SCOPE],
        "exp": int(time.time()) + ttl_s,
        "device": device,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    sig = hmac.new(_SECRET, raw, hashlib.sha256).digest()
    return f"{_b64u(raw)}.{_b64u(sig)}"


class ConsentError(Exception):
    pass


def validate_consent(token: str) -> dict:
    """Return the token payload if valid; raise ConsentError otherwise (fail-closed)."""
    try:
        raw_b64, sig_b64 = token.split(".", 1)
        raw = _b64u_dec(raw_b64)
        sig = _b64u_dec(sig_b64)
    except Exception as exc:  # malformed
        raise ConsentError("malformed consent token") from exc

    expected = hmac.new(_SECRET, raw, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        raise ConsentError("bad consent signature")

    try:
        payload = json.loads(raw)
    except Exception as exc:
        raise ConsentError("unreadable consent payload") from exc

    if int(payload.get("exp", 0)) < int(time.time()):
        raise ConsentError("consent expired")
    if REQUIRED_SCOPE not in payload.get("scopes", []):
        raise ConsentError("consent scope missing")
    return payload
