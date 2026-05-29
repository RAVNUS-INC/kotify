# Phase 2 코드 리뷰 — 메시지 발송 파이프라인 (Critical Path)

리뷰 대상: `app/services/compose.py`, `app/services/chat.py`, `app/services/report.py`,
`app/routes/campaigns.py`, `app/routes/threads.py`, `app/routes/webhook.py`,
`app/msghub/{client,auth,codes,schemas}.py`, 보조: `app/models.py`, `app/util/{text,phone}.py`, `app/services/groups.py`

렌즈: 🧭 UX / ⚙️ 기능 / 🧹 코드품질 / 🔢 알고리즘
심각도: 🔴 CRITICAL(금전/오발송/중복발송/과금오류) / 🟠 HIGH / 🟡 MEDIUM / 🟢 LOW

> 본 영역은 금전·오발송 사고 직결 구간이므로 🔴🟠 항목은 모두 재현 시나리오를 포함한다.

---

## 🔴 CRITICAL

### C1
[🔴][⚙️ 기능] app/routes/campaigns.py:295-306 + app/services/compose.py:347-372 — POST /campaigns 에 멱등키가 없어 더블클릭/재시도 시 동일 수신자 중복 발송·이중 과금

근거:
- `create_campaign`은 `Idempotency-Key` 등 어떤 중복 방지 키도 받지 않는다 (grep: `Idempotency|idempotent|request_id` → 0 hits in campaigns.py/threads.py/client.py).
- `dispatch_campaign`은 매 호출마다 새 `Campaign`을 INSERT 하고(compose.py:416-437) 곧바로 msghub로 실발송한다. 동일 본문/수신자에 대한 중복 호출을 막는 가드가 전무하다.
- 발송 자체가 네트워크 왕복이라 수백 ms~수 초가 걸린다. 그 사이 사용자가 버튼을 두 번 누르거나, 프론트가 타임아웃 후 자동 재요청하면 두 개의 캠페인이 각각 끝까지 실발송된다.

재현 시나리오:
1. 1,000명 캠페인 "보내기" 클릭 → 요청이 3초 걸림.
2. 사용자가 응답이 없자 한 번 더 클릭(또는 프론트 axios 재시도).
3. `dispatch_campaign`이 2회 실행 → msghub로 1,000명 × 2 = 2,000건 발송, 과금도 2배.
   cliKey는 `c{campaign_id}-...` 로 campaign_id가 다르므로 msghub 10분 중복 차단(cliKey 기준)도 우회된다.

제안:
- POST /campaigns 에 `Idempotency-Key` 헤더(또는 body 필드)를 받아 `(created_by, key)` UNIQUE 로 캠페인 생성 단계에서 중복을 차단. 동일 키 재요청 시 기존 캠페인 결과를 그대로 반환.
- 최소 방어로라도 "동일 created_by + 동일 content 해시 + 동일 수신자 집합이 N초 내 재요청"을 거부하는 단기 가드 추가.

---

### C2
[🔴][🔢 알고리즘] app/services/compose.py:599-629 (resolve_recipients 미사용) + campaigns.py:301 — 수신자 중복 제거가 발송 경로에 전혀 적용되지 않아 중복 번호가 그대로 중복 발송·과금

근거:
- 실제 발송 경로는 `create_campaign`이 `body.recipients`(POST 원본 배열)를 `dispatch_campaign`에 그대로 전달한다(campaigns.py:301). `dispatch_campaign`에는 dedup 로직이 없다(compose.py:368-372는 길이 검증뿐).
- 중복 제거를 수행하는 `resolve_recipients`(compose.py:599)는 **어디서도 호출되지 않는다**(grep: `resolve_recipients` → 정의 1곳뿐). 즉 dead code이며, 발송 경로의 dedup 보장이 아니다.
- `CampaignCreateBody.recipients`(campaigns.py:169)는 `max_length=1000`만 검증, 중복 검사 없음.

재현 시나리오:
1. 사용자가 수신자 입력란에 `010-1111-2222` 를 실수로 두 줄 붙여넣음(엑셀 복붙 흔함).
2. POST /campaigns recipients=`["01011112222","01011112222", ...]`.
3. `parse_phone_list`는 둘 다 유효로 통과(util/phone.py:52, dedup 없음) → 동일 번호에 2건 발송 + 2건 과금.
   (그룹 발송 시 `expand_groups_to_contacts`는 contact_id 기준 distinct이지만, 서로 다른 contact가 같은 phone을 가지면 역시 중복 발송된다.)

