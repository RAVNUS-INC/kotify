# Phase 6 — 핵심 발견 심층 검증

> 목적: 금전 직결 4건(C1·C2·C4·C5)을 코드 레벨로 끝까지 추적해 확정/반증.
> 원칙: 에이전트 주장도 가설로 보고 grep·코드·문서로 교차검증. 거짓 양성은 명시 철회.

---

## 검증 요약

| 발견 | 에이전트 주장 | 검증 판정 | 비고 |
|------|--------------|----------|------|
| C1 멱등키 부재 | 중복발송·이중과금 | ✅ **확정** | 라우트~서비스 전 경로 확인 |
| C2 수신자 dedup 미적용 | 입력중복 발송 | ✅ **확정** | dead code + 발송경로 dedup 0 |
| C4 단문 과금 불일치 | 17원 과금 | ✅ **확정(격상)** | 단순오타 아닌 명세-구현 3중 모순 |
| C5 웹훅 재조정 dead | 영구 PENDING | ✅ **확정** | 폴링/스케줄러 전무 |
| (자기검증) chat_session_cost | 세션과금 dead 의심 | ❌ **반증/철회** | chat.py:312에서 정상 사용 |

---

## C1 — 캠페인 멱등키 부재 ✅ 확정

**추적 경로**:
- `campaigns.py:295` `create_campaign` → `dispatch_campaign(recipients=list(body.recipients), ...)` 직접 호출. Idempotency-Key 등 중복 방지 입력 없음.
- `compose.py:416` `dispatch_campaign`은 매 호출마다 `Campaign(...)` 새로 INSERT(`db.add(campaign)` 437).
- `compose.py:143` `_make_cli_key = f"c{campaign_id}-{chunk}-{idx}"` → cliKey가 campaign_id에 종속.

**결론**: 동일 본문·수신자를 재요청하면 새 campaign_id → 전혀 다른 cliKey 집합 → msghub의 cliKey 기반 10분 중복차단마저 우회. **더블클릭/프론트 재시도 = 전체 캠페인 중복 발송·이중 과금.** (CRITICAL 유효)

---

## C2 — 수신자 중복 제거 미적용 ✅ 확정

**추적 경로**:
- `campaigns.py:301` `recipients=list(body.recipients)` — POST 원본 배열 그대로 전달.
- `compose.py:214, 451` `chunks = [recipients[i:i+CHUNK_SIZE] ...]` — dedup 없이 청크 분할.
- `compose.py:599` `resolve_recipients`는 호출처 0 (grep 확인). **게다가 이 함수 자체도 dedup을 안 함** — `phones = [c.phone for c in contacts if c.phone]` 단순 펼치기(611, 623). 즉 에이전트가 "dedup 함수"라 칭했으나 실제론 dedup 기능조차 없는 dead code.

**결론**: 발송 경로 어디에도 phone 중복 제거가 없음. 엑셀 복붙 등으로 동일 번호 2회 입력 시 2회 발송·과금. (CRITICAL 유효, 단 "resolve_recipients가 dedup을 한다"는 전제는 부정확 — dedup 로직 자체를 신규 추가해야 함)

---

## C4 — 단문 과금: 명세-구현-과금표 3중 불일치 ✅ 확정 (격상)

에이전트는 "17원 과금 버그"로 봤으나, 검증 결과 **과금 모델 설계 자체의 모순**으로 격상.

### 세 출처가 서로 다름

| 출처 | 단문(≤90B) 정의 | 단가 |
|------|----------------|------|
| `SPEC.md:308`, `msghub-migration-spec.md:46`, `msghub-ux-changes.md:76` | RCS **양방향(CHAT)** → SMS fallback | 8원 → 9원 |
| `compose.py:93-99` 주석 | 양방향은 outbound 불가 → **단방향 RPSSAXX001** | "9원" |
| `codes.py:36-46` PRICE_TABLE | `(RCS,CHAT)=8`, `(RCS,SMS)=17`("미사용"), `(SMS,SMS)=9` | — |

### 근본 결함
1. **명세의 전제 오류**: SPEC은 outbound 단문을 "RCS 양방향(CHAT) 8원"으로 정의하나, `compose.py:93-97`은 "양방향 CHAT은 replyId 없는 outbound에선 29003/404로 거부 → 단방향 써야 함"이라 명시. **즉 SPEC이 약속한 '양방향 8원'은 outbound 브로드캐스트에서 원천적으로 불가능.**
2. **과금표 공백**: 단방향 RPSSAXX001이 RCS로 성공 전달될 때 `calculate_cost(item.ch, item.product_code)`(report.py:196)는 webhook이 준 (ch,productCode)를 그대로 PRICE_TABLE 조회. 단방향 RCS 성공을 **9원으로 매길 키가 PRICE_TABLE에 없음**. 후보는 `(RCS,CHAT)=8`(양방향 전용) 또는 `(RCS,SMS)=17`(개발자가 "미사용" 가정).
3. **견적-청구 분리**: `_ESTIMATE_MAP["short"]=((RCS,CHAT)=8,(SMS,SMS)=9)`로 견적은 8~9원인데, 실청구는 위 공백으로 17원이 될 수 있음. 게다가 `estimate_cost`는 **호출처 0(dead)**이라 발송 직후 화면은 항상 0원(M1).

