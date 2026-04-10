"""백그라운드 폴링 워커.

NCP에서 발송 결과를 주기적으로 조회하여 messages 테이블을 갱신한다.
단일 uvicorn 프로세스 전제 (워커 인스턴스 1개).
파일 락으로 다중 인스턴스 기동을 방지한다 (#11).
"""
from __future__ import annotations

import asyncio
import fcntl
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import Campaign, Message, NcpRequest

# Phase B2 가드: 예약 캠페인은 아직 실행되지 않았으므로 정상 폴링 루프에서
# 완전히 제외한다. Phase B3에서 reserve-status 전환 로직이 RESERVED→DISPATCHING
# 전환을 수행하면 그 시점부터 자동으로 정상 폴링이 집는다.
_SKIP_CAMPAIGN_STATES: tuple[str, ...] = ("RESERVED",)

logger = logging.getLogger(__name__)

# Backoff 스케줄 (poll_count → 다음 폴링까지 초).
# NCP 공식 권장(ncp-research.md §4.7 폴링 패턴): 5초 → 15초 → 30초 → 1분 → 5분 → 30분.
_BACKOFF: list[int] = [5, 15, 30, 60]  # poll_count 0,1,2,3
_BACKOFF_4_9 = 300   # poll_count 4-9 (5분)
_BACKOFF_10_PLUS = 1800  # poll_count 10+ (30분). 70분 cutoff가 먼저 끊음.

# 메인 루프 sleep 간격 (초)
_TICK = 5

# force_refresh 쿨다운: 같은 campaign_id로 10초 내 재요청 무시 (NCP 429 예방).
_FORCE_REFRESH_COOLDOWN_SECONDS = 10

# 발송 후 70분 경과 시 결과 확인 포기 (공식 권장 60분 + 안전 버퍼 10분).
# 기준: ncp_request.sent_at — NCP는 API 이력을 90일만 보관하므로 무한 폴링 금지.
_CUTOFF_SECONDS = 70 * 60

# 포기 시 기록할 설명 메시지 (NCP statusMessage를 받지 못한 상태이므로 우리가 생성).
_UNCONFIRMED_MESSAGE = "70분 동안 NCP로부터 수신 확인을 받지 못했습니다"

# 더 이상 폴링하지 않는 최종 상태들.
# - COMPLETED: NCP가 결과(성공/실패)를 확정한 상태
# - UNKNOWN: 발송 API 호출 자체가 실패한 상태 (compose 단계)
# - DELIVERY_UNCONFIRMED: 70분 cutoff 도달 (수신 결과 확인 포기)
_FINAL_STATUSES: tuple[str, ...] = ("COMPLETED", "UNKNOWN", "DELIVERY_UNCONFIRMED")

def _backoff_interval(poll_count: int) -> int:
    """poll_count 기준 다음 폴링까지 대기 시간(초)를 반환한다."""
    if poll_count < len(_BACKOFF):
        return _BACKOFF[poll_count]
    if poll_count < 10:
        return _BACKOFF_4_9
    return _BACKOFF_10_PLUS


