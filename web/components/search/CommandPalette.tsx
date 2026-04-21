'use client';

import * as Dialog from '@radix-ui/react-dialog';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from 'react';
import type { Route } from 'next';
import { Icon, Kbd } from '@/components/ui';
import { searchClient } from '@/lib/search';
import type { SearchResult } from '@/types/search';
import { cn } from '@/lib/cn';
import { HighlightText } from './HighlightText';

type Item = {
  href: Route;
  primary: string;
  secondary?: string;
  icon: Parameters<typeof Icon>[0]['name'];
  section: '주소록' | '대화' | '캠페인' | '감사';
};

const SECTION_LIMIT = 4;

function buildItems(q: string, r: SearchResult): Item[] {
  const items: Item[] = [];
  r.contacts.slice(0, SECTION_LIMIT).forEach((c) =>
    items.push({
      href: (`/contacts?selected=${encodeURIComponent(c.id)}`) as Route,
      primary: c.name,
      secondary: c.phone,
      icon: 'user',
      section: '주소록',
    }),
  );
  r.threads.slice(0, SECTION_LIMIT).forEach((t) =>
    items.push({
      href: (`/chat/${encodeURIComponent(t.id)}`) as Route,
      primary: t.name,
      secondary: t.snippet,
      icon: 'chat',
      section: '대화',
    }),
  );
  r.campaigns.slice(0, SECTION_LIMIT).forEach((c) =>
    items.push({
      href: (`/campaigns/${encodeURIComponent(c.id)}`) as Route,
      primary: c.name,
      secondary: c.createdAt,
      icon: 'zap',
      section: '캠페인',
    }),
  );
  r.auditLogs.slice(0, SECTION_LIMIT).forEach((a) =>
    items.push({
      href: (`/audit?q=${encodeURIComponent(q)}`) as Route,
      primary: a.actor,
      secondary: `${a.action} · ${a.target}`,
      icon: 'fileText',
      section: '감사',
    }),
  );
  return items;
}

export function CommandPalette() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const [result, setResult] = useState<SearchResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  // 글로벌 ⌘K 단축키
  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setOpen((v) => !v);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  // 열릴 때 q 초기화·포커스
  useEffect(() => {
    if (open) {
      setQ('');
      setResult(null);
      setActive(0);
      const t = setTimeout(() => inputRef.current?.focus(), 50);
      return () => clearTimeout(t);
    }
  }, [open]);

  // debounced search
  useEffect(() => {
    const query = q.trim();
    if (!query) {
      setResult(null);
      setLoading(false);
      return;
    }
    const t = setTimeout(async () => {
      setLoading(true);
      try {
        const r = await searchClient(query);
        setResult(r);
        setActive(0);
      } catch {
        setResult(null);
      } finally {
        setLoading(false);
      }
    }, 200);
    return () => clearTimeout(t);
  }, [q]);

  const items = result ? buildItems(q, result) : [];

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    const query = q.trim();
    if (!query) return;
    const target = items[active];
    if (target) {
      router.push(target.href);
    } else {
      router.push(`/search?q=${encodeURIComponent(query)}` as Route);
    }
    setOpen(false);
  };

  const onKeyDown = useCallback(
    (e: KeyboardEvent<HTMLInputElement>) => {
      if (e.nativeEvent.isComposing) return;
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setActive((i) => Math.min(i + 1, Math.max(items.length - 1, 0)));
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setActive((i) => Math.max(i - 1, 0));
      }
    },
    [items.length],
  );

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <button
          type="button"
          aria-label="검색 (Cmd+K)"
          className="k-btn k-btn-ghost k-btn-sm"
        >
          <Icon name="search" size={13} />
          <Kbd className="ml-1">⌘K</Kbd>
        </button>
      </Dialog.Trigger>

      <Dialog.Portal>
        <Dialog.Overlay className="k-drawer-overlay fixed inset-0 z-[1060] bg-black/40" />
        <Dialog.Content
          className={cn(
            'k-cmd-content fixed left-1/2 top-1/2 z-[1060] w-full max-w-2xl -translate-x-1/2 -translate-y-1/2',
            'flex flex-col overflow-hidden rounded-lg border border-line bg-surface shadow-lg',
            'focus:outline-none',
          )}
          aria-describedby={undefined}
        >
          <Dialog.Title className="sr-only">통합 검색</Dialog.Title>

          <form onSubmit={onSubmit} className="border-b border-line">
            <div className="flex items-center gap-2 px-4 py-3">
              <Icon name="search" size={16} className="shrink-0 text-ink-dim" />
              <input
                ref={inputRef}
                value={q}
                onChange={(e) => setQ(e.target.value)}
                onKeyDown={onKeyDown}
                placeholder="주소록·대화·캠페인·감사 통합 검색"
                className="flex-1 bg-transparent text-md text-ink outline-none placeholder:text-ink-dim"
                autoComplete="off"
                spellCheck={false}
                aria-label="검색어"
              />
              {loading && (
                <span className="font-mono text-[10.5px] text-ink-dim">검색 중…</span>
              )}
              <Kbd>Esc</Kbd>
            </div>
          </form>

          <div className="max-h-[60vh] overflow-y-auto">
            {!q.trim() && (
              <div className="px-4 py-6 text-center text-sm text-ink-muted">
                <p>검색어를 입력하세요.</p>
                <p className="mt-1 font-mono text-[11px] text-ink-dim">
                  ↑↓로 이동 · Enter로 열기 · Esc로 닫기
                </p>
              </div>
            )}

            {q.trim() && items.length === 0 && !loading && (
              <div className="px-4 py-6 text-center text-sm text-ink-muted">
                &lsquo;{q}&rsquo;에 대한 결과가 없습니다.
              </div>
            )}

            {items.length > 0 && (
              <ul role="listbox" aria-label="검색 결과" className="flex flex-col py-1">
                {items.map((it, i) => (
                  <li key={`${it.section}-${it.href}`} role="option" aria-selected={i === active}>
                    <Link
                      href={it.href}
                      onClick={() => setOpen(false)}
                      onMouseEnter={() => setActive(i)}
                      className={cn(
                        'flex items-center gap-3 px-4 py-2 transition-colors duration-fast ease-out',
                        i === active ? 'bg-brand-soft' : 'hover:bg-gray-1',
                      )}
                    >
                      <Icon name={it.icon} size={13} className="shrink-0 text-ink-dim" />
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm text-ink">
                          <HighlightText text={it.primary} q={q} />
                        </div>
                        {it.secondary && (
                          <div className="truncate text-[11.5px] text-ink-muted">
                            <HighlightText text={it.secondary} q={q} />
                          </div>
                        )}
                      </div>
                      <span className="font-mono text-[10.5px] text-ink-dim">
                        {it.section}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {q.trim() && (
            <div className="flex items-center justify-between border-t border-line bg-gray-1 px-4 py-2 font-mono text-[11px] text-ink-dim">
              <span>Enter로 전체 결과 페이지</span>
              <span>↑↓ 이동 · Esc 닫기</span>
            </div>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
