# Phase 4 — 프론트엔드 UX & 상태관리 코드 리뷰

> 리뷰어: Frontend Architect Agent  
> 대상 브랜치: vibrant-shamir-e74f49  
> 리뷰 기준일: 2026-05-30  
> 테스트: 없음 (코드 정독 기반)

---

## 발견사항 (심각도 순)

---

### [🔴 CRITICAL][⚙️ 기능] `csrf-client.ts:13` — CSRF 토큰 캐시가 탭/창 간 공유됨 (토큰 고갈 취약점)

**근거:** `cached`와 `inflight`가 모듈 수준 변수(`let cached: string | null = null`)로 선언되어 있다. 브라우저에서 모듈은 같은 origin의 모든 탭이 공유하는 것이 아니라 탭별 JS 컨텍스트에서 격리되므로 이것 자체는 문제가 아니다. 그러나 더 심각한 문제가 있다: 로그아웃 후 다시 로그인했을 때 `invalidateCsrfToken()`이 호출되지 않는 경로가 존재한다. `apiSend`는 403 응답에만 `invalidateCsrfToken()`을 호출하는데, 세션이 만료되어 서버가 401을 반환하면 stale 토큰이 캐시에 남아있는 채로 이후 모든 변경 요청이 전송된다. 401 → 리다이렉트 → 재로그인 → 여전히 구 토큰 사용 흐름에서 CSRF 검증 실패가 아닌 권한 오류가 발생한다.

**사용자 시나리오:** 사용자가 세션 만료 후 재로그인하고 캠페인을 발송하면, 서버가 X-CSRF-Token을 거부하거나(서버 구현에 따라) 의도치 않은 사용자 컨텍스트로 요청이 수행된다.

**제안:** `apiSend`에서 401 응답도 `invalidateCsrfToken()` 트리거 조건에 추가한다. 또는 인증 컨텍스트(로그아웃 이벤트)에서 명시적으로 `invalidateCsrfToken()`을 호출하는 훅을 연결한다.

---

### [🔴 CRITICAL][⚙️ 기능] `ComposeForm.tsx:114-149` — 중복 제출 방지 로직에 경쟁 조건(race condition) 존재

**근거:** `canSubmit` 조건이 `!submitting`을 포함하지만, `onSubmit`은 `async` 함수이며 `setSubmitting(true)`는 React 상태 업데이트이므로 다음 렌더 전까지 즉각 반영되지 않는다. 두 번 빠르게 클릭하면 첫 번째 `onSubmit`이 `setSubmitting(true)`를 예약하기 전에 두 번째 `onSubmit`이 호출될 수 있다. `canSubmit` 체크는 렌더된 상태를 기반으로 하므로 두 번째 호출 시점에 `submitting`이 여전히 `false`일 수 있다.

**사용자 시나리오:** 발송 버튼을 빠르게 두 번 클릭하면 동일한 캠페인이 두 번 접수되어 수신자들이 메시지를 중복 수신한다. 대량 발송 시스템에서 이는 대규모 피해로 이어진다.

**제안:** `useRef<boolean>`으로 동기 플래그를 관리한다:
```ts
const submittingRef = useRef(false);
const onSubmit = async (e: FormEvent) => {
  e.preventDefault();
  if (submittingRef.current || !canSubmit) return;
  submittingRef.current = true;
  setSubmitting(true);
  // ...
  submittingRef.current = false; // finally 블록에서
};
```

---

### [🔴 CRITICAL][🧭 UX] `ContactDrawer.tsx:47` — `window.confirm()` 사용으로 접근성·UX 규격 위반

**근거:** `onDelete`에서 `confirm(`${contact.name} 연락처를 삭제하시겠습니까?`)`를 직접 호출한다. `window.confirm`은 (1) 키보드 포커스 트랩을 브라우저에 위임해 현재 포커스 위치를 잃음, (2) 스크린리더에서 예측 불가능한 동작, (3) 디자인 시스템과 일관되지 않는 OS 네이티브 대화상자, (4) 테스트 불가능 등 다수의 문제가 있다.

