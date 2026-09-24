"""Load/stress smoke — NO genera facturas (no toca /facturar).

Uso:
  python scripts/load_test.py --base http://localhost:8000 --concurrency 20 --duration 15
"""
from __future__ import annotations

import argparse
import asyncio
import random
import statistics
import sys
import time
from collections import Counter
from typing import Any, Dict, List, Tuple

import httpx

FORBIDDEN_PATHS = ("/facturar", "/facturas")


def build_targets(base: str) -> List[Tuple[str, str, Any]]:
    nits = [
        ("800197268", "4"),
        ("900123456", "7"),
        ("830039867", "8"),
    ]
    targets: List[Tuple[str, str, Any]] = [
        ("GET", f"{base}/health", None),
        ("GET", f"{base}/", None),
        ("GET", f"{base}/api/v1/nit/calcular-dv/800197268", None),
        ("GET", f"{base}/openapi.json", None),
    ]
    for nit, dv in nits:
        targets.append(("POST", f"{base}/api/v1/nit/validar", {"nit": nit, "dv": dv}))
        targets.append(("POST", f"{base}/api/v1/nit/validar", {"nit": nit + dv, "dv": dv}))
    # status inexistente: solo mide 404 sin escribir BD (UUID válido)
    targets.append(
        (
            "GET",
            f"{base}/api/v1/status/00000000-0000-4000-8000-000000000000",
            None,
        )
    )
    return targets


async def worker(
    client: httpx.AsyncClient,
    targets: List[Tuple[str, str, Any]],
    stop_at: float,
    latencies: List[float],
    codes: Counter,
    errors: Counter,
    name: str,
) -> None:
    while time.monotonic() < stop_at:
        method, url, body = random.choice(targets)
        if any(p in url for p in FORBIDDEN_PATHS):
            errors["forbidden_path"] += 1
            continue
        t0 = time.perf_counter()
        try:
            if method == "POST":
                r = await client.post(url, json=body)
            else:
                r = await client.get(url)
            dt = (time.perf_counter() - t0) * 1000
            latencies.append(dt)
            codes[r.status_code] += 1
            if r.status_code >= 500:
                errors[f"http_{r.status_code}"] += 1
        except Exception as exc:
            errors[type(exc).__name__] += 1
        # pequeña pausa para no saturar rate-limit innecesariamente
        await asyncio.sleep(0.01)


def pct(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = min(len(ordered) - 1, max(0, int(round((p / 100) * (len(ordered) - 1)))))
    return ordered[k]


async def run(base: str, concurrency: int, duration: float) -> int:
    base = base.rstrip("/")
    targets = build_targets(base)
    latencies: List[float] = []
    codes: Counter = Counter()
    errors: Counter = Counter()

    limits = httpx.Limits(max_connections=concurrency + 5, max_keepalive_connections=concurrency)
    timeout = httpx.Timeout(10.0)
    stop_at = time.monotonic() + duration
    t_start = time.time()

    async with httpx.AsyncClient(limits=limits, timeout=timeout, follow_redirects=True) as client:
        # warmup
        for method, url, body in targets[:3]:
            try:
                if method == "POST":
                    await client.post(url, json=body)
                else:
                    await client.get(url)
            except Exception:
                pass

        tasks = [
            asyncio.create_task(worker(client, targets, stop_at, latencies, codes, errors, f"w{i}"))
            for i in range(concurrency)
        ]
        await asyncio.gather(*tasks)

    elapsed = time.time() - t_start
    total = sum(codes.values()) + sum(errors.values())
    rps = total / elapsed if elapsed else 0
    ok = sum(v for k, v in codes.items() if k < 400)
    rate_limited = codes.get(429, 0)

    report = {
        "base": base,
        "duration_s": round(elapsed, 2),
        "concurrency": concurrency,
        "requests": total,
        "rps": round(rps, 1),
        "ok": ok,
        "ok_pct": round(100 * ok / total, 1) if total else 0,
        "codes": dict(codes),
        "errors": dict(errors),
        "rate_limited_429": rate_limited,
        "latency_ms": {
            "avg": round(statistics.mean(latencies), 1) if latencies else None,
            "p50": round(pct(latencies, 50), 1),
            "p95": round(pct(latencies, 95), 1),
            "p99": round(pct(latencies, 99), 1),
            "max": round(max(latencies), 1) if latencies else None,
        },
        "forbidden_paths_hit": any(p in str(u) for p in FORBIDDEN_PATHS for _, u, _ in targets),
        "facturas_created": 0,
    }

    print("=== LOAD TEST (sin facturar) ===")
    for k, v in report.items():
        print(f"{k}: {v}")

    # Fallo solo si hay 5xx o errores de red; 429 es comportamiento esperado de rate-limit
    has_server_error = any(int(c) >= 500 for c in codes)
    fail = has_server_error or bool(errors and not all(k == "forbidden_path" for k in errors))
    print(f"RESULT: {'FAIL' if fail else 'PASS'} (429 esperados por rate-limit OK)")
    return 1 if fail else 0


def main() -> None:
    p = argparse.ArgumentParser(description="Load test sin generar facturas")
    p.add_argument("--base", default="http://localhost:8000")
    p.add_argument("--concurrency", type=int, default=20)
    p.add_argument("--duration", type=float, default=15.0)
    args = p.parse_args()
    for path in FORBIDDEN_PATHS:
        if path in args.base:
            print("Refusing base URL that points at facturación", file=sys.stderr)
            sys.exit(2)
    rc = asyncio.run(run(args.base, args.concurrency, args.duration))
    sys.exit(rc)


if __name__ == "__main__":
    main()