제안:
- `dispatch_campaign` 진입부에서 `recipients = list(dict.fromkeys(recipients))` 로 순서 보존 dedup 후 `total_count` 산정.
- 그룹/연락처 출처도 phone 기준 최종 dedup(현재 contact_id distinct만으로는 phone 중복을 못 막음).
- dedup으로 제거된 건수를 응답/감사로그에 노출해 사용자에게 투명 고지.

---

### C3
[🔴][🔢 알고리즘] app/services/compose.py:262-291 — MsghubRateLimited(CPS 초과) 재시도 경로가 동일 청크를 중복 발송할 수 있음

근거:
- `send_rcs`가 예외를 던지는 시점은 `_raise_for_response`(client.py:201/312)로, 이는 **HTTP 응답 본문을 받은 뒤** code를 보고 raise한다. 즉 29002(CPS 초과)는 서버가 요청을 수신·처리한 뒤 반환하는 코드다.
- 그런데 compose.py:262 의 `except MsghubRateLimited` 핸들러는 `db.rollback()` 후 30초 대기하고 `_send_chunk_direct`로 **같은 수신자에게 SMS를 다시 발송**한다(compose.py:267). cliKey는 `-fb` 접미사로 바꿔 msghub의 cliKey 10분 중복 차단(compose.py:502-503 주석)도 회피한다.
- 문제: 29002는 "이번 요청이 CPS 한도를 넘어 거절"인지 "일부 수신자는 큐잉되고 한도 초과분만 거절"인지 본문만으로 단정할 수 없다. msghub가 부분 수락(일부 cliKey REG) 후 전체 코드로 29002를 줄 가능성이 있고, 이 경우 -fb 재발송은 이미 큐잉된 수신자에게 2번째 메시지를 보낸다.
- 더 확실한 케이스: `MsghubServerError`/타임아웃(compose.py:337) 시에는 재발송하지 않고 실패 처리하는데, 29002만 유독 즉시 재발송이라 경로별 정책이 불일치한다.

재현 시나리오:
1. 대량 발송 중 특정 청크가 CPS 한도 경계에 걸려 msghub가 일부 수신자는 REG 처리하고 전체 응답 code=29002 반환.
2. `except MsghubRateLimited` → 30초 후 `_send_chunk_direct`로 같은 10명에게 SMS 재발송.
3. 이미 RCS로 받은 수신자가 SMS를 한 번 더 수신 → 중복 발송 + 중복 과금.

제안:
- 29002 재시도는 "동일 cliKey로 동일 엔드포인트 재요청"(멱등)으로 처리하고, msghub의 cliKey 중복 차단을 **활용**해야 한다. `-fb` 키로 채널을 바꿔 재발송하는 현재 방식은 멱등성을 깨므로 금지.
- 재시도 전 `query_sent`로 해당 cliKey들의 상태(REG/ING/DONE)를 조회해 이미 접수된 건을 제외하고 미접수분만 재발송.
- 최소한 부분 수락 가능성을 문서/코드로 확정하기 전까지는 29002도 다른 서버오류와 동일하게 "실패 기록 후 멱등 재처리 대기"로 보수적 처리. **확인 필요**: msghub 29002의 부분수락 의미론(공식 스펙 확인 권장).

---

### C4
[🔴][🔢 알고리즘] app/msghub/codes.py:36-46 + compose.py:99 — RCS SMS형(RPSSAXX001) 실발송의 과금 단가가 PRICE_TABLE과 어긋나 단문 캠페인이 예상의 ~2배(17원)로 청구될 수 있음

근거:
- 단문은 항상 `RPSSAXX001`(RCS SMS형, 단방향)으로 발송된다(compose.py:99-110, 410). 코드 주석은 "9원"이라 단언한다(compose.py:89, 363).
- 그러나 실제 청구는 webhook 리포트의 `(ch, productCode)`로 `calculate_cost`가 PRICE_TABLE을 조회해 결정된다(report.py:196, codes.py:102-106).
- RCS로 성공 전달되면 리포트의 ch는 "RCS"가 된다. PRICE_TABLE에서 `(RCS, SMS)=17`(codes.py:41)이다. 즉 RPSSAXX001이 RCS로 도달해 msghub가 productCode=SMS로 리포트하면 **건당 17원**이 기록된다 — README의 "RCS양방향 8원" 도 아니고 "SMS 9원"도 아니다.
- 반대로 fallback되어 ch=SMS로 도달하면 `(SMS,SMS)=9`로 9원. 그래서 동일 캠페인이 단말 전달 채널에 따라 9원/17원으로 갈린다.
- 추가 불일치: `estimate_cost("short")`(codes.py:67-70, 121-127)는 min을 `(RCS,CHAT)=8`로 잡지만, 실제 발송 상품은 CHAT이 아니라 SMS형이다. 견적과 실청구의 상품 정의가 다르다.

