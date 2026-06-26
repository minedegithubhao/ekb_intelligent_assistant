"""Password hashing and minimal HS256 JWT helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.config import get_runtime_config
from app.core.exceptions import AuthException


PASSWORD_ALGORITHM = "pbkdf2_sha256"


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def hash_password(password: str, salt: str | None = None, iterations: int | None = None) -> str:
    # PBKDF2 is available in the Python standard library, so no extra auth dependency is required.
    config = get_runtime_config().app.security
    used_iterations = iterations or config.password_hash_iterations
    used_salt = salt or secrets.token_urlsafe(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), used_salt.encode("utf-8"), used_iterations)
    return f"{PASSWORD_ALGORITHM}${used_iterations}${used_salt}${_b64url_encode(digest)}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations, salt, expected = password_hash.split("$", 3)
        if algorithm != PASSWORD_ALGORITHM:
            return False
        candidate = hash_password(password, salt=salt, iterations=int(iterations)).split("$", 3)[3]
        return hmac.compare_digest(candidate, expected)
    except Exception:
        return False


def create_access_token(subject: str, username: str, roles: list[str]) -> tuple[str, datetime, str]:
    # Returns token, expiry time, and token id. The token id is used for logout blacklist.
    security = get_runtime_config().app.security
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=security.access_token_expire_minutes)
    jti = secrets.token_urlsafe(16)
    header = {"typ": "JWT", "alg": security.algorithm}
    payload = {
        "sub": subject,
        "username": username,
        "roles": roles,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": jti,
    }
    signing_input = f"{_b64url_encode(json.dumps(header, separators=(',', ':')).encode())}.{_b64url_encode(json.dumps(payload, separators=(',', ':')).encode())}"
    signature = hmac.new(security.secret_key.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url_encode(signature)}", expires_at, jti


def decode_access_token(token: str) -> dict[str, Any]:
    security = get_runtime_config().app.security
    try:
        header_segment, payload_segment, signature_segment = token.split(".", 2)
        signing_input = f"{header_segment}.{payload_segment}"
        header = json.loads(_b64url_decode(header_segment))
        if header.get("alg") != security.algorithm:
            raise AuthException("unsupported token algorithm")
        expected_signature = hmac.new(
            security.secret_key.encode("utf-8"),
            signing_input.encode("ascii"),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(_b64url_encode(expected_signature), signature_segment):
            raise AuthException("invalid token signature")
        payload = json.loads(_b64url_decode(payload_segment))
        if int(payload.get("exp", 0)) < int(datetime.now(UTC).timestamp()):
            raise AuthException("token expired", code=40101)
        return payload
    except AuthException:
        raise
    except Exception as exc:
        raise AuthException("invalid token") from exc
