"""백그라운드 폴링 워커.

NCP에서 발송 결과를 주기적으로 조회하여 messages 테이블을 갱신한다.
단일 uvicorn 프로세스 전제 (워커 인스턴스 1개).
파일 락으로 다중 인스턴스 기동을 방지한다 (#11).
"""
from __future__ import annotations

import asyncio
import fcntl
import logging
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Campaign, Message, NcpRequest

logger = logging.getLogger(__name__)

# Backoff 스케줄 (poll_count → 다음 폴링까지 초)
_BACKOFF: list[int] = [5, 10, 30, 60]  # 0,1,2,3
_BACKOFF_4_9 = 300   # 4-9
_BACKOFF_10_PLUS = 900  # 10+

# 메인 루프 sleep 간격 (초)
_TICK = 5

# 발송 후 타임아웃 (초)
_TIMEOUT_SECONDS = 3600  # 1시간


def _backoff_interval(poll_count: int) -> int:
    """poll_count 기준 다음 폴링까지 대기 시간(초)를 반환한다."""
    if poll_count < len(_BACKOFF):
        return _BACKOFF[poll_count]
    if poll_count < 10:
        return _BACKOFF_4_9
    return _BACKOFF_10_PLUS


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


class Poller:
    """NCP 발송 결과 폴링 워커.

    Args:
        db_factory: 호출 시 Session을 반환하는 팩토리 함수.
        ncp_client_factory: 호출 시 NCPClient를 반환하는 팩토리 함수.
            None 반환 시 해당 tick 스킵.
    """

    def __init__(
        self,
        db_factory: Callable[[], Session],
        ncp_client_factory: Callable[[], "NCPClient | None"],  # type: ignore[name-defined]  # noqa: F821
    ) -> None:
        self._db_factory = db_factory
        self._ncp_client_factory = ncp_client_factory
        self._running = False
        self._task: asyncio.Task | None = None
        # 강제 새로고침 큐: campaign_id set
        self._force_refresh: set[int] = set()
        # 파일 락 (#11)
        self._lock_fd = None

    async def start(self) -> None:
        """메인 폴링 루프를 백그라운드 태스크로 시작한다.

        파일 락으로 다중 인스턴스 기동을 방지한다 (#11).
        """
        from app.config import settings

        # db_path 부모 디렉토리를 락 파일 위치로 사용 (R2: hasattr 분기 제거)
        lock_path = settings.db_path.parent
        lock_file = lock_path / "poller.lock"
        try:
            lock_file.parent.mkdir(parents=True, exist_ok=True)
            self._lock_fd = open(lock_file, "w")  # noqa: WPS515
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logger.warning("다른 폴러 인스턴스가 실행 중입니다. 이 인스턴스는 폴링을 건너뜁니다.")
            if self._lock_fd:
                self._lock_fd.close()
                self._lock_fd = None
            return
        except Exception as exc:
            logger.warning("폴러 파일 락 획득 실패 (계속 진행): %s", exc)

        self._running = True
        self._task = asyncio.create_task(self._loop(), name="poller")
        logger.info("폴링 워커 시작")

    async def stop(self) -> None:
        """폴링 루프를 graceful하게 종료한다."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        # 파일 락 해제 (#11)
        if self._lock_fd is not None:
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
                self._lock_fd.close()
            except Exception:
                pass
            self._lock_fd = None
        logger.info("폴링 워커 종료")

    def add_force_refresh(self, campaign_id: int) -> None:
        """특정 캠페인을 다음 tick에 강제 폴링하도록 큐에 추가한다."""
        self._force_refresh.add(campaign_id)

    async def _loop(self) -> None:
        """메인 폴링 루프."""
        while self._running:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception("폴링 루프 예외: %s", exc)
            await asyncio.sleep(_TICK)

    async def run_once(self) -> None:
        """한 사이클: 미완료 메시지가 있는 ncp_requests들을 폴링한다."""
        from app.ncp.client import NCPAuthError, NCPRateLimited

        ncp_client = self._ncp_client_factory()
        if ncp_client is None:
            return  # NCP 설정 미완료

        db = self._db_factory()
        try:
            await self._poll_cycle(db, ncp_client)
        except NCPRateLimited:
            logger.warning("NCP Rate Limited — 30초 대기")
            await asyncio.sleep(30)
        except NCPAuthError as exc:
            logger.error("NCP 인증 오류 — 1분 대기: %s", exc)
            await asyncio.sleep(60)
        except Exception as exc:
            logger.exception("폴링 사이클 예외: %s", exc)
        finally:
            db.close()

    async def _poll_cycle(self, db: Session, ncp_client: object) -> None:
        """실제 폴링 사이클 구현.

        각 ncp_request를 독립적으로 처리하고 청크마다 커밋한다 (#4).
        한 청크 실패해도 다른 청크는 계속 처리된다.
        """
        now = _now()

        # 미완료 메시지가 있는 ncp_requests 조회
        final_statuses = ("COMPLETED", "TIMEOUT", "UNKNOWN")
        stmt = (
            select(NcpRequest)
            .join(Message, Message.ncp_request_id == NcpRequest.id)
            .where(Message.status.notin_(final_statuses))
            .where(NcpRequest.request_id.isnot(None))
            .distinct()
        )
        ncp_requests: list[NcpRequest] = list(db.execute(stmt).scalars().all())

        # 강제 새로고침 큐 처리
        force_ids = self._force_refresh.copy()
        self._force_refresh.clear()

        for ncp_req in ncp_requests:
            try:
                await self._poll_one(db, ncp_req, ncp_client, force_ids, now)
                db.commit()  # 청크 단위 커밋 (#4)
            except Exception as exc:
                db.rollback()
                logger.warning(
                    "폴링 청크 실패 (request_id=%s): %s", ncp_req.request_id, exc
                )
                continue

    async def _poll_one(
        self,
        db: Session,
        ncp_req: NcpRequest,
        ncp_client: object,
        force_ids: set[int],
        now: datetime,
    ) -> None:
        """단일 ncp_request의 폴링 처리."""
        campaign_id = ncp_req.campaign_id
        force = campaign_id in force_ids

        # 해당 ncp_request의 messages 조회
        final_statuses = ("COMPLETED", "TIMEOUT", "UNKNOWN")
        messages = list(
            db.execute(
                select(Message).where(
                    Message.ncp_request_id == ncp_req.id,
                    Message.status.notin_(final_statuses),
                )
            ).scalars().all()
        )
        if not messages:
            return

        # 타임아웃 체크: 발송 시점 + 1시간 경과
        sent_at = _parse_dt(ncp_req.sent_at)
        if sent_at:
            # timezone-aware 비교
            if sent_at.tzinfo is None:
                sent_at = sent_at.replace(tzinfo=timezone.utc)
            if now - sent_at > timedelta(seconds=_TIMEOUT_SECONDS):
                for msg in messages:
                    msg.status = "TIMEOUT"
                    msg.last_polled_at = now.isoformat()
                db.flush()
                await self._update_campaign(db, campaign_id)
                return

        # Backoff 체크: 최소 poll_count 기준
        min_poll_count = min(msg.poll_count for msg in messages)
        backoff_secs = _backoff_interval(min_poll_count)

        # 마지막 폴링 시간 체크
        last_polled_strs = [msg.last_polled_at for msg in messages if msg.last_polled_at]
        if last_polled_strs and not force:
            latest_polled = max(_parse_dt(s) for s in last_polled_strs if _parse_dt(s))
            if latest_polled:
                if latest_polled.tzinfo is None:
                    latest_polled = latest_polled.replace(tzinfo=timezone.utc)
                if (now - latest_polled).total_seconds() < backoff_secs:
                    return  # 아직 backoff 시간이 안 됨

        # NCP 조회
        list_resp = await ncp_client.list_by_request_id(ncp_req.request_id)

        # message_id 기준 업데이트
        msg_by_id: dict[str, Message] = {
            msg.message_id: msg for msg in messages if msg.message_id
        }
        # #19: 같은 to_number 여러 개 → list로 관리, pop-on-use
        msg_by_to: dict[str, list[Message]] = {}
        for msg in messages:
            msg_by_to.setdefault(msg.to_number, []).append(msg)

        poll_time = _now().isoformat()

        for item in list_resp.messages:
            # message_id 우선 매칭, 없으면 to_number 리스트에서 pop
            msg = msg_by_id.get(item.message_id)
            if msg is None:
                candidates = msg_by_to.get(item.to, [])
                if candidates:
                    msg = candidates.pop(0)
            if msg is None:
                continue

            # message_id 업데이트 (첫 폴링 시 수집)
            if not msg.message_id and item.message_id:
                msg.message_id = item.message_id

            msg.status = item.status
            msg.result_status = item.status_name
            msg.result_code = item.status_code
            msg.result_message = item.status_message
            msg.telco_code = item.telco_code
            msg.complete_time = item.complete_time
            msg.last_polled_at = poll_time
            msg.poll_count = (msg.poll_count or 0) + 1

        db.flush()
        await self._update_campaign(db, campaign_id)

    async def _update_campaign(self, db: Session, campaign_id: int) -> None:
        """캠페인의 카운터와 state를 재계산하여 업데이트한다.

        R5: 전체 메시지 ORM 로드 대신 COUNT 쿼리로 처리 (1,000명 캠페인 OOM 방지).
        """
        from sqlalchemy import func as _func

        campaign = db.get(Campaign, campaign_id)
        if campaign is None:
            return

        # 성공 건수: result_status == "success"
        ok_count = db.execute(
            select(_func.count()).select_from(Message).where(
                Message.campaign_id == campaign_id,
                Message.result_status == "success",
            )
        ).scalar_one()

        # 실패 건수: final state이고 success가 아닌 것
        fail_count = db.execute(
            select(_func.count()).select_from(Message).where(
                Message.campaign_id == campaign_id,
                Message.status.in_(("COMPLETED", "TIMEOUT", "UNKNOWN")),
                Message.result_status != "success",
            )
        ).scalar_one()

        # 미완료 건수: final state에 도달하지 않은 것
        pending_count = db.execute(
            select(_func.count()).select_from(Message).where(
                Message.campaign_id == campaign_id,
                Message.status.notin_(("COMPLETED", "TIMEOUT", "UNKNOWN")),
            )
        ).scalar_one()

        campaign.ok_count = ok_count
        campaign.fail_count = fail_count
        campaign.pending_count = pending_count

        # 모든 메시지가 final state에 도달했는지 확인
        all_final = pending_count == 0

        # PARTIAL_FAILED → 최종 fail/success 카운트로 state 결정 (R7)
        if all_final and campaign.state in ("DISPATCHED", "DISPATCHING", "PARTIAL_FAILED"):
            if fail_count == 0:
                campaign.state = "COMPLETED"
            elif ok_count == 0:
                campaign.state = "FAILED"
            else:
                # 일부 성공, 일부 실패 → PARTIAL_FAILED 유지
                campaign.state = "PARTIAL_FAILED"
            campaign.completed_at = _now().isoformat()

        db.flush()