재현 시나리오:
1. 1,000명 단문 캠페인 발송, 수신자 대부분 RCS 단말.
2. webhook 리포트 ch=RCS, productCode=SMS 로 도착.
3. `calculate_cost("RCS","SMS",True)=17` → `total_cost=17,000`원으로 집계.
4. 사용자/README 기대치는 9원×1,000=9,000원. 약 89% 초과 청구로 인식.

제안:
- RPSSAXX001 성공 전달 시 msghub가 부과하는 실제 (ch, productCode, 단가)를 **공식 단가표로 확정**하고 PRICE_TABLE을 그에 맞춰 정정(특히 `(RCS,SMS)=17`이 맞는지, README의 단문 단가 정의와 일치시킬지).
- `_ESTIMATE_MAP["short"]`의 RCS 측 키를 실제 발송 상품(SMS형)과 일치시켜 견적·청구 정의를 통일.
- **확인 필요**: msghub의 통합 RCS SMS형(RPSSAXX001) 과금 코드. 현 PRICE_TABLE 17원은 출처 주석이 없어 검증 불가.

---

### C5
[🔴][⚙️ 기능] app/services/compose.py / app/services/report.py 전반 — 웹훅 유실 시 PENDING 메시지를 회수할 폴링·재조정 경로가 전혀 없어, 상태가 영구 PENDING으로 남고 과금/성공 집계가 누락

근거:
- 배달 리포트는 100% 웹훅 의존(webhook.py)이며 폴링이 없다(README/주석 명시).
- 보조 회수 수단인 `query_sent`(client.py:423)와 `process_sent_query`(report.py:82)는 **어디서도 호출되지 않는다**(grep 결과 호출부 0). 즉 죽은 코드다.
- 스케줄러/백그라운드 재조정 작업도 없다(grep: `apscheduler|asyncio.create_task|cron|reconcil` → 0 hits).
- 결과: 특정 캠페인의 웹훅이 유실(네트워크/콘솔 URL 오설정/msghub 일시 장애)되면 그 Message들은 `_update_message`를 영원히 못 받는다. `_refresh_campaign_counters`는 webhook 트랜잭션 안에서만 호출되므로(report.py:73-76), 캠페인 카운터(ok/fail/cost)도 갱신되지 않는다.

재현 시나리오:
1. 캠페인 발송 → Message 1,000건 status=REG.
2. 해당 캠페인 리포트 웹훅이 유실(예: 배포 중 다운타임에 msghub가 400 받고 재시도 횟수 소진).
3. 영구히 status=REG, campaign.total_cost=0, ok_count=0. 대시보드/정산이 0원으로 표시되어 실제 청구와 괴리.

제안:
- `query_sent`/`process_sent_query`를 주기 작업(예: 발송 후 N분/시간 경과한 미완료 Message를 cliKey 배치 조회)으로 실제 배선. 이미 idempotency(status==DONE skip, report.py:99)는 구현돼 있어 재조정에 안전.
- 또는 `get_daily_stats`(client.py:447)로 일자별 msghub 집계와 DB 집계를 대조하는 정산 잡 추가(해당 함수 docstring이 이미 그 용도를 명시).

---

### C6
[🔴][⚙️ 기능] app/routes/webhook.py:178-282 + schemas.py:287-319 — MO 웹훅에서 SMS/MMS MO의 멱등키(moKey)가 비면 매 재시도마다 중복 저장 + 위변조 페이로드로 임의 대화 주입 가능

근거:
- MO 저장 멱등성은 `mo_key` UNIQUE(models.py:305)와 사전 SELECT(webhook.py:234-239)로 보장된다. 그러나 `MoItem.from_dict`(schemas.py:305-319)에서 SMS/MMS MO의 `mo_key`는 payload의 `moKey`에서 온다. msghub가 moKey를 비워 보내거나 형식이 다르면 webhook.py:230 의 `if not item.mo_key: continue`로 **조용히 skip**되어, 해당 MO는 영영 저장되지 않는다(수신 누락). 반대로 RCS 양방향은 `msgKey`를 mo_key로 쓰는데(schemas.py:294), 두 출처가 같은 키 공간을 공유한다는 보장이 없어 충돌/오매칭 가능.
- 위변조: 웹훅 인증은 URL 경로 토큰뿐이다(webhook.py:48-78). 토큰은 msghub 콘솔과 우리 URL에만 있으나, 토큰이 한 번 유출되면(로그/프록시/리퍼러) 공격자가 임의의 `moNumber/moCallback/moMsg`로 가짜 MO를 주입할 수 있다. payload 내용 검증이 없어 존재하지 않는 고객 번호로 임의 대화 스레드를 만들 수 있고, 이는 대화방 UI·미답 카운트·향후 자동응답을 오염시킨다.

