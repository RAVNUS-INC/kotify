'use client';

import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import {
  Button,
  Check,
  ChipField,
  Editor,
  EditorToolbarButton,
  EditorToolbarDivider,
  Field,
  Icon,
  Input,
  Radio,
} from '@/components/ui';
import type { UploadedAttachment } from '@/lib/campaigns-client';
import { apiSend } from '@/lib/csrf-client';
import { formatPhone } from '@/lib/phone';
import type { SenderNumber } from '@/types/number';
import { AttachmentPicker } from './AttachmentPicker';

type SendMode = 'now' | 'schedule';
type SendChannel = 'rcs' | 'sms';

type Sender = { value: string; label: string };

const SMS_BYTES = 90;
const LMS_BYTES = 2000;

export function computeEstimate(
  message: string,
  recipientCount: number,
  hasAttachment = false,
  sendChannel: 'rcs' | 'sms' = 'rcs',
) {
  // 단가: U+ msghub 공식(VAT 별도, 백엔드 PRICE_TABLE 과 일치).
  // 채널 판정은 백엔드 _classify_msg_type 와 동일하게 — 첨부(이미지)가 있으면
  // MMS, 아니면 본문 바이트로 단문/장문. 보수적으로 채널 단가를 표시한다.
  // 단문만 전송 방식에 따라 갈린다: RCS 17 / 일반 SMS 9. 장문(27)·이미지(85)는 동일.
  const bytes = new TextEncoder().encode(message).length;
  let channel: 'SMS' | 'LMS' | 'MMS' = 'SMS';
  let perUnit = sendChannel === 'sms' ? 9 : 17; // 단문: 일반 SMS 9 / RCS 17
  if (hasAttachment) {
    channel = 'MMS';
    perUnit = 85; // 이미지(첨부): RCS MMS형 RPMSMMX001 = productCode MMS = 85
  } else if (bytes > LMS_BYTES) {
    channel = 'MMS';
    perUnit = 85; // 초장문(>2000B)
  } else if (bytes > SMS_BYTES) {
    channel = 'LMS';
    perUnit = 27; // 장문: RCS LMS = LMS fallback = 27
  }
  const cost = recipientCount * perUnit;
  const bytesState: 'warn' | 'err' | undefined =
    bytes > LMS_BYTES ? 'err' : bytes > SMS_BYTES ? 'warn' : undefined;
  return { bytes, channel, perUnit, cost, bytesState };
}