**사용자 시나리오:** 키보드 사용자가 삭제 버튼을 누르면 포커스가 OS 다이얼로그로 이동했다가 닫힌 후 포커스가 유실되어 Drawer 내 탐색을 다시 처음부터 해야 한다. 스크린리더 사용자는 맥락 없이 "연락처를 삭제하시겠습니까?"라는 메시지만 듣게 된다.

**제안:** Radix UI Dialog 기반의 확인 모달(ConfirmDialog)을 사용해 포커스 트랩과 ARIA role="alertdialog"를 준수한다. 기존 Drawer/Dialog 패턴이 이미 있으므로 재사용 가능하다.

---

### [🟠 HIGH][⚙️ 기능] `useChatStream.ts:38-52` — `router` 의존성이 매 렌더마다 새 EventSource 생성 유발

**근거:** `useEffect`의 의존성 배열이 `[router]`인데, Next.js App Router의 `useRouter()`는 렌더마다 안정된 참조를 반환하지만 일부 경로 변경(특히 `router.refresh()` 호출 후)에서 참조가 변경될 수 있다. `ThreadView`에서 `useChatStream()`이 호출되고, `ThreadComposer`에서 메시지 발송 후 `router.refresh()`를 호출하면 router 참조가 새로 만들어져 `useEffect`가 재실행된다. 이 경우 기존 EventSource는 close되고 새 연결이 수립되어 `attempts`가 0으로 리셋되는데, 재연결 중 서버 이벤트를 놓칠 수 있다.

**사용자 시나리오:** 메시지를 발송할 때마다 SSE 스트림이 잠시 끊어졌다가 재연결되며, 그 사이에 도착한 상대방 메시지가 실시간으로 반영되지 않는다.

**제안:** `router`를 ref로 안정화한다:
```ts
const routerRef = useRef(router);
useEffect(() => { routerRef.current = router; }, [router]);
useEffect(() => {
  // connect 내부에서 routerRef.current.refresh() 호출
}, []); // 빈 의존성 배열
```

---

### [🟠 HIGH][⚙️ 기능] `useChatStream.ts:27-53` — SSE 재연결 시 `attempts` 증가 순서 오류로 backoff 계산 버그

**근거:** 에러 핸들러에서 `delay`를 계산한 후 `attempts += 1`을 수행한다(50~51번째 줄). 첫 번째 에러 시 `attempts=0`이므로 `delay = 1000 * 2^0 = 1000ms`가 맞지만, 이후 시도에서 `attempts`가 delay 계산 이후에 증가하므로 2번째 재시도는 `delay = 1000 * 2^1 = 2000ms`(올바름), 3번째는 `1000 * 2^2 = 4000ms`(올바름)로 보인다. 그러나 `open` 이벤트에서 `attempts = 0`으로 리셋하는데, open 이벤트가 error 이벤트와 같은 틱에서 발생할 경우 리셋이 적용되기 전에 delay가 계산될 수 있다. 또한 연속 실패 시나리오에서 `attempts`가 `MAX_BACKOFF_MS` 계산 상한을 넘어도 계속 증가하여 `2 ** 40` 등 Number.MAX_SAFE_INTEGER를 초과할 수 있다(실제로는 Math.min이 막지만 `attempts` 자체가 무한히 커짐).

**제안:** `attempts` 증가를 delay 계산 앞으로 이동하고, 상한 클램프(`Math.min(attempts, 30)`)를 적용한다.

---

### [🟠 HIGH][🧭 UX] `CommandPalette.tsx:226-265` — 검색 결과 목록이 실제 `listbox/option` ARIA 패턴을 올바르게 구현하지 않음

**근거:** 
1. `role="listbox"`를 가진 컨테이너 내부에 `role="option"`을 가진 `div`가 있지만, 실제 포커스는 상단 `<input>`에 있다. `listbox`+`option`은 포커스가 listbox에 있을 때 사용하는 패턴이다. 검색 입력 + 결과 목록의 올바른 ARIA 패턴은 `combobox` + `aria-controls` + `aria-activedescendant`이다.
2. 키보드로 `ArrowDown/Up`을 눌러 `active` 인덱스를 변경해도 실제 DOM 포커스는 이동하지 않고 시각적 표시만 변경된다(`bg-brand-soft`). `aria-activedescendant`가 없으므로 스크린리더는 현재 선택 항목을 알 수 없다.
3. `role="option"`인 `div` 내부에 `<Link>`(실제 `<a>`)가 있는데, option 안에 인터랙티브 요소를 중첩하면 ARIA 규격 위반이다.

