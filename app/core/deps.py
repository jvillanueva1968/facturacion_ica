from typing import Callable, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings
from app.core.security import ROLE_ADMIN, decode_access_token, has_role, normalize_roles

settings = get_settings()
bearer_scheme = HTTPBearer(auto_error=False)

DEV_PRINCIPAL = {"sub": "dev", "roles": ["admin"]}


def auth_enabled() -> bool:
    return bool(settings.app_secret_key) and settings.environment == "production"


async def require_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> dict:
    """En producción exige Bearer JWT. En dev, admin por defecto."""
    if not auth_enabled():
        return dict(DEV_PRINCIPAL)

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
    payload["roles"] = normalize_roles(payload.get("roles"))
    return payload


def require_role(minimum: str) -> Callable:
    """Dependency factory: exige rol mínimo (viewer < operator < admin)."""

    async def _dep(
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    ) -> dict:
        if not auth_enabled():
            return dict(DEV_PRINCIPAL)

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

        payload["roles"] = normalize_roles(payload.get("roles"))
        if not has_role(payload, minimum):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Rol insuficiente: se requiere {minimum} o superior",
            )
        return payload

    return _dep


require_viewer = require_role("viewer")
require_operator = require_role("operator")
require_admin = require_role(ROLE_ADMIN)


async def optional_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> Optional[dict]:
    if credentials is None or not credentials.credentials:
        return None
    return decode_access_token(credentials.credentials)
