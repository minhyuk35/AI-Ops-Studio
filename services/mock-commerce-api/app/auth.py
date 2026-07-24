import hashlib
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import httpx
import jwt

ALGORITHM = "HS256"
TOKEN_TTL_MINUTES = 60 * 24 * 7  # 7 days, fine for a portfolio demo session
GOOGLE_TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"


class GoogleTokenError(Exception):
    """Raised when a Google Identity Services credential fails verification."""

# passlib's CryptContext wraps bcrypt but its bundled version-detection shim
# is broken against bcrypt>=4.1 (no more `__about__`), so this calls bcrypt
# directly instead. bcrypt's own 72-byte secret limit is handled by hashing
# the password down to a fixed-length digest first.


def _digest(password: str) -> bytes:
    return hashlib.sha256(password.encode("utf-8")).digest()


def _secret_key() -> str:
    # Dev-only fallback so the app runs out of the box; real deployments must
    # set AUTH_SECRET_KEY (see .env.example). Padded past 32 bytes to clear
    # HS256's minimum recommended key length (RFC 7518 §3.2).
    return os.getenv("AUTH_SECRET_KEY", "dev-insecure-secret-change-me-please")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_digest(password), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(_digest(password), password_hash.encode("ascii"))
    except ValueError:
        return False


def create_access_token(customer_id: str) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": customer_id,
        "iat": now,
        "exp": now + timedelta(minutes=TOKEN_TTL_MINUTES),
    }
    return jwt.encode(payload, _secret_key(), algorithm=ALGORITHM)


def decode_access_token(token: str) -> str | None:
    try:
        payload: dict[str, Any] = jwt.decode(token, _secret_key(), algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    subject = payload.get("sub")
    return subject if isinstance(subject, str) else None


def verify_google_id_token(id_token: str) -> dict[str, Any]:
    """Verify a Google Identity Services credential and return its claims.

    Calls Google's tokeninfo endpoint rather than doing local JWKS/signature
    verification — Google documents this endpoint for exactly this kind of
    low-volume server-side check, and it avoids adding a JWKS client just
    for one login path. GOOGLE_CLIENT_ID must match the credential's
    audience or the token is rejected even if Google says it's valid.
    """
    client_id = os.getenv("GOOGLE_CLIENT_ID", "")
    if not client_id:
        raise GoogleTokenError(
            "구글 로그인이 아직 설정되지 않았습니다. 서버에 GOOGLE_CLIENT_ID를 설정해주세요."
        )
    try:
        response = httpx.get(GOOGLE_TOKENINFO_URL, params={"id_token": id_token}, timeout=10)
    except httpx.HTTPError as exc:
        raise GoogleTokenError("구글 로그인 서버에 연결하지 못했습니다.") from exc
    if response.status_code != 200:
        raise GoogleTokenError("구글 로그인 토큰이 유효하지 않습니다.")
    claims: dict[str, Any] = response.json()
    if claims.get("aud") != client_id:
        raise GoogleTokenError("구글 로그인 토큰의 대상이 이 서비스와 일치하지 않습니다.")
    if claims.get("email_verified") not in ("true", True):
        raise GoogleTokenError("구글 계정의 이메일이 인증되지 않았습니다.")
    if not claims.get("email"):
        raise GoogleTokenError("구글 계정에서 이메일을 확인할 수 없습니다.")
    return claims
