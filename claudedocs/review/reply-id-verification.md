# 양방향 답장 — moRecvDt·replyId 유효시간 스펙 검증 + 리포트 실패 대체 발송 채널

> 목적: 인계 문서(`HANDOFF-resume.md:32`)의 "양방향 발송은 replyId+moRecvDt 필수" 기록과
> replyId 유효시간을 공식 스펙으로 확인하고, 양방향 답장이 리포트에서 실패할 때의 대체 발송
> 채널을 정한다.
> 일자: 2026-09-15
>
> 출처
> - msghub 공식 가이드 (https://doc.msghub.uplus.co.kr): 2.3.2 통합 RCS 메시지 §1·§2,
>   2.3.1 RCS 메시지(android) §2, 2.8 메시지 리포트 §3, 2.9 결과코드, 5.2 MO
>   (`/rest-api/02메시지발송/020302rcs_integrated/` 등). 인계 문서가 가리킨
>   `/guide/d/rcs` 는 사이트 개편으로 404.
> - 이통 공통 중계사-통신사 RCS 발송규격 (MaaP FE 공통 규격서 v1.2.0,
>   https://biz-rcs-1.gitbook.io/rcs/): `/message`, `/momsg (webhook)`,
>   `/msgstatus (webhook)`, About(수정이력). msghub 는 이 규격의 중계사다.

---

## 판정

| 항목 | 결과 | 조치 |
|------|------|------|
| moRecvDt 필수 여부 | ❌ 요청 필드가 아님 — 인계 문서 기록이 스펙과 다름 | 코드 무변경, 요청 본문을 테스트로 고정 |
| replyId 유효시간 | ✅ 24시간 — 기존 창과 같음 | 만료 직전 30분은 양방향을 쓰지 않음 |
| 리포트 실패 대체 발송 | 일반 SMS → **단방향 RCS + fbInfoLst SMS** | webhook 대체 발송 변경 |

---

## 근거

### 1. moRecvDt — 양방향 요청 필드가 아니다

- msghub 2.3.2 §2 `POST /rcs/bi/v1.1` Request Body 표의 필수(●) 필드는 replyId, cliKey(20자),
  messagebaseId, chatbotId(40자), telco, phone, body(description), header('0'만)이다. 선택
  필드는 agency, campaignId, deptCode, buttons, chipList, brandId/brandKey/productCode(대행사).
  **moRecvDt 행은 없다.** 2.3.1(android) §2 도 필수 필드가 같고(header 0/1, footer·copyAllowed
  선택이 더 있을 뿐) moRecvDt 는 없다.
- 상위 규격 `/message` 도 수신 시각 필드가 없다(필수: agencyId, agencyKey, body, brandKey,
  chatbotId, clientMsgId, header, messagebaseId, userContact / 선택: replyId 등).
- moRecvDt 는 **MO 쪽** 필드다 — 5.2 MO 웹훅 `moLst[].moRecvDt`(수신 일시), 운영에서 받은
  `rcsBiLst` 페이로드(`tests/test_msghub_schemas.py`). 인계 문서의 경로 `/msg/v1.1/bi/rcs` 도
  현행 문서에 없어, MO 페이로드 필드와 섞인 기록으로 보인다. 결론(양방향은 MO 응답 전용,
  outbound 8원 불가)은 그대로 유효.
- 고정: `tests/test_rcs_chat_request.py` — 요청 본문 키 = 스펙 필수 필드 집합.

### 2. replyId — 24시간 유효, 만료 직전은 쓰지 않는다

- 상위 규격 `/message` 의 replyId 설명: "전달받은 replyId 는 24시간 유효함." `/momsg` 의
  replyId 설명도 같은 유효시간을 적고, 중계사가 세션 메시지를 보내려면 이 값을 `/message` 의
  replyId 로 넣어야 한다고 한다.
- msghub 문서엔 유효시간이 없고, 2.9 결과코드에 replyId 실패만 있다: 55713(replyId 사용 횟수
  초과), 55715(replyId 가 존재하지 않음). 56007(RCS 세션 만료로 발송 실패)도 있다.
- 사용 횟수: 상위 규격 1.1.7 수정이력은 replyId 의 세션 유효시간을 바꾸면서 ceiling(상한)
  정책을 없앴다고 적고 있어, 현행 규격엔 횟수 상한이 없다. msghub 표에 55713 이 남아 있어
  msghub 자체 상한인지는 미확인(아래 미해결 2).
- 과금: `/msgstatus` 의 bill 필드 설명 — replyId 를 넣어 보낸 세션 메시지는 이통사 세션시간
  (예: 24시간) 기준 최대 N건까지만 과금되고, 세션 메시지 발송 실패는 항상 비과금. 기존
  `CHAT_SESSION_*` 과금 모델과 맞고, 실패한 양방향 + 대체 발송이 이중 과금되지 않는다.
- 조치 (`app/msghub/codes.py`, `app/services/chat.py:_fresh_reply_id`)
  - 과금 세션 창(`CHAT_SESSION_WINDOW_HOURS`)과 replyId 유효시간은 규칙이 달라
    `REPLY_ID_VALID_HOURS = 24` 로 분리.
  - 판정 = MO 수신 시각(mo_recv_dt, 없으면 received_at)부터 24h − 30분
    (`REPLY_ID_SAFETY_MARGIN_MINUTES`). 유효시간은 중계사가 받은 때부터 세는데, 우리 요청은
    msghub 를 거쳐 이통사에 늦게 닿고 서버 간 시각 차이도 있어 경계에 딱 맞추면 만료된
    replyId 가 나간다(리포트 실패 → 대체 발송까지 지연). 여유 안의 답장은 단방향 RCS(17원)로
    나가 건당 최대 9원 더 들지만, 대부분의 답장은 MO 후 몇 분~몇 시간 안이라 영향이 작다.
- 고정: `tests/test_send_reply.py::test_reply_id_near_expiry_goes_oneway`.

### 3. 리포트 실패 대체 발송 — 단방향 RCS

- 양방향 요청 표엔 fbInfoLst 가 없다 → msghub 가 대체 발송하지 않으므로 webhook 이 직접
  보내야 한다(기존 구조 유지).
- 단방향 RCS(2.3.2 §1)는 fbInfoLst(SMS/MMS, 메인 채널과 달라야 함)로 msghub 가 대체 발송한다.
  RCS 를 못 받는 단말이면 SMS 로 도달하므로 도달성은 일반 SMS 이상이다.
- 결정: 대체 발송 = 단방향 RCS(RPSSAXX001) + fbInfoLst SMS. RCS 요청이 거부되면
  (`MsghubBadRequest`) 직접 SMS — `_dispatch_rcs_chunks` 와 같은 순서. 즉시 실패 경로
  (`send_reply` → `dispatch_campaign`)와 같은 채널이라 운영자가 고른 RCS 가 유지된다.
  구현: `app/services/compose.py:dispatch_chat_fallback`, `app/routes/webhook.py`.
- cliKey: 단방향 RCS `{원본}-rcs-fb`, 직접 `{원본}-fb`. 둘 다 `-fb` 로 끝나 재대체 방지
  가드(`report.process_report`)가 그대로 동작하고, 표시는 접미사로 가른다
  (`chat.outbound_channel`, 캠페인 상세 수신자 상태). recvInfoLst cliKey 는 30자 이내.
- 멱등성: 리포트 처리와 대체 발송은 한 트랜잭션(기존 구조 유지). msghub 는 400·응답 지연 시
  리포트를 10초 간격으로 재전송하므로 다음 경합을 처리한다(독립 리뷰에서 발견·보강).
  - 발송 접수 뒤 커밋 실패 → 롤백·400 → 재처리 때 같은 cliKey 는 29005(중복발송)/29024(중복키)로
    거부된다. 이미 접수된 것이므로 다음 단계로 넘어가지 않고 리포트를 기다린다(RCS·SMS 이중
    발송 방지). 10분 중복 규칙은 `msghub-migration-spec.md §2.3·§6.7`(같은 날 10분) 기준 — 현행
    공식 페이지에서 해당 문구는 다시 찾지 못했다.
  - 커밋된 뒤 원본 실패 리포트 재전송 → cliKey 가 이미 바뀐 원본의 리포트는 건너뛴다
    (`report._superseded_by_fallback`). cliKey 가 있는데 맞는 행이 없는 리포트는 phone 보조매칭을
    하지 않는다 — 같은 번호로 새로 보낸 다른 답장에 원본 실패가 붙어 엉뚱한 대체 발송이 나갔다.
  - 롤백 사이에 대체 발송 리포트가 먼저 도착 → 원본 키 행에 매칭하고 키를 대체 발송 키로 맞춘다
    (`report._fallback_base_key`) — 실패 리포트여도 다시 대체 발송하지 않는다.
  - 29002(CPS 초과)는 요청 전체 거부(접수 0, `c3-verification.md`)라 FAILED 로 버리지 않고
    다시 던져 롤백·400 → 재전송 때 다시 보낸다. msghub 클라이언트가 없을 때도 400.
- 거부가 아닌 발송 오류(5xx·타임아웃 등)는 접수 여부를 알 수 없어 직접 SMS 로 넘기지 않고
  FAILED 로 남긴다(기존 정책). 이때 캠페인 집계를 다시 계산한다 — 이전엔 FAILED 로 바꾸고
  집계를 갱신하지 않아 캠페인이 pending 1건·DISPATCHED 로 남았다. 타임아웃이었는데 실제론 접수돼
  늦게 성공 리포트가 오면, 실패 0건이 된 PARTIAL_FAILED/FAILED 캠페인을 COMPLETED 로 보정한다
  (`_refresh_campaign_counters` — 대시보드는 PARTIAL_FAILED 를 '실패'로 보여 준다).
- 고정: `tests/test_report_fallback.py`(21건), `tests/test_reply_channel_default.py`. 각 보강을
  하나씩 되돌리면 해당 테스트가 실패함을 확인했다.

---

## 미해결 (U+ 확인 또는 운영 로그 필요)

1. **telco 필수인데 빈 문자열로 보냄.** 2.3.2 §2 는 telco 를 필수로 표시하지만 RCS 양방향 MO
   (`rcsBiLst`)엔 telco 가 없어 넘길 값이 없다(`client.send_rcs_chat` 은 `""`). 빈 값 처리는
   문서에 없다. 2.9 에 29022(자사 고객 아님 — 타 이통사 발송요청)가 있어, 이통사가 비거나
   틀리면 타사 고객에게 보낸 양방향 답장이 리포트에서 실패할 수 있다. 이 경우 이번 변경으로
   답장은 단방향 RCS 로 전달되지만, 양방향(8원)은 계속 실패한다.
   확인: 운영 로그의 `양방향 답장 리포트 실패 → 단방향 RCS 대체 발송` 경고(code 포함)를 모아
   55715/29022 비중과 이통사 분포를 보고(msghub 콘솔에서 msgKey 로 이통사 확인), U+ 에 빈
   telco 처리 방식을 문의.
2. **replyId 사용 횟수.** msghub 55713 이 msghub 자체 상한인지. MO 1건에 답장을 여러 번 보내는
   흐름이 흔하므로 로그에서 55713 발생 여부 확인.
3. **FB_PENDING 재조정 없음.** `reconcile_pending_messages` 는 PENDING/REG/ING 만 조회해, 대체
   발송 리포트 웹훅이 유실되면 FB_PENDING 으로 남는다(기존과 같음, 이번 범위 밖).
4. **한 트랜잭션 구조의 남은 이중 발송 창 (설계 결정 필요).** 중복 코드 방어는 msghub 의 중복
   판정 창(같은 날 10분) 안에서만 유효하다. 발송 접수 뒤 커밋 실패가 10분 넘게 이어지거나 자정을
   넘기면, 또는 RCS 거부 → 직접 SMS 접수 → 커밋 실패 → 재처리 때 RCS 가 접수되면 두 건이 나간다.
   또 msghub 호출(최대 30초 × 2)이 리포트 처리 flush 이후, 즉 SQLite 쓰기 잠금을 쥔 채로 실행돼
   그동안 다른 쓰기(MO 저장 등)가 기본 5초 대기 후 실패할 수 있다(기존 SMS 대체와 같은 구조).
   근본 해결: 대체 발송 의도(FB_PENDING + 새 cliKey)를 발송 전에 커밋하고, 발송은 트랜잭션 밖에서
   한 뒤 결과를 따로 커밋, reconcile 이 FB_PENDING 을 조회. 요청받은 "리포트 처리와 한 트랜잭션"
   구조를 바꾸는 일이라 이번엔 하지 않았다.
