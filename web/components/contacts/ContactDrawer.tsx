'use client';

import { useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import type { Route } from 'next';
import type { ContactDetail } from '@/types/contact';
import {
  Badge,
  Button,
  Drawer,
  Icon,
  Pill,
} from '@/components/ui';
import { deleteContactClient } from '@/lib/contacts-client';
import { ContactFormDialog } from './ContactFormDialog';

export type ContactDrawerProps = {
  contact: ContactDetail | null;
  basePath: string;
  /** admin 이 아니면 편집/삭제 버튼 숨김. */
  canManage?: boolean;
};

export function ContactDrawer({
  contact,
  basePath,
  canManage = false,
}: ContactDrawerProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const open = contact !== null;
  const [editOpen, setEditOpen] = useState(false);
  const [busy, setBusy] = useState<'delete' | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const handleOpenChange = (next: boolean) => {
    if (next) return;
    // 쿼리에서 selected만 제거, 나머지(q 등) 보존
    const params = new URLSearchParams(Array.from(searchParams.entries()));
    params.delete('selected');
    const qs = params.toString();
    router.push((qs ? `${basePath}?${qs}` : basePath) as Route);
  };

  const onDelete = async () => {
    if (!contact || busy) return;
    if (!confirm(`${contact.name} 연락처를 삭제하시겠습니까?`)) return;
    setBusy('delete');
    setActionError(null);
    try {
      await deleteContactClient(contact.id);
      // drawer 닫고 목록 새로고침.
      handleOpenChange(false);
      router.refresh();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : '삭제 실패');
      setBusy(null);
    }
  };

  return (
    <Drawer
      open={open}
      onOpenChange={handleOpenChange}
      width={400}
      title={contact?.name ?? ''}
      description={contact?.phone ?? ''}
      footer={
        contact && canManage ? (
          <div className="flex flex-col gap-2">
            {actionError ? (
              <div
                className="text-[12px] text-danger"
                role="alert"
              >
                {actionError}
              </div>
            ) : null}
            <div className="flex items-center justify-between gap-2">
              <Button
                variant="ghost"
                size="sm"
                icon={<Icon name="edit" size={12} />}
                onClick={() => setEditOpen(true)}
                disabled={busy !== null}
              >
                편집
              </Button>
              <Button
                variant="danger"
                size="sm"
                icon={<Icon name="trash" size={12} />}
                onClick={onDelete}
                disabled={busy !== null}
                loading={busy === 'delete'}
              >
                삭제
              </Button>
            </div>
          </div>
        ) : null
      }
    >
      {contact && (
        <div className="flex flex-col gap-6 p-5">
          <Section title="기본 정보">
            <InfoRow label="이메일" value={contact.email ?? '—'} mono={!!contact.email} />
            <InfoRow label="팀" value={contact.team ?? '—'} />
            <InfoRow
              label="등록일"
              value={contact.createdAt ?? '—'}
              mono={!!contact.createdAt}
            />
          </Section>

          <Section title="태그">
            {contact.tags && contact.tags.length > 0 ? (
              <div className="flex flex-wrap gap-1.5">
                {contact.tags.map((t) => (
                  <Pill key={t} tone={t === 'VIP' ? 'brand' : 'neutral'}>
                    {t}
                  </Pill>
                ))}
              </div>
            ) : (
              <span className="text-sm text-ink-dim">태그 없음</span>
            )}
          </Section>

          <Section title="소속 그룹">
            {contact.groupIds && contact.groupIds.length > 0 ? (
              <div className="flex flex-wrap gap-1.5">
                {contact.groupIds.map((g) => (
                  <Badge key={g} kind="neutral" icon={<Icon name="user2" size={10} />}>
                    {g}
                  </Badge>
                ))}
              </div>
            ) : (
              <span className="text-sm text-ink-dim">소속 그룹 없음</span>
            )}
          </Section>

          <Section title="최근 받은 캠페인">
            {contact.recentCampaigns && contact.recentCampaigns.length > 0 ? (
              <ul className="flex flex-col gap-1.5">
                {contact.recentCampaigns.map((rc) => (
                  <li
                    key={rc.id}
                    className="flex items-center justify-between gap-2 rounded border border-line bg-gray-1 px-3 py-2 text-sm"
                  >
                    <span className="truncate">{rc.name}</span>
                    <span className="shrink-0 font-mono text-[11px] text-ink-dim">
                      {rc.sentAt.split(' ')[0]}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <span className="text-sm text-ink-dim">발송 이력 없음</span>
            )}
          </Section>

          <Section title="회신 이력">
            {contact.replyHistory && contact.replyHistory.length > 0 ? (
              <ul className="flex flex-col gap-2">
                {contact.replyHistory.map((rh) => (
                  <li
                    key={rh.id}
                    className="rounded border border-line bg-gray-1 p-3 text-sm"
                  >
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="truncate font-medium text-ink">
                        {rh.campaignName}
                      </span>
                      <span className="shrink-0 font-mono text-[11px] text-ink-dim">
                        {rh.at.split(' ')[1]}
                      </span>
                    </div>
                    <p className="mt-1 text-ink-muted">&ldquo;{rh.text}&rdquo;</p>
                  </li>
                ))}
              </ul>
            ) : (
              <span className="text-sm text-ink-dim">회신 없음</span>
            )}
          </Section>
        </div>
      )}
      {canManage && contact ? (
        <ContactFormDialog
          open={editOpen}
          onOpenChange={setEditOpen}
          contact={contact}
        />
      ) : null}
    </Drawer>
  );
}

type SectionProps = {
  title: string;
  children: React.ReactNode;
};

function Section({ title, children }: SectionProps) {
  return (
    <section>
      <h3 className="mb-2 font-mono text-[10.5px] font-medium uppercase tracking-[0.08em] text-ink-dim">
        {title}
      </h3>
      {children}
    </section>
  );
}

type InfoRowProps = {
  label: string;
  value: string;
  mono?: boolean;
};

function InfoRow({ label, value, mono }: InfoRowProps) {
  return (
    <div className="flex items-baseline justify-between gap-3 text-sm">
      <span className="text-ink-muted">{label}</span>
      <span className={mono ? 'font-mono text-ink' : 'text-ink'}>{value}</span>
    </div>
  );
}