재현 시나리오(중복 저장):
1. 정상 MO 수신 → DB 저장, 200 반환. (정상 멱등)
2. (누락 케이스) msghub가 moKey 없이 MO 전송 → webhook.py:231 skip → 200 success 반환 → msghub는 "성공"으로 큐에서 삭제 → MO 영구 유실(중복이 아니라 누락 사고).

재현 시나리오(위변조):
1. 토큰이 액세스 로그를 통해 유출.
2. 공격자가 `POST /webhook/msghub/{token}/mo` 로 `{"moLst":[{"moKey":"x","moNumber":"01000000000","moCallback":"<우리발신번호>","moMsg":"가짜"}]}` 전송.
3. 가짜 MO가 저장되어 대화방에 임의 메시지 표시 + unanswered 카운트 오염.

제안:
- moKey 누락 시 skip+200 대신, payload 식별 가능한 대체키(예: `hash(moNumber+moRecvDt+moMsg)`)로 저장하거나 4xx로 거부해 유실을 막는다(현 skip은 "성공" 응답이라 재시도조차 안 됨).
- 토큰은 회전 가능하게 하고, 가능하면 발신지 IP allowlist(msghub 고정 IP)와 결합. payload의 `moCallback`이 우리가 보유한 활성 발신번호(Caller)인지 검증해 임의 콜백 주입을 차단.

---

## 🟠 HIGH

### H1
[🟠][🔢 알고리즘] app/services/compose.py:535-561 + 458-466 — HTTP 200 응답 내 일부 수신자 실패가 dispatch 단계 카운터에 반영되지 않아 상태/실패수가 일시적으로 틀림

근거(수치 검증):
- 10명 청크가 HTTP 200으로 성공하고 그 안에서 3명이 item code=29020(실패)인 경우, `_create_messages_from_response`(compose.py:535-548)는 7 REG + 3 FAILED 행을 만든다.
- 그러나 `dispatch_campaign`의 실패 집계 `failed_chunk_sizes`는 **HTTP 레벨 예외가 난 청크만** 담는다(compose.py:290-291, 341-342). 위 청크는 예외가 없으므로 `failed_recipients=0`.
- 결과(파이썬 시뮬레이션): `state=DISPATCHED, fail_count=0, pending_count=10` — 실제로는 3건이 이미 FAILED. 카운터가 사실과 불일치.
- 이 불일치는 webhook이 도착해 `_refresh_campaign_counters`(report.py:211)가 Message행에서 재계산할 때 비로소 교정된다. 즉 C5(웹훅 유실)와 겹치면 영구히 틀린 상태로 남는다.

재현 시나리오:
1. 일부 수신번호가 형식상 통과했으나 msghub가 item 단위로 거절(29020 등) — HTTP는 200.
2. 발송 직후 상세 화면: 캠페인 DISPATCHED, 실패 0으로 표기되나 수신자 목록엔 FAILED 3건.
3. 사용자 혼란 + 해당 캠페인 웹훅이 늦거나 유실되면 집계가 계속 0 실패로 남음.

제안:
- `_create_messages_from_response`가 (성공/실패 건수)를 반환하게 하여 `dispatch_campaign`이 item 레벨 실패를 즉시 `fail_count/pending_count`에 반영. 상태 판정도 item 단위 실패를 포함.

---

### H2
[🟠][⚙️ 기능] app/services/chat.py:324-370 + app/routes/threads.py:338 — 답장 길이 검증(validate_reply_content)이 호출되지 않아, 90바이트 초과 답장이 조용히 LMS로 강등되어 대화 연속성이 깨짐

