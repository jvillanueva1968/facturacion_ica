from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from typing import Any, Dict, Optional, Set


class ProgressHub:
    """Pub/sub en memoria de progreso de tareas de upload (un solo proceso)."""

    def __init__(self) -> None:
        self._subs: Dict[str, Set[asyncio.Queue]] = defaultdict(set)
        self._latest: Dict[str, Dict[str, Any]] = {}
        self._max_tasks = 500

    async def publish(self, task_id: str, event: Dict[str, Any]) -> None:
        payload = {
            "task_id": task_id,
            "ts": time.time(),
            **event,
        }
        self._latest[task_id] = payload
        if len(self._latest) > self._max_tasks:
            for key in list(self._latest.keys())[: len(self._latest) - self._max_tasks]:
                self._latest.pop(key, None)
        for q in list(self._subs.get(task_id, ())):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass

    def subscribe(self, task_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=32)
        self._subs[task_id].add(q)
        latest = self._latest.get(task_id)
        if latest is not None:
            q.put_nowait(latest)
        return q

    def unsubscribe(self, task_id: str, q: asyncio.Queue) -> None:
        subs = self._subs.get(task_id)
        if not subs:
            return
        subs.discard(q)
        if not subs:
            self._subs.pop(task_id, None)

    def get_latest(self, task_id: str) -> Optional[Dict[str, Any]]:
        return self._latest.get(task_id)

    def clear(self) -> None:
        self._subs.clear()
        self._latest.clear()


progress_hub = ProgressHub()

STAGE_EVENTS = {
    "received": {"stage": "received", "status": "processing", "progress": 5},
    "ocr_start": {"stage": "ocr_start", "status": "processing", "progress": 10},
    "ocr_done": {"stage": "ocr_done", "status": "processing", "progress": 40},
    "llm_start": {"stage": "llm_start", "status": "processing", "progress": 45},
    "llm_done": {"stage": "llm_done", "status": "processing", "progress": 75},
    "nit_start": {"stage": "nit_start", "status": "processing", "progress": 80},
    "completed": {"stage": "completed", "status": "completed", "progress": 100},
    "failed": {"stage": "failed", "status": "failed", "progress": 100},
}


async def emit_stage(
    task_id: str,
    stage: str,
    *,
    mensaje: Optional[str] = None,
    datos: Optional[dict] = None,
    errores: Optional[list] = None,
    nit_validado: Optional[bool] = None,
    nit_mensaje: Optional[str] = None,
    confianza: Optional[float] = None,
    texto_ocr: Optional[str] = None,
    paginas: Optional[int] = None,
) -> None:
    base = dict(STAGE_EVENTS.get(stage, {"stage": stage, "status": "processing", "progress": 50}))
    event: Dict[str, Any] = dict(base)
    if mensaje:
        event["mensaje"] = mensaje
    if datos is not None:
        event["datos"] = datos
    if errores is not None:
        event["errores"] = errores
    if nit_validado is not None:
        event["nit_validado"] = nit_validado
    if nit_mensaje is not None:
        event["nit_mensaje"] = nit_mensaje
    if confianza is not None:
        event["confianza"] = confianza
    if texto_ocr:
        event["texto_ocr"] = texto_ocr
    if paginas is not None:
        event["paginas"] = paginas
    await progress_hub.publish(task_id, event)