**사용자 시나리오:** 스크린리더 사용자가 CommandPalette를 열고 검색어를 입력한 후 화살표키로 탐색해도 어떤 결과가 선택되었는지 음성 안내를 받지 못한다.

**제안:** `role="listbox/option"` 대신 `role="combobox"`(input에), `aria-controls="palette-list"`, `aria-activedescendant={activeItemId}`, 결과 컨테이너에 `role="listbox"`, 각 항목에 `id`를 부여하는 표준 combobox 패턴으로 전환한다.

---

### [🟠 HIGH][🧭 UX] `ThreadView.tsx:14-15` — `useChatStream()` 호출 시 thread prop을 전달하지 않아 특정 스레드 전용 구독 불가

**근거:** `useChatStream()`을 인자 없이 호출한다. 내부 구현을 보면 `/api/chat/stream` 전체 스트림을 구독하고 모든 `message.new`/`thread.updated` 이벤트에 `router.refresh()`를 호출한다. 현재 보고 있는 스레드와 무관한 이벤트에도 전체 페이지가 refresh된다. 여러 탭에서 채팅 페이지를 열면 모든 탭에서 동시 refresh가 발생한다. 더 중요하게, `thread.messages`는 SSR에서 내려온 snapshot이고 SSE 이벤트 후 `router.refresh()`로 재렌더되지만, 발송한 메시지는 낙관적으로 표시되지 않아 실제 roundtrip 후에야 보이게 된다.

**사용자 시나리오:** 메시지 발송 후 화면이 일시 blank 또는 로딩 상태가 되었다가 서버 응답 후 갱신된다. 느린 네트워크에서는 발송한 내 메시지가 수초간 보이지 않는다.

**제안:** 낙관적 업데이트 패턴을 도입하거나, 최소한 `useChatStream`에 현재 threadId를 전달해 관련 이벤트만 필터링한다.

---

### [🟠 HIGH][⚙️ 기능] `SetupWizard.tsx:138-141` — `setTimeout(800ms)` 후 `window.location.href` 이동은 비결정적

**근거:** `restartRecommended`가 false인 경우 800ms 후 `window.location.href = r.next`로 이동한다. 컴포넌트가 언마운트되어도 timer는 취소되지 않는다(cleanup 없음). 사용자가 800ms 내에 뒤로가기를 누르거나 다른 링크를 클릭하면 의도치 않은 강제 이동이 발생한다. 또한 `r.next`는 서버가 반환하는 임의의 URL인데 유효성 검사가 없어 open redirect 가능성이 있다(서버가 신뢰할 수 있다고 가정하더라도 Defence in depth 관점).

**사용자 시나리오:** 셋업 완료 직후 사용자가 명령창 지시문을 읽다가 800ms가 지나면 강제로 다른 페이지로 이동된다.

**제안:** `useEffect`에서 timer를 생성하고 cleanup에서 `clearTimeout`을 반환한다. 이동 전 "로그인 페이지로 이동합니다..." 메시지와 함께 취소 링크를 제공하는 것이 더 나은 UX이다.

---

### [🟡 MEDIUM][🧭 UX] `ComposeForm.tsx:311-319` — 예약 발송 시간 유효성 검사 누락 (과거 시간 허용)

**근거:** `mode === 'schedule'` 시 `<input type="datetime-local">`을 표시하지만 `min` 속성이 없고 과거 날짜/시간 선택을 막지 않는다. `canSubmit` 조건도 `sendAt !== ''` 만 확인하며 미래 시간 여부를 검증하지 않는다. FastAPI 서버에서 검증할 수 있지만, 클라이언트 피드백이 없으면 사용자는 폼 제출 후 서버 오류를 통해야만 문제를 알 수 있다.

**사용자 시나리오:** 실수로 어제 날짜를 선택하고 발송 버튼을 눌러야만 "과거 시간은 예약 불가" 오류를 볼 수 있다.

**제안:** `<Input type="datetime-local" min={new Date().toISOString().slice(0, 16)} />`을 추가하고, `canSubmit` 조건에 `new Date(sendAt) > new Date()`를 포함한다.