근거:
- `validate_reply_content`(chat.py:324)는 "90바이트 초과면 차단"을 구현하지만 **어디서도 호출되지 않는다**(grep: 정의 1곳뿐).
- 실제 답장 경로 `send_reply`(chat.py:348-370)는 `message_type="SMS"`를 넘기지만, `dispatch_campaign`은 이 인자를 사용하지 않고 `_classify_msg_type(content,...)`로 **본문 길이에 따라 재분류**한다(compose.py:382-383). 90바이트 초과 본문은 `long`→RPLSAXX001(LMS형 단방향)으로 발송된다.
- chat.py:325-330 주석 스스로 "90byte 넘으면 LMS(단방향)로 강등되어 고객이 더 이상 답장할 수 없다"고 경고하는데, 그 방어가 비활성(미호출)이다.

재현 시나리오:
1. 상담원이 대화방에서 100바이트(한글 50자) 답장 입력.
2. `api_post_message` → `send_reply` → `dispatch_campaign`이 long으로 분류 → 단방향 LMS 발송.
3. 고객은 RCS 양방향 대화창이 아닌 일반 LMS를 받아 답장 불가 → 대화 단절. 사용자에겐 정상 발송으로 표시.

제안:
- `api_post_message` 또는 `send_reply` 진입부에서 `validate_reply_content`를 호출해 90바이트 초과를 422로 차단(현재 의도된 정책). 완화하려면 정책을 명시적으로 바꾸되, "조용한 강등"은 제거.

---

### H3
[🟠][🔢 알고리즘] app/services/report.py:218-223 — 비용/성공 집계의 fallback 채널 판정이 KAKAO·RCS-SMS형 등을 누락해 fallback_count/총비용이 어긋남

근거:
- `is_fallback = channel in ("SMS","LMS","MMS") & is_success`(report.py:223). 그러나 ChatChannel은 최근 KAKAO까지 확장됐다(threads.py:57, chat.py:36 주석). KAKAO로 전달된 성공 건은 rcs도 fallback도 아닌 것으로 분류되어 `rcs_count + fallback_count != ok_count`가 된다.
- `is_rcs`는 `channel=="RCS"`만 RCS로 본다. C4에서 보듯 단문 RCS 성공이 ch="RCS", productCode="SMS"로 와도 채널이 RCS면 rcs_count에 잡히지만, 비용은 17원이 되는 등 분류·단가가 따로 논다.
- `total_cost`는 Message.cost 합(report.py:230)이라 그 자체는 productCode 기반으로 맞지만, 화면 breakdown(campaigns.py:259-265: rcsDelivered/smsFallback)이 위 누락으로 합이 안 맞아 사용자가 "전달=성공"인데 분해 합이 모자란 것을 보게 된다.

재현 시나리오:
1. 카카오 알림톡 채널로 일부 전달(KAKAO).
2. ok_count엔 포함되나 rcs_count/fallback_count 어디에도 안 들어감.
3. 상세 breakdown: total=100, rcsDelivered=60, smsFallback=30, failed=0 → 합 90 ≠ 100. 10건이 사라진 것처럼 보임.

제안:
- fallback/채널 분류를 명시적 enum 함수로 통일하고 KAKAO를 포함. breakdown이 `rcs+fallback+kakao+failed == total`을 항상 만족하도록 불변식 추가/테스트.

---

### H4
[🟠][⚙️ 기능] app/services/report.py:162-175 (_find_message phone 보조매칭) — cliKey 없는 리포트를 phone으로 "가장 최근 미완료 메시지"에 붙여 엉뚱한 캠페인에 결과·과금이 귀속될 수 있음

근거:
- cliKey/msgKey 매칭 실패 시 `phone`만으로 `status in (PENDING,REG,ING,FB_PENDING)`인 **가장 최근 1건**에 결과를 적용한다(report.py:162-171).
- 동일 번호에 짧은 시간 내 2개 캠페인이 발송돼 둘 다 미완료면, 먼저 도착한 리포트가 의도와 다른 캠페인의 Message를 DONE 처리하고 비용까지 그 캠페인에 적재한다(`_update_message`가 channel/product_code/cost를 그대로 기록, report.py:194-196).

재현 시나리오:
1. 같은 고객 번호가 캠페인 A(09:00)와 캠페인 B(09:01)에 모두 포함.
2. msghub 콘솔 설정 문제로 리포트에 cliKey가 비어 도착, phone만 존재.
3. `_find_message`가 id 역순으로 B의 Message를 집어 A의 결과를 B에 기록 → A는 영영 PENDING, B는 잘못된 채널/비용.

제안:
- phone 보조매칭은 "해당 phone의 미완료가 정확히 1건일 때"만 적용하고, 2건 이상이면 매칭 보류(로그+미처리)로 오귀속을 방지.
- 가능하면 발송 시 cliKey를 userCustomFields에도 심어 리포트의 `user_custom_fields`(schemas.py:216)로 교차검증.

