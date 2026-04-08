"""헬스체크 라우트 — 인증 없음."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db

router = APIRouter()


@router.get("/healthz")
async def healthz(db: Session = Depends(get_db)) -> JSONResponse:
    """DB ping + 상태 반환."""
    try:
        db.execute(text("SELECT 1"))
        return JSONResponse({"status": "ok"})
    except Exception as exc:
        return JSONResponse({"status": "error", "detail": str(exc)}, status_code=503)