---

### [🟡 MEDIUM][🧭 UX] `AttachmentPicker.tsx:39-57` — 업로드 중 컴포넌트 언마운트 시 setState 호출 (메모리 누수 경고)

**근거:** `onFile`은 `async` 함수이며 `uploadCampaignAttachmentClient` 호출 후 `onChange(uploaded)`, `setUploading(false)` 등을 호출한다. 업로드 도중 사용자가 탭을 이탈하거나 ComposeForm이 언마운트되면 비동기 작업이 완료될 때 unmounted 컴포넌트에 setState를 호출해 React 경고가 발생한다(React 18에서는 경고가 제거됐지만 실제로는 메모리 누수 가능성 있음). `uploadCampaignAttachmentClient`는 취소(AbortController) 메커니즘을 제공하지 않는다.

**제안:** `useEffect` cleanup 패턴이나 `AbortController`를 활용해 언마운트 시 업로드를 취소한다. 혹은 최소한 unmounted ref 플래그로 setState 호출을 가드한다.

---

### [🟡 MEDIUM][🧭 UX] `CommandPalette.tsx:96-101` — 포커스를 `setTimeout(50ms)`으로 지연시키는 불안정한 패턴

**근거:** Dialog가 열릴 때 `setTimeout(() => inputRef.current?.focus(), 50)`으로 포커스를 지연한다. 이 50ms는 Radix Dialog 애니메이션이 끝나기를 기다리는 추정값으로, 느린 기기에서는 부족하고 빠른 기기에서는 과도하다. Radix UI Dialog는 `onOpenAutoFocus` 이벤트를 제공하므로 이를 활용하는 것이 표준이다.

**사용자 시나리오:** 저사양 기기에서 CommandPalette가 열려도 50ms 내에 렌더가 완료되지 않으면 포커스가 설정되지 않아 키보드 사용자가 즉시 타이핑할 수 없다.

**제안:**
```tsx
<Dialog.Content onOpenAutoFocus={(e) => { e.preventDefault(); inputRef.current?.focus(); }}>
```

---

### [🟡 MEDIUM][🔢 알고리즘] `ThreadList.tsx` — 대량 스레드 목록 가상화/페이지네이션 없음

**근거:** `threads.map((t) => ...)` 전체를 DOM에 렌더링한다. 페이지네이션/가상화 로직이 없다. 스레드가 수백~수천 개일 경우 초기 렌더 시간과 스크롤 성능이 저하된다. `threads.length` 표시는 있지만 서버 사이드 페이지네이션 파라미터를 전달하지 않는다.

**사용자 시나리오:** 대량 발송 시스템 특성상 수신자(스레드)가 1000개를 넘을 수 있는데, 이 경우 목록 렌더링이 버벅이고 스크롤이 느려진다.

**제안:** 서버 쪽에 이미 cursor 페이지네이션(`meta.cursor`)이 준비되어 있으므로, 스크롤 끝에 도달할 때 다음 페이지를 로드하는 무한 스크롤 또는 명시적 "더 보기" 버튼을 추가한다. 또는 `react-window`/`@tanstack/react-virtual`로 가상화한다.

---

### [🟡 MEDIUM][🧭 UX] `ThreadRow.tsx:25` — `aria-current` 값이 명세 불일치

**근거:** `aria-current={active ? 'true' : undefined}`로 문자열 `'true'`를 사용하고 있다. WAI-ARIA 명세에서 `aria-current`의 유효한 값은 `page | step | location | date | time | true | false`이다. 문자열 `'true'`는 유효한 토큰이지만, 링크 리스트에서 현재 항목을 나타낼 때는 `aria-current="page"` 또는 `aria-current="true"`(토큰) 중 `"page"`가 더 의미적으로 정확하다. 또한 `ChatFilters.tsx`에서는 `aria-current="page"`를 올바르게 사용하고 있어 불일치한다.

**제안:** `aria-current={active ? 'page' : undefined}`로 변경해 ChatFilters와 일관성을 맞춘다.

---

### [🟡 MEDIUM][🧭 UX] `SetupWizard.tsx:208` — Setup token 입력 필드에 `htmlFor` 연결 없음 (라벨-입력 비연결)

