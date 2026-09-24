from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import get_settings

settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
ALGORITHM = "HS256"

ROLE_VIEWER = "viewer"
ROLE_OPERATOR = "operator"
ROLE_ADMIN = "admin"
VALID_ROLES = {ROLE_VIEWER, ROLE_OPERATOR, ROLE_ADMIN}

# Jerarquía: admin > operator > viewer
ROLE_RANK = {ROLE_VIEWER: 1, ROLE_OPERATOR: 2, ROLE_ADMIN: 3}


def normalize_roles(roles: Optional[Iterable[str]]) -> List[str]:
    if not roles:
        return [ROLE_OPERATOR]
    cleaned = []
    for r in roles:
        r = (r or "").strip().lower()
        if r in VALID_ROLES and r not in cleaned:
            cleaned.append(r)
    return cleaned or [ROLE_OPERATOR]


def has_role(payload: dict, required: str) -> bool:
    roles = normalize_roles(payload.get("roles"))
    need = ROLE_RANK.get(required, 99)
    return any(ROLE_RANK.get(r, 0) >= need for r in roles)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(
    subject: str,
    expires_minutes: Optional[int] = None,
    roles: Optional[Iterable[str]] = None,
) -> str:
    secret = settings.app_secret_key or "dev-secret-change-me-in-production-32bytes"
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes or settings.access_token_expire_minutes
    )
    payload = {
        "sub": subject,
        "exp": expire,
        "roles": normalize_roles(roles),
    }
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    secret = settings.app_secret_key or "dev-secret-change-me-in-production-32bytes"
    try:
        return jwt.decode(token, secret, algorithms=[ALGORITHM])
    except JWTError:
        return None
