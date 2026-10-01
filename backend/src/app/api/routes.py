from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
async def health(request: Request) -> Any:
    """
    Health endpoint. If a health_check callable is attached to app.state it is
    called with (conn, settings) semantics; otherwise return the minimal ok.
    """
    health_check = getattr(request.app.state, "health_check", None)
    if health_check is None:
        return {"status": "ok"}

    result = await health_check() if callable(health_check) else None
    # If the injected check indicates healthy, return the simple shape.
    if result is None or getattr(result, "status", None) == "ok":
        return {"status": "ok"}

    # Otherwise, follow the minimal unhealthy shape.
    return {
        "status": "unhealthy",
        "reason": getattr(result, "reason", "unknown"),
        "detail": getattr(result, "detail", ""),
    }
