'use client';

import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import {
  Button,
  Check,
  ChipField,
  Editor,
  Field,
  Icon,
  Input,
  Radio,
} from '@/components/ui';
import type { UploadedAttachment } from '@/lib/campaigns-client';
import { previewCampaignClient, type CampaignPreview } from '@/lib/campaign-preview';
import { apiSend } from '@/lib/csrf-client';
import {
  lookupHiworks,
  toDigits,
  type HiworksLookupResult,
} from '@/lib/hiworks-client';
import { formatPhone, isSendableNumber } from '@/lib/phone';
import type { SenderNumber } from '@/types/number';
import { AttachmentPicker } from './AttachmentPicker';

type SendMode = 'now' | 'schedule';
type SendChannel = 'rcs' | 'sms';

type Sender = { value: string; label: string };

/**
 * Compatibility helper for callers that used the old synchronous estimate.
 * ComposeForm itself uses the server preview below, because browsers do not
 * provide the server's EUC-KR encoder. Keep this helper deliberately small and
 * deterministic for existing component consumers and unit tests.
 */
export function computeEstimate(
  message: string,
  recipientCount: number,
  hasAttachment = false,
  sendChannel: SendChannel = 'rcs',
) {
  // Preserve the legacy helper's UTF-8 result for external callers. The form
  // never uses this value for sending; it uses previewCampaignClient instead.
  const bytes = new TextEncoder().encode(message).length;
  let channel: 'SMS' | 'LMS' | 'MMS' = 'SMS';
  let perUnit = sendChannel === 'sms' ? 9 : 17;
  if (hasAttachment || bytes > 2000) {
    channel = 'MMS';
    perUnit = 85;
  } else if (bytes > 90) {
    channel = 'LMS';
    perUnit = 27;
  }
  return {
    bytes,
    channel,
    perUnit,
    cost: recipientCount * perUnit,
    bytesState: bytes > 2000 ? ('err' as const) : bytes > 90 ? ('warn' as const) : undefined,
  };
}

type PreviewState = {
  key: string;
  result: CampaignPreview | null;
  failure: string | null;
};

