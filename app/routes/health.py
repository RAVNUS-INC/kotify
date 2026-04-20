"""헬스체크 라우트 — 인증 없음."""
from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db

router = APIRouter()


def _compute_git_hash() -> str:
    """현재 실행 중인 프로세스의 git 해시. 프로세스 시작 시 1회 계산."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent.parent),
            timeout=2,
        )
        return (result.stdout or "").strip() or "unknown"
    except Exception:
        return "unknown"


# 모듈 로드 시점 = uvicorn 프로세스 시작 시점. systemctl restart 이후
# 새 프로세스가 이 변수를 새로 계산하므로 재시작 전후 비교로 "업데이트 완료"
# 감지가 가능하다.
_GIT_HASH: str = _compute_git_hash()


@router.get("/healthz")
async def healthz(db: Session = Depends(get_db)) -> JSONResponse:
    """DB ping + 현재 코드 버전 반환."""
    try:
        db.execute(text("SELECT 1"))
        return JSONResponse({"status": "ok", "version": _GIT_HASH})
    except Exception as exc:
        return JSONResponse(
            {"status": "error", "detail": str(exc), "version": _GIT_HASH},
            status_code=503,
        )