def _now() -> datetime:
    return datetime.now(UTC)


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
        ncp_client_factory: Callable[[], NCPClient | None],  # type: ignore[name-defined]  # noqa: F821
    ) -> None:
        self._db_factory = db_factory
        self._ncp_client_factory = ncp_client_factory
        self._running = False
        self._task: asyncio.Task | None = None
        # 강제 새로고침 큐: campaign_id set
        self._force_refresh: set[int] = set()
        # I4: 쿨다운 추적 — campaign_id → 마지막 force_refresh 수락 시각.
        # 10초 내 재요청은 무시하여 연타로 NCP 429를 유발하지 못하게 한다.
        self._force_refresh_at: dict[int, datetime] = {}
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

    def add_force_refresh(self, campaign_id: int) -> bool:
        """특정 캠페인을 다음 tick에 강제 폴링하도록 큐에 추가한다.

        쿨다운(10초) 내 재요청은 조용히 무시한다. 연타로 NCP 429를 유발할 수 없도록
        방어하는 것이 목적이다.

        Returns:
            실제로 큐에 추가됐으면 True, 쿨다운으로 무시됐으면 False.
        """
        now = _now()
        last = self._force_refresh_at.get(campaign_id)
        if last is not None:
            elapsed = (now - last).total_seconds()
            if elapsed < _FORCE_REFRESH_COOLDOWN_SECONDS:
                logger.debug(
                    "force_refresh 쿨다운: campaign_id=%d 무시 (last=%.1fs 전)",
                    campaign_id,
                    elapsed,
                )
                return False
        self._force_refresh.add(campaign_id)
        self._force_refresh_at[campaign_id] = now
        return True

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

        # 70분 cutoff sweep: sent_at 기준으로 만료된 메시지를 먼저 정리.
        # 이걸 먼저 해야 아래 ncp_requests 쿼리에서 만료된 것들이 제외된다.
        expired_campaign_ids = self._expire_stuck_messages(db, now)
        if expired_campaign_ids:
            db.commit()
            for cid in expired_campaign_ids:
                try:
                    await self._update_campaign(db, cid)
                    db.commit()
                except Exception as exc:
                    db.rollback()
                    logger.warning("만료 sweep 캠페인 집계 실패 (campaign_id=%s): %s", cid, exc)

        # 미완료 메시지가 있는 ncp_requests 조회.
        # 예약(RESERVED) 캠페인은 제외 — 아직 NCP가 발송을 실행하지 않은 상태.
        stmt = (
            select(NcpRequest)
            .join(Message, Message.ncp_request_id == NcpRequest.id)
            .join(Campaign, Campaign.id == NcpRequest.campaign_id)
            .where(Message.status.notin_(_FINAL_STATUSES))
            .where(NcpRequest.request_id.isnot(None))
            .where(Campaign.state.notin_(_SKIP_CAMPAIGN_STATES))
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
        messages = list(
            db.execute(
                select(Message).where(
                    Message.ncp_request_id == ncp_req.id,
                    Message.status.notin_(_FINAL_STATUSES),
                )
            ).scalars().all()
        )
        if not messages:
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
                    latest_polled = latest_polled.replace(tzinfo=UTC)
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
        matched_ids: set[int] = set()

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
            matched_ids.add(msg.id)

        # C3: NCP 응답에 포함되지 않은 메시지도 폴링은 "시도"된 것이므로
        # poll_count/last_polled_at을 증가시켜야 한다. 그렇지 않으면 해당 메시지의
        # poll_count가 영원히 0에 머물러 backoff가 _BACKOFF[0]=5초에 고정 — 핫루프.
        # NCP list 응답 누락은 70분 cutoff가 최종적으로 처리한다.
        for msg in messages:
            if msg.id in matched_ids:
                continue
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

        # 실패 건수: final state이고 success가 아닌 것.
        # SQL NULL 주의: `result_status != 'success'`는 NULL일 때 NULL로 평가되어 빠짐.
        # DELIVERY_UNCONFIRMED는 result_status=None이므로 IS NULL 조건을 OR로 명시.
        fail_count = db.execute(
            select(_func.count()).select_from(Message).where(
                Message.campaign_id == campaign_id,
                Message.status.in_(_FINAL_STATUSES),
                (Message.result_status != "success") | Message.result_status.is_(None),
            )
        ).scalar_one()

        # 미완료 건수: final state에 도달하지 않은 것
        pending_count = db.execute(
            select(_func.count()).select_from(Message).where(
                Message.campaign_id == campaign_id,
                Message.status.notin_(_FINAL_STATUSES),
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

    def _expire_stuck_messages(self, db: Session, now: datetime) -> set[int]:
        """70분 cutoff: sent_at 기준으로 만료된 미완료 메시지를 DELIVERY_UNCONFIRMED로 전환.

        NCP는 결과 확인이 보통 수초~수분 내 끝난다. 70분 넘게 결과가 확정되지
        않은 메시지는 폴링을 포기한다. 근거:
        - NCP 공식 권장 1시간 (ncp-research.md §4.7 폴링 패턴)
        - NCP API 이력 보관 90일 → 그 이후엔 조회 자체가 404
        - 무한 폴링 시 월 10,000건 quota 낭비

        Args:
            db: 세션
            now: 현재 시각 (UTC)

        Returns:
            영향받은 메시지의 campaign_id 집합. 호출자는 캠페인 카운터를 재집계해야 한다.
        """
        cutoff = now - timedelta(seconds=_CUTOFF_SECONDS)
        cutoff_iso = cutoff.isoformat()

        # 만료 대상 조회 (campaign_id 수집용)
        stale_rows = db.execute(
            select(Message.id, Message.campaign_id)
            .join(NcpRequest, Message.ncp_request_id == NcpRequest.id)
            .where(Message.status.notin_(_FINAL_STATUSES))
            .where(NcpRequest.sent_at < cutoff_iso)
        ).all()

        if not stale_rows:
            return set()

        stale_ids = [row[0] for row in stale_rows]
        affected_campaigns: set[int] = {row[1] for row in stale_rows}

        # 벌크 UPDATE로 한 번에 전환
        db.execute(
            update(Message)
            .where(Message.id.in_(stale_ids))
            .values(
                status="DELIVERY_UNCONFIRMED",
                result_message=_UNCONFIRMED_MESSAGE,
                last_polled_at=now.isoformat(),
            )
        )
        logger.info(
            "70분 cutoff: %d건을 DELIVERY_UNCONFIRMED로 전환 (campaigns=%s)",
            len(stale_ids),
            sorted(affected_campaigns),
        )
        return affected_campaigns
