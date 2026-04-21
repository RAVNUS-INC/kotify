'use client';

import { useState } from 'react';
import {
  Check,
  Field,
  Icon,
  Input,
  Radio,
  SearchInput,
  Segmented,
  Textarea,
  Toggle,
} from '@/components/ui';

type Channel = 'rcs' | 'sms' | 'lms';

export function FormsSample() {
  const [name, setName] = useState('');
  const [msg, setMsg] = useState('');
  const [query, setQuery] = useState('');
  const [agree, setAgree] = useState(false);
  const [partial, setPartial] = useState(true);
  const [channel, setChannel] = useState<Channel>('rcs');
  const [immediate, setImmediate] = useState(true);
  const [realtime, setRealtime] = useState(false);

  const bytes = new TextEncoder().encode(msg).length;
  const bytesState: 'warn' | 'err' | undefined =
    bytes > 180 ? 'err' : bytes > 140 ? 'warn' : undefined;

  return (
    <div className="grid gap-8">
      <div className="grid grid-cols-2 gap-5">
        <Field label="이름" required hint="실명을 입력하세요">
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="홍길동"
          />
        </Field>

        <Field
          label="발송 번호"
          htmlFor="from"
          hint="승인된 번호만 표시됩니다"
        >
          <Input
            id="from"
            prefix={<Icon name="phone" size={12} />}
            defaultValue="1588-1234"
            inputSize="md"
          />
        </Field>

        <Field label="조직 도메인" htmlFor="org">
          <Input
            id="org"
            suffix={<span className="text-ink-muted">.kotify.io</span>}
            defaultValue="ravnus"
          />
        </Field>

        <Field
          label="이메일"
          htmlFor="email"
          error="이미 사용 중인 이메일입니다"
        >
          <Input
            id="email"
            type="email"
            defaultValue="taken@example.com"
            invalid
          />
        </Field>

        <Field label="검색" htmlFor="q">
          <SearchInput
            id="q"
            placeholder="이름·번호·그룹"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onClear={() => setQuery('')}
            kbd={query ? undefined : '⌘K'}
          />
        </Field>

        <Field
          label="전체 상태"
          hint="브라우저가 indeterminate 표시"
        >
          <Check
            checked={false}
            partial={partial}
            label="부분 선택 (3/10)"
            onChange={() => setPartial((p) => !p)}
          />
        </Field>
      </div>

      <Field
        label="메시지 본문"
        htmlFor="msg"
        hint="140바이트 초과 시 LMS로 전환됩니다"
        counter={{
          value: `${bytes} / 180 bytes`,
          state: bytesState,
        }}
      >
        <Textarea
          id="msg"
          rows={4}
          value={msg}
          onChange={(e) => setMsg(e.target.value)}
          placeholder="본문을 입력하세요"
          invalid={bytesState === 'err'}
        />
      </Field>

      <div className="grid grid-cols-2 gap-5">
        <Field label="채널">
          <div className="flex flex-col gap-2">
            <Radio
              name="channel"
              value="rcs"
              checked={channel === 'rcs'}
              onChange={() => setChannel('rcs')}
              label="RCS"
              sub="리치 카드·버튼 지원"
            />
            <Radio
              name="channel"
              value="sms"
              checked={channel === 'sms'}
              onChange={() => setChannel('sms')}
              label="SMS"
              sub="90바이트 텍스트"
            />
            <Radio
              name="channel"
              value="lms"
              checked={channel === 'lms'}
              onChange={() => setChannel('lms')}
              label="LMS"
              sub="2,000자 장문"
            />
          </div>
        </Field>

        <Field label="설정">
          <div className="flex flex-col gap-3">
            <Toggle
              checked={immediate}
              onChange={setImmediate}
              label="즉시 발송"
              sub="예약 발송을 사용하지 않음"
            />
            <Toggle
              checked={realtime}
              onChange={setRealtime}
              label="실시간 결과 알림"
              sub="Slack 웹훅 연동 필요"
            />
            <Check
              checked={agree}
              onChange={(e) => setAgree(e.target.checked)}
              label="수신자 동의 확인"
              sub="고위험 발송의 경우 2단 확인"
            />
          </div>
        </Field>
      </div>

      <Field label="발송 이력 필터">
        <Segmented
          items={[
            { value: 'all', label: '전체' },
            { value: 'sending', label: '진행' },
            { value: 'scheduled', label: '예약' },
            { value: 'failed', label: '실패' },
          ]}
          value="all"
          onChange={() => {}}
          aria-label="상태 필터"
        />
      </Field>
    </div>
  );
}
