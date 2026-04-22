'use client';

import { useState, useEffect, type FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import { Button, Drawer, Field, Icon, Input, Textarea } from '@/components/ui';
import {
  createContactClient,
  updateContactClient,
  type ContactInput,
} from '@/lib/contacts-client';
import type { Contact } from '@/types/contact';

export type ContactFormDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** undefined 면 create 모드, Contact 가 전달되면 edit 모드. */
  contact?: Contact;
};

export function ContactFormDialog({
  open,
  onOpenChange,
  contact,
}: ContactFormDialogProps) {
  const router = useRouter();
  const mode: 'create' | 'edit' = contact ? 'edit' : 'create';

  const [name, setName] = useState('');
  const [phone, setPhone] = useState('');
  const [email, setEmail] = useState('');
  const [team, setTeam] = useState('');
  const [notes, setNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    // 열릴 때마다 상태를 contact prop 기준으로 reset — create 면 빈 값.
    setName(contact?.name ?? '');
    setPhone(contact?.phone ?? '');
    setEmail(contact?.email ?? '');
    setTeam(contact?.team ?? '');
    setNotes('');
    setError(null);
    setSubmitting(false);
  }, [open, contact]);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (submitting) return;
    if (!name.trim()) {
      setError('이름을 입력하세요');
      return;
    }
    setSubmitting(true);
    setError(null);

    const input: ContactInput = {
      name: name.trim(),
      phone: phone.trim() || null,
      email: email.trim() || null,
      team: team.trim() || null,
      notes: notes.trim() || null,
    };

    try {
      if (mode === 'edit' && contact) {
        await updateContactClient(contact.id, input);
      } else {
        await createContactClient(input);
      }
      onOpenChange(false);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : '저장 실패');
      setSubmitting(false);
    }
  };

  return (
    <Drawer
      open={open}
      onOpenChange={onOpenChange}
      width={400}
      title={mode === 'edit' ? '연락처 수정' : '새 연락처'}
      footer={
        <div className="flex items-center justify-end gap-2">
          <Button
            variant="ghost"
            size="md"
            onClick={() => onOpenChange(false)}
            disabled={submitting}
          >
            취소
          </Button>
          <Button
            variant="primary"
            size="md"
            type="submit"
            form="contact-form"
            loading={submitting}
            icon={<Icon name="check" size={12} />}
          >
            {mode === 'edit' ? '저장' : '등록'}
          </Button>
        </div>
      }
    >
      <form id="contact-form" onSubmit={onSubmit} className="space-y-4">
        <Field label="이름" required>
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoFocus
            disabled={submitting}
            required
          />
        </Field>
        <Field label="전화번호" hint="하이픈/공백 허용 — 숫자만 저장됩니다.">
          <Input
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder="010-1234-5678"
            disabled={submitting}
          />
        </Field>
        <Field label="이메일">
          <Input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="example@domain.com"
            disabled={submitting}
          />
        </Field>
        <Field label="팀/부서">
          <Input
            value={team}
            onChange={(e) => setTeam(e.target.value)}
            placeholder="예) 영업"
            disabled={submitting}
          />
        </Field>
        <Field label="메모">
          <Textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={3}
            disabled={submitting}
          />
        </Field>
        {error ? (
          <div className="rounded border border-danger/30 bg-danger/5 p-2 text-sm text-danger" role="alert">
            {error}
          </div>
        ) : null}
      </form>
    </Drawer>
  );
}