### 외부 확인 결과 (2026-05-30, LG U+ 공식 단가) — 결론 반전 ⭐

LG U+ 메시지허브 솔루션 페이지(lguplus.com/biz/.../message-hub)의 공식 단가를 VAT 별도로 환산하니 PRICE_TABLE과 **정확히 일치**:

| 채널 | U+ 공식(VAT 포함) | ÷1.1 (VAT 별도) | PRICE_TABLE | 일치 |
|------|------------------|----------------|-------------|------|
| RCS 단문 | 18.7원 | **17원** | `(RCS,SMS)=17` | ✅ |
| RCS 장문 | 29.7원 | 27원 | `(RCS,LMS)=27` | ✅ |
| RCS 템플릿 | 8.8원 | 8원 | `(RCS,CHAT)=8` | ✅ |
| SMS | 9.9원 | 9원 | `(SMS,SMS)=9` | ✅ |
| LMS | 29.7원 | 27원 | `(LMS,LMS)=27` | ✅ |
| MMS | 93.5원 | 85원 | `(MMS,MMS)=85` | ✅ |

**§6.3 + 외부 단가 종합 → 진짜 결론 (에이전트 가설 반전):**
- 단방향 `RPSSAXX001`의 productCode = **SMS**(§6.3 line 401,420). RCS 단말 성공 시 리포트 ch=RCS, productCode=SMS → `(RCS,SMS)=17`.
- **이 17원은 U+ 공식 RCS 단문 실단가다. `calculate_cost`는 정확하다.** "과다청구 버그"가 아니다.
- **진짜 결함은 견적·문서**: SPEC/README/`_ESTIMATE_MAP["short"]`가 단문을 "양방향 8원"으로 안내하나, 양방향(CHAT)은 outbound에 사용 불가(compose.py:93). 사용자에게 8원 견적 → 실제 17원 청구(약 2배 괴리).
- ⚠️ **수정 방향 반전**: ❌ "PRICE_TABLE 17→9 수정"(이러면 U+ 청구보다 과소 집계) → ✅ **견적/문서를 단방향 RCS 단문=17원으로 정정**(또는 단문도 양방향 8원 발송이 가능한지 U+에 확인).

> 교훈: 외부 확인 없이 17원을 9원으로 고쳤다면 정산이 U+ 실청구보다 적게 잡히는 더 큰 버그를 유발했을 것. **"버그처럼 보이는 정상값"을 외부 근거로 가려낸 사례.**

---

## C5 — 웹훅 유실 재조정 경로 부재 ✅ 확정

**추적 경로**:
- `query_sent`(client.py:423), `process_sent_query`(report.py:82), `get_daily_stats`(client.py:447) 모두 호출처 0 (grep 확인).
- `_refresh_campaign_counters`(report.py:211)는 webhook 처리 트랜잭션에서만 호출.
- 스케줄러/백그라운드 작업 없음(`apscheduler|create_task|cron` 0 hits).

**결론**: 배달 리포트 100% 웹훅 의존 + 유실 시 능동 회수 수단이 전부 dead. 웹훅 1배치만 유실돼도 해당 Message 영구 PENDING, campaign 카운터·비용 미갱신. (CRITICAL 유효)

---

## 자기검증 — chat_session_cost ❌ 반증/철회

리뷰 중 "RCS 양방향 세션 과금(24h 10건→80원 상한)이 미배선 아닌가" 의심했으나:
- `chat.py:312` `billed = chat_session_cost(out_count)` — **정상 사용 확인**.
- 캠페인 발송(compose→report)이 세션과금을 안 쓰는 것은 **설계상 맞음**: outbound는 단방향이라 양방향(CHAT) 세션 과금 대상이 아님. 양방향 과금은 대화 답장(chat) 경로에만 적용.

→ 이 의심은 **철회**한다. (단, `estimate_cost`·`resolve_recipients`·`validate_reply_content`의 dead 판정은 grep으로 재확인되어 유효)

---

## 검증 결론

심층 검증 대상 4건(C1·C2·C4·C5) **모두 확정**, C4는 단순 버그에서 **과금 모델 설계 모순**으로 격상. 자기검증으로 거짓 양성 1건(세션과금) 철회. → REVIEW-SUMMARY의 🔴 우선순위(중복발송·과금)는 **행동에 옮길 신뢰도 확보**됨.

**유일한 외부 의존**: C4의 단방향 RCS 성공 시 실단가 — U+ msghub 공식 단가표 확인 후 PRICE_TABLE 정정 필요.