---

### H5
[🟠][⚙️ 기능] app/services/compose.py:415, 458-466 + report.py:244 — 예약(RESERVED) 캠페인이 실제 발송 시점에 상태/카운터를 갱신할 경로가 없어 영구 RESERVED로 정체

근거:
- 예약 발송은 `send_rcs(resv_yn="Y")` → `ReserveResponse`(items 없음) → `_create_messages_from_response`의 else 분기로 Message가 status=PENDING으로 생성(compose.py:549-560).
- 발송 직후 상태 판정에서 실패가 없으면 `campaign.state="RESERVED"` 유지(compose.py:459).
- 예약 시각이 도래해 msghub가 실제 발송하면 리포트 웹훅이 와야 `_refresh_campaign_counters`가 RESERVED→COMPLETED/PARTIAL_FAILED로 전이할 수 있다(report.py:244는 RESERVED를 후보에 포함). 그러나 리포트가 오기 전까지(또는 유실 시 C5와 동일) RESERVED로 남고, pending_count는 total과 같아 "발송됐는지" 알 수 없다.
- 또한 RESERVED→DISPATCHING(실행 시작) 같은 중간 전이가 없어, 예약이 실행됐는지 취소 가능한지 경계가 모호하다(cancel_campaign은 RESERVED만 허용, campaigns.py:382).

재현 시나리오:
1. 내일 10:00 예약 캠페인 생성 → RESERVED.
2. 10:00에 msghub가 발송했으나 리포트 웹훅 첫 배치가 유실.
3. 캠페인은 계속 RESERVED, 사용자는 "아직 안 나갔다"고 오인하고 cancel을 시도(이미 발송됐는데 취소 성공 표시될 수 있음 → H6 참조).

제안:
- 예약 발송도 C5의 재조정(query_sent/get_daily_stats)로 상태를 능동 확인. 예약 실행 시점(reserve_time) 경과 후 미완료면 폴링으로 보강.

---

### H6
[🟠][⚙️ 기능] app/routes/campaigns.py:418-421 — 예약 취소가 msghub에서 BadRequest(이미 실행됨)여도 로컬 상태를 RESERVE_CANCELED로 만들어, 이미 발송된 캠페인을 "취소됨"으로 오표기

근거:
- `cancel_reservation`이 `MsghubBadRequest`를 던지면(이미 실행/취소된 경우 포함) except 블록이 `campaign.state="RESERVE_CANCELED"`로 강제하고 "이미 처리되었습니다" 메시지를 붙여 **commit**한다(campaigns.py:418-421, 439).
- 즉 msghub가 "이미 발송 시작됨"이라 취소 거부한 경우조차 우리 DB는 취소로 기록된다. 실제로는 발송이 진행/완료될 수 있어 상태가 사실과 정반대가 된다.

재현 시나리오:
1. 예약 시각 직전 사용자가 취소 클릭.
2. msghub는 이미 발송 큐에 넣어 BadRequest(취소 불가) 반환.
3. 우리 DB: RESERVE_CANCELED. 그러나 메시지는 실제 발송됨 → 사용자는 "취소했다"고 믿지만 고객은 메시지를 받음(오발송 인지 실패).

제안:
- BadRequest 응답을 코드별로 구분: "이미 취소됨"은 RESERVE_CANCELED로, "이미 발송/실행중"은 상태를 바꾸지 말고 사용자에게 "취소 불가(이미 발송됨)"를 명확히 고지. 발송 여부는 이후 리포트로 확정.

---

## 🟡 MEDIUM

### M1
[🟡][🧭 UX] app/routes/campaigns.py:326-331 — POST /campaigns 응답의 estimate.cost가 항상 0이라 사용자에게 잘못된 비용(0원)을 노출

근거:
- 응답 `estimate.cost = campaign.total_cost`(campaigns.py:329)인데 `total_cost`는 생성 시 0으로 고정(compose.py:432)이고, 실제 비용은 이후 웹훅 집계로만 채워진다. 발송 직후 화면엔 항상 0원.
- 실제 견적 함수 `estimate_cost`(codes.py:109)는 존재하나 미사용(C4 참조).

제안:
- 응답에 `estimate_cost(msg_type, len(recipients))` 기반의 (min~max) 범위를 노출. "확정 비용은 전달 결과 반영 후"임을 함께 표기.

