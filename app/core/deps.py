from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings
from app.core.security import decode_access_token

settings = get_settings()
bearer_scheme = HTTPBearer(auto_error=False)


def auth_enabled() -> bool:
    return bool(settings.app_secret_key) and settings.environment == "production"


async def require_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> dict:
    """En producción exige Bearer JWT. En dev, permite pasar sin token."""
    if not auth_enabled():
        return {"sub": "dev", "roles": ["admin"]}

    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token requerido",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(credentials.credentials)
    if not payload or not payload.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload


async def optional_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> Optional[dict]:
    if credentials is None or not credentials.credentials:
        return None
    return decode_access_token(credentials.credentials)
