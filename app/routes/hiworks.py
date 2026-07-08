"""하이웍스 CID 주소록 조회 API.

- POST /hiworks/lookup      : 번호 배열 → {번호: 표시명} (발송 수신자 입력 등 클라이언트용)
- POST /hiworks/test        : 설정된 MySQL 접속 테스트 (admin)

조회는 외부 MySQL(cid_lookup)을 읽기 전용으로 본다. 실패는 격리되어 빈 결과를
반환하므로, 호출측은 이름이 없으면 번호를 그대로 쓰면 된다.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.deps import require_role, require_setup_complete, require_user
from app.db import get_db
from app.security.csrf import verify_csrf
from app.services.hiworks import _digits, lookup_names, test_connection

router = APIRouter(
    dependencies=[Depends(require_user), Depends(require_setup_complete)],
)


class LookupBody(BaseModel):
    """조회할 번호들. 형식 무관(내부에서 숫자만 추출)."""

    phones: list[str] = Field(default_factory=list, max_length=1000)


@router.post("/hiworks/lookup", dependencies=[Depends(verify_csrf)])
def api_hiworks_lookup(body: LookupBody, db: Session = Depends(get_db)) -> dict:
    """번호 배열 → {정규화번호: {name, grade, company, display}} 매핑.

    미설정·조회 실패 시 빈 맵(격리). 호출측은 매칭 없으면 번호 그대로 사용.
    """
    cid = lookup_names(db, body.phones)
    return {"data": cid}


@router.post(
    "/hiworks/test",
    dependencies=[Depends(require_role("admin")), Depends(verify_csrf)],
    response_model=None,
)
def api_hiworks_test(db: Session = Depends(get_db)) -> dict | JSONResponse:
    """설정된 MySQL 접속 테스트 — 성공 시 주소록 건수, 실패 시 422."""
    ok, message = test_connection(db)
    if ok:
        return {"data": {"ok": True, "message": message}}
    return JSONResponse(
        {"error": {"code": "connect_failed", "message": message}},
        status_code=422,
    )


__all__ = ["router", "_digits"]