### M2
[🟡][⚙️ 기능] app/services/compose.py:519 + client.py:226-229 — LMS(파일 없는 long)에서 fallback 직접 발송 시 title이 빈 문자열로 들어가 MMS title 필수 제약 위반 가능

근거:
- RCS 실패 직접 전환 경로 `_send_chunk_direct`는 long/image를 `send_mms(title=subject or "", ...)`로 호출(compose.py:517-523). subject가 없으면 title="".
- `_build_fallback`(compose.py:169-175)은 fbInfoLst용으로 title 기본값("알림")을 채우지만, **직접 발송 경로**는 그 로직을 거치지 않아 title 공백. MMS/LMS title 제약("MMS 시 필수", schemas.py:71)에 걸려 청크 전체가 실패할 수 있다.

제안:
- `_send_chunk_direct`도 `_build_fallback`과 동일한 title 기본값 로직을 공유(헬퍼 추출)해 일관 처리.

### M3
[🟡][🔢 알고리즘] app/services/compose.py:159-175 — fbInfoLst 단/장문 경계를 90바이트로 자체 판정하지만, RCS 본문 길이와 fallback 채널 길이 제약이 분리되어 경계 부근에서 예기치 않은 채널 선택

근거:
- `_build_fallback`은 `measure_bytes(content) <= 90`이면 SMS, 초과면 MMS(LMS 대용)로 본다(compose.py:169-175). EUC-KR 기준 45자=90byte=SMS, 46자=92byte=MMS로 검증됨.
- 그러나 RCS 메시지 자체는 RPSSAXX001(SMS형)으로 보내면서 fallback은 본문 길이로 SMS/MMS를 가르므로, RCS는 SMS형인데 fallback은 MMS가 되는 조합이 생긴다(91바이트 단문). 채널 정책 일관성이 약하고, msghub의 RCS SMS형 본문 한도와 어긋나면 RCS 자체가 거부될 수 있다.

제안:
- RCS messagebase 선택(`_classify_msg_type`)과 fallback 채널 선택을 동일한 길이 기준/표로 묶어 경계에서 채널 정의가 어긋나지 않게 한다. **확인 필요**: RPSSAXX001 본문 최대 바이트(공식 스펙).

### M4
[🟡][🧹 코드품질] app/services/compose.py:337 — `except (MsghubServerError, MsghubError, Exception)`가 사실상 모든 예외를 청크 실패로 흡수해, 프로그래밍 오류·취소(CancelledError)까지 "발송 실패"로 기록

근거:
- 마지막 except가 `Exception`을 포함하므로 KeyError/TypeError 등 코드 버그나 `asyncio.CancelledError`(BaseException이라 제외되긴 하나)도 발송 실패로 분류·커밋된다(compose.py:337-342). 진짜 버그가 "발송 실패"로 가려져 근본 원인 추적이 어렵다.

제안:
- 예상 가능한 msghub 예외만 잡고, 그 외 예외는 로깅 후 재전파하거나 별도 "INTERNAL_ERROR" 상태로 구분.

### M5
[🟡][⚙️ 기능] app/routes/webhook.py:99-100 — `_send_sms_fallback`에서 `campaign_cache[msg.campaign_id] = db.get(...)` 결과가 None이어도 캐시에 저장되나, None 캠페인의 `campaign.content` 접근 전 None 체크는 있으되, content가 None일 가능성은 미검증

근거:
- campaign이 None이면 continue(webhook.py:105). 그러나 `send_sms(msg=campaign.content)`에서 content가 빈 문자열/None인 경우 방어가 없다(webhook.py:114-118). 단, 현 outbound는 단방향이라 이 경로는 사실상 미사용(report.py 주석). 영향 제한적이나 사용 시 위험.

제안:
- fallback 발송 전 content 유효성 검증 추가, 또는 이 경로가 dead임을 명시(코드 상단 가드).

### M6
[🟡][🧹 코드품질] app/msghub/codes.py + compose.py 다수 — dead code(`resolve_recipients`, `validate_reply_content`, `query_sent`, `process_sent_query`, `estimate_cost`, `send_rcs_chat`)가 "구현됨"처럼 보여 안전 로직(중복제거/검증/재조정/견적)이 실제로 동작한다는 착시 유발

근거: 위 C2/C5/H2/M1에서 각 미호출 확인. 핵심 안전장치가 정의만 되고 배선이 안 됨.

제안: 미사용 함수는 (a) 실제 배선하거나 (b) 명확히 "미사용/예정" 주석+테스트 부재를 표기. 특히 중복제거·재조정은 critical이라 배선 우선.

