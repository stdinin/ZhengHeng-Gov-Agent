from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from jwt.exceptions import InvalidTokenError

from backend.app.config import Settings
from backend.app.security.rbac import Role


@dataclass(frozen=True, slots=True)
class User:
    id: str
    email: str
    password_hash: str
    role: Role
    created_at: datetime | None = None
    updated_at: datetime | None = None


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_access_token(user: User, settings: Settings) -> str:
    expires_at = datetime.now(UTC) + timedelta(seconds=settings.session_ttl_seconds)
    return jwt.encode(
        {"sub": user.id, "role": user.role.value, "exp": expires_at},
        settings.app_secret,
        algorithm="HS256",
    )


def decode_access_token(token: str, settings: Settings) -> str:
    try:
        payload = jwt.decode(token, settings.app_secret, algorithms=["HS256"])
    except InvalidTokenError as error:
        raise ValueError("Invalid or expired access token.") from error
    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject:
        raise ValueError("Access token subject is missing.")
    return subject
