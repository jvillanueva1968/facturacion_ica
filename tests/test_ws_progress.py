import asyncio

from fastapi.testclient import TestClient

from app.core.progress import ProgressHub, emit_stage, progress_hub
from app.main import app

client = TestClient(app)


def test_progress_hub_pub_sub():
    hub = ProgressHub()

    async def run():
        q = hub.subscribe("t1")
        await hub.publish("t1", {"stage": "ocr_start", "status": "processing", "progress": 10})
        event = await asyncio.wait_for(q.get(), timeout=1)
        assert event["stage"] == "ocr_start"
        assert event["task_id"] == "t1"
        hub.unsubscribe("t1", q)
        q2 = hub.subscribe("t1")
        latest = q2.get_nowait()
        assert latest["stage"] == "ocr_start"
        hub.unsubscribe("t1", q2)

    asyncio.run(run())


def test_emit_stage_actualiza_latest():
    async def run():
        progress_hub.clear()
        await emit_stage("task-emit", "received", mensaje="ok")
        latest = progress_hub.get_latest("task-emit")
        assert latest is not None
        assert latest["status"] == "processing"
        assert latest["progress"] == 5
        assert latest["mensaje"] == "ok"
        progress_hub.clear()

    asyncio.run(run())


def test_ws_status_conecta_y_recibe_evento():
    progress_hub.clear()
    with client as c:
        with c.websocket_connect("/api/v1/ws/status/task-ws-1") as ws:
            hello = ws.receive_json()
            assert hello["stage"] == "subscribed"
            hub = progress_hub
            hub._latest["task-ws-1"] = {
                "task_id": "task-ws-1",
                "stage": "completed",
                "status": "completed",
                "progress": 100,
                "mensaje": "Completado",
            }
            for q in list(hub._subs.get("task-ws-1") or set()):
                q.put_nowait(hub._latest["task-ws-1"])
            event = ws.receive_json()
            assert event["status"] == "completed"
            assert event["stage"] == "completed"
    progress_hub.clear()


def test_ws_upgrade_ok_en_dev():
    with client.websocket_connect("/api/v1/ws/status/any") as ws:
        msg = ws.receive_json()
        assert msg["stage"] == "subscribed"
