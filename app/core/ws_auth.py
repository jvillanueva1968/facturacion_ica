from typing import Optional, Tuple

from fastapi import Query, WebSocket, WebSocketDisconnect

from app.config import get_settings
from app.core.deps import DEV_PRINCIPAL, auth_enabled
from app.core.security import ROLE_VIEWER, decode_access_token, has_role, normalize_roles

settings = get_settings()


def _token_from_ws(websocket: WebSocket, token: Optional[str]) -> Optional[str]:
    if token:
        return token
    auth = websocket.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


async def authenticate_websocket(
    websocket: WebSocket,
    token: Optional[str] = Query(default=None),
) -> Optional[dict]:
    """Autentica WebSocket (viewer+). Devuelve payload o cierra y devuelve None."""
    if not auth_enabled():
        return dict(DEV_PRINCIPAL)

    raw = _token_from_ws(websocket, token)
    if not raw:
        await websocket.close(code=4401, reason="Token requerido")
        return None

    payload = decode_access_token(raw)
    if not payload or not payload.get("sub"):
        await websocket.close(code=4401, reason="Token inválido o expirado")
        return None

    payload["roles"] = normalize_roles(payload.get("roles"))
    if not has_role(payload, ROLE_VIEWER):
        await websocket.close(code=4403, reason="Rol insuficiente: se requiere viewer")
        return None
    return payload


async def require_ws_viewer(websocket: WebSocket) -> Optional[Tuple[WebSocket, dict]]:
    user = await authenticate_websocket(websocket)
    if user is None:
        return None
    return websocket, user