**근거:** `<Field label="Setup token">` 내부의 `<Input>`에 `id` prop이 없다. `Field` 컴포넌트가 `htmlFor`를 받아 label을 연결하는 구조인데(`ComposeForm.tsx`에서는 `htmlFor="sender"`, `htmlFor="msg"` 패턴을 따름), SetupWizard의 모든 Field+Input 쌍에 `id`/`htmlFor`가 없다. 스크린리더에서 레이블과 입력 필드가 연결되지 않는다.

**사용자 시나리오:** 스크린리더 사용자가 Setup 페이지의 입력 필드로 이동하면 "편집" 등 역할만 읽히고 어떤 필드인지(Issuer URL, Client ID 등) 알 수 없다.

**제안:** SetupWizard의 모든 `<Field label="...">` + `<Input>`에 `htmlFor`/`id` 쌍을 추가한다.

---

### [🟡 MEDIUM][⚙️ 기능] `notifications-client.ts:21-23` — `markAllNotificationsReadClient` 오류 응답 미처리

**근거:**
```ts
const body = (await res.json()) as { data?: { readCount: number } };
return body.data?.readCount ?? 0;
```
`!res.ok` 체크 없이 body를 파싱한다. 서버 오류(500, 403 등) 시 body가 에러 envelope이어도 `readCount ?? 0`을 반환하고 에러를 삼킨다. 다른 모든 client 함수들은 `parse<T>()` 헬퍼를 통해 오류를 throw하는 일관된 패턴을 따르는데, 이 함수만 예외이다.

**제안:** 다른 client 파일과 동일한 `parse<T>()` 패턴을 적용하거나 최소한 `if (!res.ok || body.error) throw new Error(...)` 가드를 추가한다.

---

### [🟡 MEDIUM][🧭 UX] `Drawer.tsx` — title이 없을 때 닫기 버튼만 있는 경우 헤더가 렌더되지 않아 닫기 불가

**근거:** `{(title || description) && <header>...</header>}` 조건으로 title과 description 둘 다 없으면 헤더와 닫기 버튼이 렌더되지 않는다. `Drawer`를 title/description 없이 사용하는 경우(예: 미래 확장 시) 닫기 버튼이 사라진다. Radix의 overlay 클릭과 Esc 키는 여전히 작동하지만 시각적 닫기 버튼이 없으면 접근성이 저하된다.

**제안:** 닫기 버튼을 헤더 존재 여부와 독립시키거나, title이 없더라도 최소한 닫기 버튼만 있는 헤더를 렌더한다.

---

### [🟢 LOW][🧭 UX] `ComposeForm.tsx:372` — 예약 시간 미리보기가 원시 ISO 문자열 표시

**근거:** `timeLabel={mode === 'schedule' && sendAt ? sendAt.replace('T', ' ') : '지금'}` — `2026-05-30T14:30`을 `2026-05-30 14:30`으로 단순 치환한다. 사용자가 입력한 로컬 datetime-local 값이 그대로 노출되어 `YYYY-MM-DD HH:mm` 포맷으로 표시된다. 실제 UI에서 기대하는 형식과 다를 수 있다(예: `5월 30일 오후 2:30`).

**제안:** `new Intl.DateTimeFormat('ko-KR', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(sendAt))`을 사용한다.

---

### [🟢 LOW][🔢 알고리즘] `DeviceMockup.tsx:44` — `role="img"` 사용하면서 내부에 인터랙티브 콘텐츠 포함

**근거:** 외부 `div`에 `role="img"` 및 `aria-label`이 있는데, 내부에 `MessageBubble` 등 동적 콘텐츠가 렌더된다. `role="img"` 요소 내부의 모든 콘텐츠는 스크린리더에서 접근할 수 없는 것이 원칙이다(이미지로 처리). 미리보기 메시지 텍스트가 스크린리더에 읽히지 않는다.

**제안:** 미리보기 컨텍스트이므로 `role="img"` 대신 `role="presentation"` 또는 `aria-hidden="true"`를 사용하거나, 스크린리더용 텍스트 요약을 `sr-only`로 제공한다.

---

### [🟢 LOW][🧹 코드품질] `ThreadRow.tsx:28` — `active`/`unread` 분기가 동일한 클래스 반환

