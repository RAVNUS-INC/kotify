"""알림센터 API — S15.

Phase 9a: mock 20개. mark-read는 in-memory flip.
"""
from __future__ import annotations

import asyncio
from typing import List, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


_notif_lock = asyncio.Lock()


_MOCK_NOTIFICATIONS: List[dict] = [
    {"id": "n-001", "kind": "send_result", "level": "success", "title": "4월 공지사항 발송 완료", "subtitle": "334/342 도달 · 12 회신", "createdAt": "2026-04-21 14:02", "unread": True, "href": "/campaigns/c-001"},
    {"id": "n-002", "kind": "send_result", "level": "info", "title": "마케팅 뉴스레터 #12 발송 중", "subtitle": "187/500 도달 (진행)", "createdAt": "2026-04-21 13:55", "unread": True, "href": "/campaigns/c-002"},
    {"id": "n-003", "kind": "security", "level": "warning", "title": "새 API 키 발급", "subtitle": "김민재가 '배포 서버' 키를 생성했습니다", "createdAt": "2026-04-21 11:22", "unread": True, "href": "/settings/developers"},
    {"id": "n-004", "kind": "send_result", "level": "error", "title": "월간 리포트 발송 실패", "subtitle": "msghub 인증 오류 — 892명 미발송", "createdAt": "2026-04-20 18:30", "unread": True, "href": "/campaigns/c-005"},
    {"id": "n-005", "kind": "system", "level": "info", "title": "조직 설정 변경", "subtitle": "김운영이 조직명을 수정했습니다", "createdAt": "2026-04-21 10:15", "unread": False, "href": "/settings/org"},
    {"id": "n-006", "kind": "send_result", "level": "success", "title": "인사팀 공지 발송 완료", "subtitle": "121/124 도달 · 8 회신", "createdAt": "2026-04-21 09:20", "unread": False, "href": "/campaigns/c-004"},
    {"id": "n-007", "kind": "security", "level": "error", "title": "로그인 실패", "subtitle": "이전직원 계정에서 3회 실패 · IP 198.51.100.55", "createdAt": "2026-04-17 16:45", "unread": False, "href": "/audit?action=LOGIN_FAILED"},
    {"id": "n-008", "kind": "send_result", "level": "warning", "title": "긴급 시스템 점검 캠페인 취소", "subtitle": "박지훈이 발송 시작 전 취소했습니다", "createdAt": "2026-04-20 15:00", "unread": False, "href": "/campaigns/c-006"},
    {"id": "n-009", "kind": "system", "level": "info", "title": "주간 리포트 초안 저장됨", "subtitle": "김운영의 초안이 draft로 저장되었습니다", "createdAt": "2026-04-21 12:00", "unread": False, "href": "/campaigns/c-010"},
    {"id": "n-010", "kind": "billing", "level": "warning", "title": "월 비용 80% 도달", "subtitle": "현재 ₩800,000 / 예산 ₩1,000,000", "createdAt": "2026-04-20 09:00", "unread": False, "href": "/reports"},
    {"id": "n-011", "kind": "send_result", "level": "success", "title": "카톡 이벤트 안내 발송 완료", "subtitle": "430/456 도달 · 15 회신", "createdAt": "2026-04-20 16:00", "unread": False, "href": "/campaigns/c-011"},
    {"id": "n-012", "kind": "security", "level": "info", "title": "웹훅 활성화", "subtitle": "김민재가 Slack 웹훅을 추가했습니다", "createdAt": "2026-04-20 14:30", "unread": False, "href": "/settings/developers"},
    {"id": "n-013", "kind": "system", "level": "info", "title": "VIP 그룹 동기화 완료", "subtitle": "CSV 업로드 · 128명 추가", "createdAt": "2026-04-18 10:30", "unread": False, "href": "/groups/g-vip"},
    {"id": "n-014", "kind": "security", "level": "warning", "title": "발신번호 등록 요청", "subtitle": "070-1234-5678 승인 대기 중", "createdAt": "2026-04-18 15:22", "unread": False, "href": "/numbers?status=pending"},
    {"id": "n-015", "kind": "send_result", "level": "success", "title": "단체 회식 공지 발송 완료", "subtitle": "140/142 도달 · 11 회신", "createdAt": "2026-04-19 14:00", "unread": False, "href": "/campaigns/c-012"},
    {"id": "n-016", "kind": "system", "level": "info", "title": "멤버 초대", "subtitle": "김운영이 reader@ravnus.kr 초대", "createdAt": "2026-04-20 10:00", "unread": False, "href": "/settings/org"},
    {"id": "n-017", "kind": "billing", "level": "info", "title": "4월 청구서 준비 중", "subtitle": "예상 합계 ₩680,000", "createdAt": "2026-04-15 09:00", "unread": False, "href": "/reports"},
    {"id": "n-018", "kind": "security", "level": "warning", "title": "발신번호 반려", "subtitle": "010-1234-5678 — 소유확인 실패", "createdAt": "2026-04-10 11:00", "unread": False, "href": "/numbers?status=rejected"},
    {"id": "n-019", "kind": "send_result", "level": "success", "title": "점심 메뉴 투표 발송 완료", "subtitle": "61/62 도달 · 34 회신", "createdAt": "2026-04-21 11:00", "unread": False, "href": "/campaigns/c-008"},
    {"id": "n-020", "kind": "system", "level": "info", "title": "비활성 멤버 정리", "subtitle": "김운영이 former@ravnus.kr 비활성화", "createdAt": "2026-04-17 11:10", "unread": False, "href": "/settings/org"},
]


def _filter(rows: List[dict], kind: Optional[str], unread: Optional[bool]) -> List[dict]:
    if kind and kind != "all":
        rows = [r for r in rows if r.get("kind") == kind]
    if unread:
        rows = [r for r in rows if r.get("unread")]
    return rows


@router.get("/notifications")
async def list_notifications(
    kind: Optional[str] = None,
    unread: Optional[bool] = None,
) -> dict:
    rows = _filter(_MOCK_NOTIFICATIONS, kind, unread)
    # 최신순
    rows = sorted(rows, key=lambda r: r.get("createdAt", ""), reverse=True)
    unread_total = sum(1 for n in _MOCK_NOTIFICATIONS if n.get("unread"))
    return {
        "data": rows,
        "meta": {"total": len(rows), "unreadTotal": unread_total},
    }


@router.post("/notifications/{nid}/read")
async def mark_read(nid: str):
    async with _notif_lock:
        for n in _MOCK_NOTIFICATIONS:
            if n["id"] == nid:
                n["unread"] = False
                return {"data": {"id": nid, "unread": False}}
    return JSONResponse(
        {"error": {"code": "not_found", "message": "알림을 찾을 수 없습니다"}},
        status_code=404,
    )


@router.post("/notifications/read-all")
async def mark_all_read():
    async with _notif_lock:
        count = 0
        for n in _MOCK_NOTIFICATIONS:
            if n.get("unread"):
                n["unread"] = False
                count += 1
    return {"data": {"readCount": count}}
