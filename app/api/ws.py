import asyncio

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.core.progress import progress_hub
from app.core.ws_auth import authenticate_websocket

router = APIRouter()


@router.websocket("/ws/status/{task_id}")
async def ws_task_status(websocket: WebSocket, task_id: str, token: str | None = Query(default=None)):
    user = await authenticate_websocket(websocket, token)
    if user is None:
        return

    await websocket.accept()
    queue = progress_hub.subscribe(task_id)
    try:
        await websocket.send_json(
            {
                "task_id": task_id,
                "stage": "subscribed",
                "status": "processing",
                "progress": 0,
                "mensaje": "Conectado al progreso",
            }
        )
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping", "task_id": task_id})
                continue
            await websocket.send_json(event)
            if event.get("status") in ("completed", "failed"):
                # dejar un momento para que el cliente reciba y cierre
                await asyncio.sleep(0.05)
                break
    except WebSocketDisconnect:
        pass
    except Exception:
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
    finally:
        progress_hub.unsubscribe(task_id, queue)
