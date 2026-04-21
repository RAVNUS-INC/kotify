'use client';

import { useState, type FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import type { Org } from '@/types/settings';
import { Button, Field, Icon, Input } from '@/components/ui';
import { patchOrgClient } from '@/lib/settings';

export type OrgSettingsFormProps = {
  initial: Org;
};

export function OrgSettingsForm({ initial }: OrgSettingsFormProps) {
  const router = useRouter();
  // baseline은 마지막 성공 저장값. dirty 판정에 사용.
  // initial prop과 분리해 trimmed sync 이후에도 dirty 계산이 정확.
  const [baseline, setBaseline] = useState(initial);
  const [name, setName] = useState(initial.name);
  const [service, setService] = useState(initial.service);
  const [contact, setContact] = useState(initial.contact);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const dirty =
    name !== baseline.name ||
    service !== baseline.service ||
    contact !== baseline.contact;

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!dirty || saving) return;
    setSaving(true);
    setError(null);
    setSaved(false);
    const trimmed = {
      name: name.trim(),
      service: service.trim(),
      contact: contact.trim(),
    };
    try {
      const updated = await patchOrgClient(trimmed);
      // 입력값이 trim되어 서버로 갔으니 로컬 state도 trimmed로 통일 + baseline 갱신.
      // 이후 "되돌리기"를 눌러도 저장된 값이 유지되고 dirty도 정확히 false.
      setName(trimmed.name);
      setService(trimmed.service);
      setContact(trimmed.contact);
      setBaseline(updated);
      setSaved(true);
      // Server Component가 stale initial prop을 갖고 있을 수 있으니 재실행 유도.
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const onReset = () => {
    setName(baseline.name);
    setService(baseline.service);
    setContact(baseline.contact);
    setError(null);
    setSaved(false);
  };

  return (
    <form
      onSubmit={onSubmit}
      className="flex flex-col gap-5 rounded-lg border border-line bg-surface p-5"
    >
      <div>
        <h2 className="text-base font-semibold text-ink">조직 정보</h2>
        <p className="mt-0.5 text-sm text-ink-muted">
          발송 화면 헤더·알림 메일 발신자에 표시됩니다.
        </p>
      </div>

      <Field label="조직명" htmlFor="org-name" required>
        <Input
          id="org-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="예) RAVNUS"
        />
      </Field>

      <Field
        label="서비스명"
        htmlFor="org-service"
        hint="고객 앞에 노출되는 제품/서비스 이름"
      >
        <Input
          id="org-service"
          value={service}
          onChange={(e) => setService(e.target.value)}
          placeholder="예) 사내 공지 시스템"
        />
      </Field>

      <Field label="대표 연락처" htmlFor="org-contact">
        <Input
          id="org-contact"
          type="email"
          value={contact}
          onChange={(e) => setContact(e.target.value)}
          placeholder="예) ops@ravnus.kr"
          prefix={<Icon name="at" size={12} />}
        />
      </Field>

      <Field label="타임존" hint="변경은 Phase 후속에 지원 예정">
        <Input value={baseline.timezone} readOnly disabled />
      </Field>

      <div className="rounded border border-line bg-gray-1 p-3 text-[12.5px] text-ink-muted">
        <div className="mb-1 font-mono text-[10.5px] uppercase tracking-[0.08em] text-ink-dim">
          조직 한도 (읽기 전용)
        </div>
        <div className="flex justify-between">
          <span>캠페인당 수신자</span>
          <span className="font-mono tabular-nums">
            {baseline.limits.recipientsPerCampaign.toLocaleString('ko-KR')}명
          </span>
        </div>
        <div className="mt-0.5 flex justify-between">
          <span>분당 캠페인</span>
          <span className="font-mono tabular-nums">
            {baseline.limits.campaignsPerMinute}건
          </span>
        </div>
      </div>

      {error && (
        <div
          role="alert"
          className="rounded border border-danger/30 bg-danger-bg px-3 py-2 text-sm text-danger"
        >
          {error}
        </div>
      )}
      {saved && !error && (
        <div
          role="status"
          className="rounded border border-success/30 bg-success-bg px-3 py-2 text-sm text-success"
        >
          저장되었습니다.
        </div>
      )}

      <div className="flex items-center justify-end gap-2">
        {dirty && !saving && (
          <Button type="button" variant="ghost" size="sm" onClick={onReset}>
            되돌리기
          </Button>
        )}
        <Button
          type="submit"
          variant="primary"
          size="sm"
          loading={saving}
          disabled={!dirty}
          icon={<Icon name="check" size={12} />}
        >
          저장
        </Button>
      </div>
    </form>
  );
}
