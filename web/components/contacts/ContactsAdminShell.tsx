'use client';

import { useState } from 'react';
import { Button, Icon } from '@/components/ui';
import { buildContactsExportHref } from '@/lib/contacts-client';
import { ContactFormDialog } from './ContactFormDialog';
import { ContactImportDialog } from './ContactImportDialog';

export type ContactsAdminShellProps = {
  canManage: boolean;
};

/**
 * S7 페이지 상단 액션 영역을 client-side 로 감싸 "새 연락처"/"CSV 가져오기"/
 * "CSV 내보내기" 를 드라이버. 테이블 내부 행 액션(수정/삭제) 은
 * ContactRowActions 에서 별도 처리.
 */
export function ContactsAdminShell({ canManage }: ContactsAdminShellProps) {
  const [createOpen, setCreateOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);

  return (
    <>
      <div className="flex items-center gap-2">
        <a
          href={buildContactsExportHref()}
          className="inline-flex h-7 items-center gap-1.5 rounded border border-gray-4 bg-surface px-2.5 text-sm font-medium text-ink transition-colors duration-fast ease-out hover:bg-gray-1"
          download
        >
          <Icon name="download" size={12} />
          CSV 내보내기
        </a>
        {canManage ? (
          <>
            <Button
              variant="ghost"
              size="sm"
              icon={<Icon name="upload" size={12} />}
              onClick={() => setImportOpen(true)}
            >
              CSV 가져오기
            </Button>
            <Button
              variant="primary"
              size="sm"
              icon={<Icon name="plus" size={12} />}
              onClick={() => setCreateOpen(true)}
            >
              새 연락처
            </Button>
          </>
        ) : null}
      </div>

      {canManage ? (
        <>
          <ContactFormDialog open={createOpen} onOpenChange={setCreateOpen} />
          <ContactImportDialog open={importOpen} onOpenChange={setImportOpen} />
        </>
      ) : null}
    </>
  );
}
