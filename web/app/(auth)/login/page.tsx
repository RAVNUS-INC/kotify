import { Button, Card, CardBody, Icon } from '@/components/ui';

type SearchParams = { from?: string };

/**
 * open redirect 방지: `/`로 시작하되 `//`로 시작하지 않는 내부 경로만 허용.
 * 그 외엔 루트로 폴백.
 */
function safeFrom(raw: string | undefined): string {
  if (typeof raw !== 'string') return '/';
  if (!raw.startsWith('/') || raw.startsWith('//')) return '/';
  return raw;
}

export default function Login({
  searchParams,
}: {
  searchParams?: SearchParams;
}) {
  const from = safeFrom(searchParams?.from);
  const loginHref = `/api/auth/login?from=${encodeURIComponent(from)}`;

  return (
    <Card>
      <CardBody>
        <div className="py-2 text-center">
          <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-lg bg-gray-11 font-mono text-white">
            K
          </div>
          <h1 className="text-2xl font-semibold tracking-tight">Kotify</h1>
          <p className="mt-1 text-sm text-ink-muted">
            조직 계정으로 로그인하세요.
          </p>
        </div>

        <a
          href={loginHref}
          className="mt-6 inline-flex h-10 w-full items-center justify-center gap-2 rounded border border-brand bg-brand px-4 text-sm font-medium text-white transition-colors duration-fast ease-out hover:bg-brand-hover"
        >
          <Icon name="shield" size={14} />
          Keycloak으로 로그인
        </a>

        <div className="mt-4 text-center text-[11px] text-ink-dim">
          로그인 후 <span className="font-mono">{from}</span>으로 돌아갑니다.
        </div>
      </CardBody>
    </Card>
  );
}

// 로그인은 쿠키 상태에 따라 리다이렉트 동작이 달라지므로 매 요청 SSR
export const dynamic = 'force-dynamic';