**근거:**
```ts
active ? 'bg-brand-soft' : unread ? 'bg-surface hover:bg-gray-1' : 'bg-surface hover:bg-gray-1'
```
`unread`인 경우와 기본 경우가 동일한 클래스를 반환한다. 읽지 않은 스레드가 읽은 스레드와 시각적으로 구분되지 않는다(배경색 기준). 볼드체로는 구분되지만 색상 힌트가 없다.

**제안:** `unread`일 때 배경색을 달리하거나(예: `bg-brand-soft/10`) 현재 의도가 올바르다면 삼항 연산자를 단순화한다(`unread ? ... : ...` 제거).

---

### [🟢 LOW][🧭 UX] `ComposeForm.tsx:285-291` — 첨부 이미지 Field의 `htmlFor` 없음

**근거:** `<Field label="첨부 이미지" hint="...">` 내부에 `AttachmentPicker`가 있는데, AttachmentPicker는 숨겨진 `<input type="file">`을 버튼으로 트리거하는 구조이다. 파일 입력에 직접 접근 가능한 label 연결이 없다. `<input type="file" className="hidden">`이므로 label 연결이 없어도 UX 영향은 적지만 WCAG 1.3.1 준수를 위해 연결이 필요하다.

**제안:** `AttachmentPicker`의 `<input type="file">`에 `id`를 부여하고, 상위 `Field`의 `htmlFor`와 연결하거나 aria-labelledby를 사용한다.

---

### [🟢 LOW][🧹 코드품질] `lib/*-client.ts` — `parse<T>()` 헬퍼 함수가 파일마다 중복 정의

**근거:** `campaigns-client.ts`, `contacts-client.ts`, `groups-client.ts`, `numbers-client.ts`, `setup.ts` 각 파일에 동일한 구조의 `parse<T>(res: Response)` 함수가 각각 정의되어 있다. `chat.ts`의 `sendMessageClient`는 인라인으로 같은 로직을 재구현한다.

**제안:** `lib/api-utils.ts` 같은 공유 모듈로 `parseEnvelope<T>(res: Response): Promise<T>`를 추출해 DRY 원칙을 적용한다.

---

## 요약 통계표

| 심각도 | 건수 | 렌즈 분포 |
|--------|------|-----------|
| 🔴 CRITICAL | 3 | ⚙️×2, 🧭×1 |
| 🟠 HIGH | 5 | ⚙️×3, 🧭×2 |
| 🟡 MEDIUM | 7 | 🧭×4, ⚙️×2, 🔢×1 |
| 🟢 LOW | 5 | 🧭×2, 🧹×2, 🔢×1 |
| **합계** | **20** | |

---

## Top 위험 3

### 1. 🔴 CRITICAL — CSRF 토큰 캐시 stale 문제 (`csrf-client.ts:13`)
세션 만료 → 재로그인 후에도 구 CSRF 토큰이 메모리에 남아 이후 모든 변경 요청(발송·삭제·수정)에 첨부된다. 서버 구현에 따라 실패하거나 의도치 않은 컨텍스트로 실행된다. 401 응답 경로에서 `invalidateCsrfToken()`이 호출되지 않는 것이 직접 원인이다.

### 2. 🔴 CRITICAL — 발송 버튼 중복 제출 경쟁 조건 (`ComposeForm.tsx:114`)
React 상태 업데이트의 비동기 특성으로 인해 빠른 더블클릭 시 `submitting` 플래그가 두 번째 클릭 시점에 아직 `false`여서 동일 캠페인이 두 번 접수될 수 있다. 대량 발송 시스템에서 수신자 전원에게 메시지가 중복 발송되는 치명적 사고로 이어진다.

### 3. 🟠 HIGH — CommandPalette ARIA 구현 오류 (`CommandPalette.tsx:226-265`)
`listbox/option` 패턴 오용과 `aria-activedescendant` 부재로 스크린리더 사용자가 키보드 탐색 중 현재 선택된 항목을 파악할 수 없다. 동시에 `option` 안에 `<a>` 태그 중첩이라는 ARIA 규격 위반도 포함된다. 접근성 감사 시 자동 실패 항목이다.