export function ComposeForm() {
  const router = useRouter();
  // 발신번호는 /api/numbers?status=approved 에서 런타임 로드.
  // 하드코딩 리스트는 운영 사용자마다 보유 번호가 달라 data-correctness 버그의 원인이 됐음.
  const [senderOptions, setSenderOptions] = useState<ReadonlyArray<Sender>>([]);
  const [senderLoading, setSenderLoading] = useState(true);
  const [senderError, setSenderError] = useState<string | null>(null);
  const [sender, setSender] = useState<string>('');
  const [recipients, setRecipients] = useState<string[]>([]);
  // 하이웍스 CID — 입력한 수신자 번호의 주소록 이름 미리보기(격리: 실패 시 빈 맵).
  const [cidNames, setCidNames] = useState<HiworksLookupResult>({});
  const [message, setMessage] = useState('');
  // 기본값 RCS — 라디오로 선택 상태가 보이고 견적도 즉시 표시된다.
  // 백엔드는 여전히 sendChannel 을 필수로 받으므로 API 직접 호출은 명시가 필요하다.
  const [sendChannel, setSendChannel] = useState<SendChannel>('rcs');
  const [mode, setMode] = useState<SendMode>('now');
  const [sendAt, setSendAt] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [attachment, setAttachment] = useState<UploadedAttachment | null>(null);
  const [preview, setPreview] = useState<PreviewState | null>(null);
  const [previewAttempt, setPreviewAttempt] = useState(0);
  const previewGeneration = useRef(0);
  const trimmedMessage = message.trim();
  const hasAttachment = attachment !== null;
  const previewInput = useMemo(
    () => ({ message: trimmedMessage, recipients, sendChannel, hasAttachment }),
    [trimmedMessage, recipients, sendChannel, hasAttachment],
  );
  const previewKey = JSON.stringify(previewInput);

  useEffect(() => {
    const generation = ++previewGeneration.current;
    if (!previewInput.message) {
      setPreview(null);
      return;
    }
    const controller = new AbortController();
    setPreview({ key: previewKey, result: null, failure: null });
    const timer = setTimeout(() => {
      void previewCampaignClient(previewInput, controller.signal)
        .then((result) => {
          if (controller.signal.aborted || generation !== previewGeneration.current) return;
          setPreview({ key: previewKey, result, failure: null });
        })
        .catch((err: unknown) => {
          if (controller.signal.aborted || generation !== previewGeneration.current) return;
          const reason = err instanceof Error ? err.message : '통신 오류';
          setPreview({
            key: previewKey, result: null,
            failure: `예상 비용을 확인하지 못했습니다 (${reason}). 다시 확인해 주세요.`,
          });
        });
    }, 300);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [previewInput, previewKey, previewAttempt]);

  // 입력·채널·수신자가 바뀐 첫 렌더부터 이전 견적으로 발송하지 않는다.
  const currentPreview = preview?.key === previewKey ? preview : null;
  const estimate = currentPreview?.result;
  const previewError = currentPreview?.failure ?? estimate?.error ?? null;
  const checking = Boolean(trimmedMessage && !estimate && !currentPreview?.failure);
  const bytes = trimmedMessage ? estimate?.byteLength ?? null : 0;
  const channel = estimate?.channel;
  const displayChannel = channel ?? 'SMS';
  const bytesState: 'warn' | 'err' | undefined = previewError
    ? 'err'
    : bytes !== null && bytes > 90 ? 'warn' : undefined;
  const lengthLabel = checking ? '길이 확인 중' : bytes === null ? '길이 확인 불가' : `${bytes} bytes`;
  const costLabel = estimate?.valid && estimate.costMin !== null && estimate.costMax !== null
    ? `예상 ${estimate.recipientCount}건 · ₩${estimate.costMin.toLocaleString('ko-KR')}${
      estimate.costMin === estimate.costMax ? '' : `~${estimate.costMax.toLocaleString('ko-KR')}`
    } (VAT 별도)`
    : checking ? '예상 비용 확인 중' : '예상 비용 —';

  // 발신번호 로딩 (승인된 번호만). stale response race 방어를 위해 cancelled flag.
  // 번호·브랜드만 쓰므로 서버의 일일 사용량 집계는 건너뛴다.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch('/api/numbers?status=approved&include_usage=false');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const json = (await res.json()) as { data?: SenderNumber[] };
        if (cancelled) return;
        const options = (json.data ?? []).map((n) => ({
          value: n.number,
          label: `${formatPhone(n.number)} · ${n.brand}`,
        }));
        setSenderOptions(options);
        if (options.length > 0 && options[0]) setSender(options[0].value);
      } catch (err) {
        if (cancelled) return;
        setSenderError(
          err instanceof Error ? err.message : '발신번호 목록 로딩 실패',
        );
      } finally {
        if (!cancelled) setSenderLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // 수신자 번호 → 하이웍스 이름 조회. 300ms debounce + stale 방어. 실패는 무시.
  useEffect(() => {
    if (recipients.length === 0) {
      setCidNames({});
      return;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      void (async () => {
        const result = await lookupHiworks(recipients);
        if (!cancelled) setCidNames(result);
      })();
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [recipients]);

  // 서버도 같은 규칙으로 거부(400)하지만, 칩을 넣는 즉시 어떤 값이 틀렸는지 보여 준다.
  const invalidRecipients = useMemo(
    () => recipients.filter((r) => !isSendableNumber(r)),
    [recipients],
  );
  const recipientsState: 'warn' | 'err' | undefined =
    recipients.length > 1000 || invalidRecipients.length > 0
      ? 'err'
      : recipients.length > 500
        ? 'warn'
        : undefined;

  const canSubmit =
    sender !== '' &&
    !senderLoading &&
    recipients.length > 0 &&
    recipients.length <= 1000 &&
    invalidRecipients.length === 0 &&
    trimmedMessage !== '' &&
    estimate?.valid === true &&
    !currentPreview?.failure &&
    (mode === 'now' || sendAt !== '') &&
    confirmed &&
    !submitting;

  // 더블클릭/연타 중복 제출 방지 (프론트 가드): setSubmitting 은 비동기 상태라
  // 두 번째 클릭이 첫 렌더 전에 들어오면 canSubmit 의 !submitting 이 아직 true 다.
  // useRef.current 는 동기 갱신이므로 즉시 차단한다.
  const submittingRef = useRef(false);

  // 멱등키 (C1) — 같은 발송 내용의 재시도는 동일 키를 보내 서버가 중복 발송을 차단한다.
  // 내용(발신/수신자/본문/예약/첨부)이 바뀌면 새 발송이므로 키를 리셋한다.
  const idemKeyRef = useRef<string | null>(null);
  useEffect(() => {
    idemKeyRef.current = null;
  }, [sender, recipients, message, sendAt, mode, attachment, sendChannel]);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (submittingRef.current || !canSubmit) return;
    submittingRef.current = true;
    setSubmitting(true);
    setError(null);
    // 재시도 시 동일 키 유지 — 네트워크 실패 후 재클릭해도 서버가 1회만 처리.
    const idemKey = idemKeyRef.current ?? crypto.randomUUID();
    idemKeyRef.current = idemKey;
    let succeeded = false;
    try {
      const res = await apiSend('/api/campaigns', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key': idemKey,
        },
        body: JSON.stringify({
          sender,
          recipients,
          message: trimmedMessage,
          sendAt: mode === 'schedule' ? sendAt : null,
          attachmentId: attachment?.attachmentId ?? null,
          sendChannel,
        }),
      });
      const json = (await res.json()) as {
        data?: { id: string };
        error?: { code: string; message: string };
      };
      if (!res.ok || json.error) {
        throw new Error(json.error?.message ?? `HTTP ${res.status}`);
      }
      succeeded = true;
      idemKeyRef.current = null; // 성공 — 다음 발송은 새 키 사용
      router.push('/campaigns');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      // 성공 시에도 router.push 가 동기 반환이라 navigation 직후 상태 리셋해야
      // 잔류 disabled 로 다음 진입 시 버튼이 막히는 문제를 방지한다.
      // 단 succeeded 인 경우 submitting=true 유지해 중복 제출 차단 (페이지 전환 전까지).
      if (!succeeded) {
        submittingRef.current = false;
        setSubmitting(false);
      }
    }
  };

  // 요약 패널 표시값
  const senderLabel = senderOptions.find((s) => s.value === sender)?.label ?? '—';
  const matchedCount = recipients.filter((r) => cidNames[toDigits(r)]).length;
  const channelSummary = sendChannel === 'rcs' ? `RCS · 안 되면 ${displayChannel}` : displayChannel;
  const whenSummary =
    mode === 'now' ? '접수 즉시' : sendAt ? sendAt.replace('T', ' ') : '예약 시각을 고르세요';
  const costSummary =
    estimate?.valid && estimate.costMin !== null && estimate.costMax !== null
      ? `₩${estimate.costMin.toLocaleString('ko-KR')}${
          estimate.costMin === estimate.costMax ? '' : ` ~ ₩${estimate.costMax.toLocaleString('ko-KR')}`
        }`
      : checking
        ? '확인 중'
        : '—';
  // 바이트 미터: SMS 경계(90 bytes)까지를 막대의 약 40% 위치에 두고 LMS 한도(2,000)까지 그린다
  const meterPct = bytes == null ? 0 : Math.min(100, (bytes / 225) * 100);

  return (
    <form onSubmit={onSubmit} className="mt-2 flex flex-wrap items-start gap-6">
      <div className="flex min-w-0 max-w-[720px] flex-[999_1_520px] flex-col gap-4">
        <section aria-labelledby="compose-recipients" className="k-card k-card-pad flex flex-col gap-5">
          <h2 id="compose-recipients" className="k-card-title">
            받는 사람
          </h2>
          <Field
            label="발신번호"
            htmlFor="sender"
            required
            hint={senderLoading ? '발신번호 불러오는 중...' : undefined}
            error={senderError ?? undefined}
          >
            <select
              id="sender"
              value={sender}
              onChange={(e) => setSender(e.target.value)}
              disabled={senderLoading || senderOptions.length === 0}
              className="h-[36px] w-full rounded border border-line-strong bg-surface px-3 text-base focus:border-brand focus:shadow-[0_0_0_3px_var(--brand-soft)] focus-visible:outline-none disabled:bg-surface-subtle disabled:text-ink-dim"
            >
              {senderLoading ? (
                <option value="">불러오는 중...</option>
              ) : senderOptions.length === 0 ? (
                <option value="">승인된 발신번호 없음</option>
              ) : (
                senderOptions.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))
              )}
            </select>
          </Field>

          <Field
            label="수신자"
            htmlFor="recipients"
            required
            hint="휴대폰·전화번호 입력 후 Enter 또는 쉼표(하이픈 있어도 됨). 캠페인당 최대 1,000명"
            error={
              invalidRecipients.length > 0
                ? `번호 형식이 틀렸습니다: ${invalidRecipients.slice(0, 5).join(', ')}${
                    invalidRecipients.length > 5 ? ` 외 ${invalidRecipients.length - 5}건` : ''
                  }`
                : undefined
            }
            counter={{
              value: `${recipients.length} / 1,000명`,
              state: recipientsState,
            }}
          >
            <ChipField
              id="recipients"
              aria-label="수신자 목록"
              value={recipients}
              onChange={setRecipients}
              placeholder="예) 010-1234-5678"
              maxChips={1000}
              invalid={recipientsState === 'err'}
            />
            {(() => {
              const matched = recipients
                .map((r) => ({ phone: r, cid: cidNames[toDigits(r)] }))
                .filter((x) => x.cid);
              if (matched.length === 0) return null;
              return (
                <div className="mt-2 rounded border border-line bg-surface-subtle p-2 text-sm text-ink-muted">
                  <span className="text-ink-dim">주소록 매칭 </span>
                  <span className="font-medium text-ink">
                    {matched.length}/{recipients.length}명
                  </span>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {matched.slice(0, 12).map((x) => (
                      <span
                        key={x.phone}
                        className="rounded bg-surface px-1.5 py-0.5 text-xs text-ink"
                        title={formatPhone(x.phone)}
                      >
                        {x.cid!.display}
                      </span>
                    ))}
                    {matched.length > 12 && (
                      <span className="px-1 py-0.5 text-ink-dim">
                        외 {matched.length - 12}명
                      </span>
                    )}
                  </div>
                </div>
              );
            })()}
          </Field>
        </section>

        <section aria-labelledby="compose-message" className="k-card k-card-pad flex flex-col gap-5">
          <h2 id="compose-message" className="k-card-title">
            메시지
          </h2>
          <Field
            label="전송 방식"
            required
            hint="일반은 표준 SMS/LMS/MMS, RCS는 브랜드 발신·읽음확인 등 리치 기능"
          >
            {/* 선택지마다 한 문장 설명이 붙는 고르기라 테두리 있는 카드로 나란히 둔다 */}
            <div className="grid grid-cols-[repeat(auto-fit,minmax(220px,1fr))] gap-3">
              {(
                [
                  {
                    value: 'rcs' as const,
                    label: 'RCS',
                    sub: '브랜드 발신(읽음 확인 가능, 채팅처럼 문자 수신 및 답장 소통 가능)',
                  },
                  {
                    value: 'sms' as const,
                    label: '일반 (SMS/LMS/MMS)',
                    sub: '표준 문자 (단순 공지, 알림, 문자 수신 및 답장 불가능한 단방향)',
                  },
                ]
              ).map((o) => (
                <div
                  key={o.value}
                  className={
                    sendChannel === o.value
                      ? 'flex rounded-lg border border-brand bg-brand-soft shadow-[inset_0_0_0_1px_var(--brand)] [&>label]:p-3'
                      : 'flex rounded-lg border border-line-strong bg-surface [&>label]:p-3'
                  }
                >
                  <Radio
                    name="sendChannel"
                    value={o.value}
                    checked={sendChannel === o.value}
                    onChange={() => setSendChannel(o.value)}
                    label={o.label}
                    sub={o.sub}
                    // 카드 전체를 눌러도 고를 수 있게 라벨을 카드 폭만큼 늘린다
                    className="flex w-full items-start"
                  />
                </div>
              ))}
            </div>
          </Field>

          <Field
            label="메시지"
            htmlFor="msg"
            required
            hint={`자동 채널: ${sendChannel === 'rcs' ? 'RCS·' : ''}${displayChannel} · ${lengthLabel}`}
            counter={{
              value: lengthLabel,
              state: bytesState,
            }}
          >
            {/* 변수·템플릿·이미지·링크 도구는 모두 비활성(미구현)이라 뺐다. 이미지는 아래 첨부 칸에서 넣는다. */}
            <Editor
              id="msg"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="본문을 입력하세요..."
              invalid={bytesState === 'err'}
              rows={6}
              footer={
                <div className="flex w-full flex-col gap-1.5">
                  <div className="relative h-1.5 rounded-full bg-gray-3" aria-hidden>
                    <div
                      className={
                        bytes != null && bytes > 90
                          ? 'absolute inset-y-0 left-0 rounded-full bg-warning'
                          : 'absolute inset-y-0 left-0 rounded-full bg-brand'
                      }
                      style={{ width: `${meterPct}%` }}
                    />
                    {/* SMS 경계 90 bytes */}
                    <div className="absolute -top-[3px] h-3 w-0.5 rounded bg-gray-7" style={{ left: '40%' }} />
                  </div>
                  <div className="flex justify-between gap-3">
                    <span className="tabular-nums">
                      {lengthLabel} · {displayChannel}
                    </span>
                    <span role="status" aria-live="polite" className="tabular-nums text-ink-dim">
                      {costLabel}
                    </span>
                  </div>
                </div>
              }
            />
            {previewError && (
              <div role="alert" className="mt-1 text-xs text-danger">
                {previewError}
                {currentPreview?.failure && (
                  <button
                    type="button"
                    onClick={() => setPreviewAttempt((attempt) => attempt + 1)}
                    disabled={submitting}
                    className="ml-2 underline"
                  >
                    다시 확인
                  </button>
                )}
              </div>
            )}
            {estimate?.valid && estimate.costMin !== estimate.costMax && (
              <p className="mt-1 text-xs text-ink-dim">
                RCS 미지원 시 일반 문자로 대체되며, 실제 비용은 전달 결과에 따라 달라집니다.
              </p>
            )}
          </Field>

          <Field label="첨부 이미지" hint="선택 — 첨부 시 MMS 로 전송됩니다. JPEG/PNG/WebP 허용, 최대 10MB.">
            <AttachmentPicker
              value={attachment}
              onChange={setAttachment}
              disabled={submitting}
            />
          </Field>
        </section>

        <section aria-labelledby="compose-when" className="k-card k-card-pad flex flex-col gap-4">
          <h2 id="compose-when" className="k-card-title">
            보낼 시각
          </h2>
          <Field label="발송 방식" required>
            <div className="flex flex-wrap gap-x-6 gap-y-2">
              <Radio
                name="mode"
                value="now"
                checked={mode === 'now'}
                onChange={() => setMode('now')}
                label="즉시 발송"
                sub="접수 후 바로 전송"
              />
              <Radio
                name="mode"
                value="schedule"
                checked={mode === 'schedule'}
                onChange={() => setMode('schedule')}
                label="예약"
                sub="지정 시간에 전송"
              />
            </div>
            {mode === 'schedule' && (
              <Input
                type="datetime-local"
                aria-label="예약 발송 시간"
                value={sendAt}
                onChange={(e) => setSendAt(e.target.value)}
                className="mt-2 max-w-[260px]"
              />
            )}
          </Field>
        </section>
      </div>

      {/* 오른쪽: 미리보기와 요약. 넓은 화면에서는 스크롤해도 따라온다. */}
      <aside
        aria-label="발송 요약"
        className="flex min-w-0 max-w-[400px] flex-[1_1_320px] flex-col gap-4 lg:sticky lg:top-6"
      >
        <section aria-labelledby="compose-preview" className="k-card overflow-hidden">
          <div className="k-card-hd">
            <h2 id="compose-preview" className="k-card-title">
              미리보기
            </h2>
            <span className="text-xs font-semibold text-ink-muted">
              {sendChannel === 'rcs' ? 'RCS' : displayChannel}
            </span>
          </div>
          <div className="flex flex-col gap-2 bg-surface-subtle p-4">
            <span className="text-xs font-semibold text-ink-muted">{senderLabel}</span>
            <div className="max-w-[92%] whitespace-pre-wrap break-words rounded-2xl rounded-tl-md border border-line bg-surface px-3 py-2 text-md text-ink">
              {trimmedMessage || <span className="text-ink-dim">본문을 입력하면 여기에 보입니다.</span>}
            </div>
            {attachment && <span className="text-xs text-ink-dim">이미지 1장 첨부 · MMS</span>}
          </div>
        </section>

        <section aria-labelledby="compose-summary" className="k-card k-card-pad flex flex-col gap-4">
          <h2 id="compose-summary" className="k-card-title">
            요약
          </h2>
          <dl className="m-0 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-2 text-md">
            <dt className="text-ink-muted">받는 사람</dt>
            <dd className="m-0 text-right font-semibold tabular-nums text-ink">
              {recipients.length.toLocaleString('ko-KR')}명
              {matchedCount > 0 && (
                <span className="ml-1 font-normal text-ink-dim">(주소록 {matchedCount}명)</span>
              )}
            </dd>
            <dt className="text-ink-muted">채널</dt>
            <dd className="m-0 text-right font-semibold text-ink">{channelSummary}</dd>
            <dt className="text-ink-muted">보낼 시각</dt>
            <dd className="m-0 text-right font-semibold tabular-nums text-ink">{whenSummary}</dd>
            <dt className="text-ink-muted">예상 비용</dt>
            <dd className="m-0 text-right font-semibold tabular-nums text-ink">
              {costSummary}
              <span className="ml-1 text-xs font-normal text-ink-dim">VAT 별도</span>
            </dd>
          </dl>
          <div className="border-t border-line pt-3">
            <Check
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
              label="수신자 모두에게 발송됨을 확인했습니다"
              sub={
                recipients.length > 100
                  ? '고위험 대량 발송 · 접수 후 취소 불가'
                  : undefined
              }
            />
          </div>

          {error && (
            <div
              role="alert"
              className="rounded border border-danger/30 bg-danger-bg px-3 py-2 text-sm text-danger"
            >
              {error}
            </div>
          )}

          <div className="flex flex-col gap-2">
            <Button
              type="submit"
              variant="primary"
              size="lg"
              full
              icon={<Icon name="send" size={14} />}
              loading={submitting}
              disabled={!canSubmit}
            >
              {mode === 'schedule' ? '예약 등록' : '발송'}
            </Button>
            <Button type="button" variant="ghost" full onClick={() => router.push('/')}>
              취소
            </Button>
          </div>
        </section>
      </aside>
    </form>
  );
}