---

## 🟢 LOW

### L1
[🟢][🧹 코드품질] app/services/compose.py:264 — `await asyncio.sleep(30)` 고정 백오프가 핸들러 안에 하드코딩. 대량 발송 중 청크마다 29002가 나면 30초×N 누적으로 요청 핸들러가 장시간 블로킹(요청-스코프 동기 발송 구조와 결합 시 타임아웃).

제안: 상수화 + 지수 백오프, 그리고 발송을 백그라운드 작업으로 분리 검토.

### L2
[🟢][🧹 코드품질] app/routes/threads.py:365 / 282 — 답장 응답 kind가 항상 "sms"로 고정(주석은 "단방향 RCS일 수도"). 실제 발송 채널과 표시가 어긋날 수 있음(경미한 표시 이슈).

### L3
[🟢][🔢 알고리즘] app/services/chat.py:67-98 (_parse_ts_for_sort) — ISO/네이티브 혼합 타임스탬프를 매 정렬마다 파싱. 스레드/메시지 많아지면 정렬 비용 증가(정확성은 OK). 캐싱/정규화 저장 고려.

### L4
[🟢][⚙️ 기능] app/msghub/auth.py:67 — `secrets.token_urlsafe(15)[:20]`는 URL-safe Base64라 `-`/`_` 포함 가능(허용 문자셋과 일치). 다만 절삭으로 엔트로피가 미세 감소. 기능상 문제 없음(확인 완료).

---

## 요약 통계표

| 심각도 | 건수 | 항목 |
|--------|------|------|
| 🔴 CRITICAL | 6 | C1 멱등키 부재(중복발송) / C2 수신자 dedup 미적용 / C3 29002 재시도 중복발송 / C4 RCS SMS형 과금 17원 불일치 / C5 웹훅유실 재조정 부재 / C6 MO 멱등키·위변조 |
| 🟠 HIGH | 6 | H1 item실패 카운터 누락 / H2 답장 길이검증 미호출 / H3 KAKAO fallback 분류 누락 / H4 phone 보조매칭 오귀속 / H5 예약 상태 정체 / H6 취소 오표기 |
| 🟡 MEDIUM | 6 | M1 estimate.cost=0 / M2 직접발송 title 공백 / M3 fallback 경계 / M4 광범위 except / M5 fallback content 미검증 / M6 dead code 착시 |
| 🟢 LOW | 4 | L1 고정 백오프 / L2 답장 kind 고정 / L3 정렬 파싱 비용 / L4 randomStr 엔트로피 |
| **합계** | **22** | |

렌즈 분포: 🔢 알고리즘 8 · ⚙️ 기능 9 · 🧹 코드품질 4 · 🧭 UX 1

---

## Top 위험 5 (이 영역 최우선)

1. **C1 — POST /campaigns 멱등키 부재 → 더블클릭/재시도 시 전체 캠페인 중복 발송·이중 과금.**
   가장 흔하고(사용자 더블클릭) 피해가 큰(1,000명×2) 금전 사고. 멱등키 도입이 1순위.

2. **C4 — 단문 RCS(RPSSAXX001) 실청구 17원 vs 기대 9원 불일치 → 단문 캠페인 최대 ~89% 초과 청구.**
   PRICE_TABLE `(RCS,SMS)=17`과 실제 발송 상품/README 단가의 정합성 확정 필요. 모든 단문 발송에 영향.

3. **C2 — 수신자 중복 제거가 발송 경로에 미적용(resolve_recipients dead) → 입력 중복 = 중복 발송·과금.**
   엑셀 복붙 등으로 매우 흔히 재현. dispatch_campaign 진입부 dedup으로 즉시 차단 가능.

4. **C5 — 웹훅 유실 시 폴링/재조정 경로 전무(query_sent·get_daily_stats dead) → 상태 영구 PENDING, 과금·성공 집계 누락.**
   배포 다운타임/콘솔 오설정과 결합 시 정산이 통째로 틀어짐. H1·H5의 일시적 오류도 영구화시키는 증폭 인자.

5. **C6 — MO 웹훅 멱등키 누락 시 조용한 유실 + URL토큰 외 페이로드 검증 부재로 위변조 대화 주입 가능.**
   moKey 없는 MO를 "성공" 응답으로 skip해 영구 유실(수신 누락) + 토큰 유출 시 임의 MO 주입.

> 권고 우선순위: C1·C2(중복발송 차단) → C4(과금 정합성) → C5(재조정 배선) → C6(MO 안전) → H1~H6 순.
