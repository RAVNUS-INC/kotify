import Link from 'next/link';
import type { Route } from 'next';
import { Icon, type IconName } from '@/components/ui';
import { cn } from '@/lib/cn';

export type SettingsTab = 'org' | 'messaging' | 'developers' | 'security';

type NavItem = {
  value: SettingsTab;
  label: string;
  icon: IconName;
  hint?: string;
};

const ITEMS: ReadonlyArray<NavItem> = [
  { value: 'org', label: '조직', icon: 'building', hint: '이름·연락처·한도' },
  { value: 'messaging', label: '메시징', icon: 'send', hint: '기본 채널·발신' },
  { value: 'developers', label: '개발자', icon: 'key', hint: 'API 키·웹훅' },
  { value: 'security', label: '보안', icon: 'shield', hint: 'SSO·세션' },
];

export type SettingsSidebarProps = {
  active: SettingsTab;
};

export function SettingsSidebar({ active }: SettingsSidebarProps) {
  return (
    <aside
      aria-label="설정 섹션"
      className="flex flex-col gap-1 rounded-lg border border-line bg-surface p-3"
    >
      {ITEMS.map((item) => {
        const isActive = item.value === active;
        const href = `/settings/${item.value}` as Route;
        return (
          <Link
            key={item.value}
            href={href}
            aria-current={isActive ? 'page' : undefined}
            className={cn(
              'flex items-start gap-2 rounded px-2.5 py-2 transition-colors duration-fast ease-out',
              isActive
                ? 'bg-brand-soft text-brand'
                : 'text-ink-muted hover:bg-gray-1 hover:text-ink',
            )}
          >
            <Icon
              name={item.icon}
              size={14}
              strokeWidth={1.7}
              className="mt-0.5 shrink-0"
            />
            <div className="min-w-0">
              <div
                className={cn(
                  'text-sm font-medium',
                  isActive ? 'text-brand' : 'text-ink',
                )}
              >
                {item.label}
              </div>
              {item.hint && (
                <div className="font-mono text-[10.5px] text-ink-dim">
                  {item.hint}
                </div>
              )}
            </div>
          </Link>
        );
      })}
    </aside>
  );
}