export function ComposeForm() {
  const router = useRouter();
  // 발신번호는 /api/numbers?status=approved 에서 런타임 로드.
  // 하드코딩 리스트는 운영 사용자마다 보유 번호가 달라 data-correctness 버그의 원인이 됐음.
  const [senderOptions, setSenderOptions] = useState<ReadonlyArray<Sender>>([]);
  const [senderLoading, setSenderLoading] = useState(true);
  const [senderError, setSenderError] = useState<string | null>(null);
  const [sender, setSender] = useState<string>('');
  const [recipients, setRecipients] = useState<string[]>([]);
  const [message, setMessage] = useState('');
  // 기본값 없음 — 사용자가 일반/RCS 를 직접 선택해야 발송 가능(침묵의 기본값 방지).
  const [sendChannel, setSendChannel] = useState<SendChannel | null>(null);
  const [mode, setMode] = useState<SendMode>('now');
  const [sendAt, setSendAt] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [attachment, setAttachment] = useState<UploadedAttachment | null>(null);

  // 발신번호 로딩 (승인된 번호만). stale response race 방어를 위해 cancelled flag.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch('/api/numbers?status=approved');
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

  // bytes/bytesState 는 채널과 무관(본문 길이 한계 경고용)이라 항상 계산.
  // cost/channel 은 전송 방식 선택 후에만 표시(아래 channelChosen 게이트).
  const { bytes, channel, cost, bytesState } = useMemo(
    () => computeEstimate(message, recipients.length, attachment != null, sendChannel ?? 'rcs'),
    [message, recipients.length, attachment, sendChannel],
  );
  const channelChosen = sendChannel != null;

  const recipientsState: 'warn' | 'err' | undefined =
    recipients.length > 1000 ? 'err' : recipients.length > 500 ? 'warn' : undefined;

  const canSubmit =
    sender !== '' &&
    !senderLoading &&
    recipients.length > 0 &&
    recipients.length <= 1000 &&
    message.trim() !== '' &&
    bytesState !== 'err' &&
    (mode === 'now' || sendAt !== '') &&
    channelChosen &&
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
  }, [sender, recipients, message, sendAt, mode, attachment]);

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
          message,
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

  return (
    <form onSubmit={onSubmit} className="mt-6 max-w-[560px]">
      <div className="flex flex-col gap-5">
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
            className="h-9 w-full rounded border border-gray-4 bg-surface px-3 text-md focus:border-brand focus:shadow-[0_0_0_3px_rgba(59,0,139,0.08)] focus:outline-none disabled:bg-gray-1 disabled:text-ink-dim"
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
          hint="이름·번호·그룹 입력 후 Enter 또는 쉼표. 캠페인당 최대 1,000명"
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
        </Field>

        <Field label="CSV 업로드" hint="수신자 목록을 일괄 추가 (준비 중)">
          <Button
            type="button"
            variant="secondary"
            size="md"
            icon={<Icon name="upload" size={12} />}
            disabled
          >
            CSV 파일 선택
          </Button>
        </Field>

        <Field
          label="전송 방식"
          required
          hint="일반은 표준 SMS/LMS/MMS, RCS는 브랜드 발신·읽음확인 등 리치 기능"
        >
          <div className="flex flex-col gap-2">
            <Radio
              name="sendChannel"
              value="sms"
              checked={sendChannel === 'sms'}
              onChange={() => setSendChannel('sms')}
              label="일반 (SMS/LMS/MMS)"
              sub="표준 문자 (단순 공지, 알림, 문자 수신 및 답장 불가능한 단방향)"
            />
            <Radio
              name="sendChannel"
              value="rcs"
              checked={sendChannel === 'rcs'}
              onChange={() => setSendChannel('rcs')}
              label="RCS"
              sub="브랜드 발신(읽음 확인 가능, 채팅처럼 문자 수신 및 답장 소통 가능)"
            />
          </div>
        </Field>

        <Field
          label="메시지"
          htmlFor="msg"
          required
          hint={
            channelChosen
              ? `자동 채널: ${sendChannel === 'rcs' ? 'RCS·' : ''}${channel} · ${bytes} bytes`
              : `${bytes} bytes · 전송 방식을 선택하세요`
          }
          counter={{
            value: `${bytes} bytes`,
            state: bytesState,
          }}
          error={
            bytesState === 'err'
              ? 'MMS 본문 한계(2,000 bytes)를 초과했습니다'
              : undefined
          }
        >
          <Editor
            id="msg"
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            placeholder="본문을 입력하세요..."
            invalid={bytesState === 'err'}
            rows={6}
            toolbar={
              <>
                <EditorToolbarButton
                  icon={<Icon name="hash" size={12} />}
                  disabled
                >
                  변수
                </EditorToolbarButton>
                <EditorToolbarButton
                  icon={<Icon name="fileText" size={12} />}
                  disabled
                >
                  템플릿
                </EditorToolbarButton>
                <EditorToolbarDivider />
                <EditorToolbarButton
                  icon={<Icon name="image" size={12} />}
                  disabled
                >
                  이미지
                </EditorToolbarButton>
                <EditorToolbarButton
                  icon={<Icon name="link" size={12} />}
                  disabled
                >
                  링크
                </EditorToolbarButton>
              </>
            }
            footer={
              <>
                <span className="font-mono">
                  {bytes} bytes{channelChosen ? ` · ${channel}` : ''}
                </span>
                <span className="font-mono text-ink-dim">
                  {channelChosen
                    ? `예상 ${recipients.length}건 · ₩${cost.toLocaleString('ko-KR')}`
                    : '전송 방식 선택 후 견적'}
                </span>
              </>
            }
          />
        </Field>

        <Field label="첨부 이미지" hint="선택 — 첨부 시 MMS 로 전송됩니다. JPEG/PNG/WebP 허용, 최대 10MB.">
          <AttachmentPicker
            value={attachment}
            onChange={setAttachment}
            disabled={submitting}
          />
        </Field>

        <Field label="발송 방식" required>
          <div className="flex flex-col gap-2">
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
            {mode === 'schedule' && (
              <Input
                type="datetime-local"
                aria-label="예약 발송 시간"
                value={sendAt}
                onChange={(e) => setSendAt(e.target.value)}
                className="ml-6 mt-1 max-w-[260px]"
              />
            )}
          </div>
        </Field>

        <Field label="확인" required>
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
        </Field>

        {error && (
          <div
            role="alert"
            className="rounded border border-danger/30 bg-danger-bg px-3 py-2 text-sm text-danger"
          >
            {error}
          </div>
        )}

        <div className="flex items-center justify-end gap-2 pt-2">
          <Button
            type="button"
            variant="ghost"
            onClick={() => router.push('/')}
          >
            취소
          </Button>
          <Button
            type="submit"
            variant="primary"
            icon={<Icon name="send" size={12} />}
            loading={submitting}
            disabled={!canSubmit}
          >
            {mode === 'schedule' ? '예약 등록' : '발송'}
          </Button>
        </div>
      </div>
    </form>
  );
}
