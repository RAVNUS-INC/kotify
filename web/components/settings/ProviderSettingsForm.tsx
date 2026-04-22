'use client';

import { useState, type FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import {
  patchProviderClient,
  testMsghubClient,
  type ProviderPatchInput,
  type ProviderSettings,
} from '@/lib/settings';
import { Button, Check, Field, Icon, Input } from '@/components/ui';

export type ProviderSettingsFormProps = {
  initial: ProviderSettings;
  /** 어떤 섹션을 보여줄지 — 설정 탭별로 관련 필드만 노출. */
  section: 'messaging' | 'security';
};

/**
 * msghub(messaging 탭) / Keycloak+app+session(security 탭) 설정 편집.
 *
 * 디자인 원칙:
 * - 시크릿은 항상 빈 칸으로 시작. 기존 값이 있으면 hint 로 마스킹만 표시.
 * - "변경 없음 = 기존 값 보존". 저장 시 빈 시크릿은 서버에 보내지 않음.
 * - 공개 필드는 현재 값으로 pre-fill.
 */
export function ProviderSettingsForm({
  initial,
  section,
}: ProviderSettingsFormProps) {
  const router = useRouter();

  // 공개 필드 state (모든 섹션 공용 state 하나 — section 이 어느 필드를 렌더할지만 결정)
  const [keycloakIssuer, setKeycloakIssuer] = useState(initial.public.keycloakIssuer);
  const [keycloakClientId, setKeycloakClientId] = useState(initial.public.keycloakClientId);
  const [appPublicUrl, setAppPublicUrl] = useState(initial.public.appPublicUrl);
  const [msghubEnv, setMsghubEnv] = useState(initial.public.msghubEnv || 'production');
  const [msghubBrandId, setMsghubBrandId] = useState(initial.public.msghubBrandId);
  const [msghubChatbotId, setMsghubChatbotId] = useState(initial.public.msghubChatbotId);

  // 시크릿 state — 항상 빈 문자열 시작.
  const [keycloakClientSecret, setKeycloakClientSecret] = useState('');
  const [msghubApiKey, setMsghubApiKey] = useState('');
  const [msghubApiPwd, setMsghubApiPwd] = useState('');
  const [sessionSecret, setSessionSecret] = useState('');
  const [msghubWebhookToken, setMsghubWebhookToken] = useState('');

  const [submitting, setSubmitting] = useState(false);
  const [testing, setTesting] = useState(false);
  const [msg, setMsg] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setMsg(null);

    // 공개 필드는 섹션에 속한 것만 보낸다 (다른 섹션 필드 덮어쓰기 방지).
    const payload: ProviderPatchInput = {};
    if (section === 'messaging') {
      if (msghubEnv.trim()) payload.msghubEnv = msghubEnv.trim();
      if (msghubBrandId.trim()) payload.msghubBrandId = msghubBrandId.trim();
      if (msghubChatbotId.trim()) payload.msghubChatbotId = msghubChatbotId.trim();
      if (msghubApiKey) payload.msghubApiKey = msghubApiKey;
      if (msghubApiPwd) payload.msghubApiPwd = msghubApiPwd;
      if (msghubWebhookToken) payload.msghubWebhookToken = msghubWebhookToken;
    } else {
      if (keycloakIssuer.trim()) payload.keycloakIssuer = keycloakIssuer.trim();
      if (keycloakClientId.trim()) payload.keycloakClientId = keycloakClientId.trim();
      if (appPublicUrl.trim()) payload.appPublicUrl = appPublicUrl.trim();
      if (keycloakClientSecret) payload.keycloakClientSecret = keycloakClientSecret;
      if (sessionSecret) payload.sessionSecret = sessionSecret;
    }

    try {
      await patchProviderClient(payload);
      // 저장 후 시크릿 필드 클리어 (hint 에 마스킹 표시로 대체됨).
      setKeycloakClientSecret('');
      setMsghubApiKey('');
      setMsghubApiPwd('');
      setSessionSecret('');
      setMsghubWebhookToken('');
      setMsg({ kind: 'ok', text: '저장됨' });
      router.refresh();
    } catch (err) {
      setMsg({
        kind: 'err',
        text: err instanceof Error ? err.message : '저장 실패',
      });
    } finally {
      setSubmitting(false);
    }
  };

  const onTestMsghub = async () => {
    if (testing) return;
    setTesting(true);
    setMsg(null);
    try {
      const r = await testMsghubClient();
      setMsg({ kind: 'ok', text: `✓ ${r.message} (env=${r.env})` });
    } catch (err) {
      setMsg({
        kind: 'err',
        text: err instanceof Error ? err.message : '테스트 실패',
      });
    } finally {
      setTesting(false);
    }
  };

  const secretHint = (info: { configured: boolean; masked: string }) =>
    info.configured
      ? `설정됨 · ${info.masked} (빈 칸으로 두면 변경 없음)`
      : '미설정';

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-5">
      {section === 'messaging' ? (
        <section
          aria-label="msghub 설정"
          className="rounded-lg border border-line bg-surface p-5"
        >
          <header className="mb-4">
            <h2 className="text-base font-semibold text-ink">msghub 인증</h2>
            <p className="mt-0.5 text-[12.5px] text-ink-muted">
              U+ msghub API 호출에 사용하는 자격증명. 비어 있으면 발송 불가.
            </p>
          </header>

          <div className="grid gap-4 md:grid-cols-2">
            <Field label="환경" hint="production · staging · sandbox">
              <Input
                value={msghubEnv}
                onChange={(e) => setMsghubEnv(e.target.value)}
                placeholder="production"
                disabled={submitting}
              />
            </Field>
            <Field label="브랜드 ID">
              <Input
                value={msghubBrandId}
                onChange={(e) => setMsghubBrandId(e.target.value)}
                placeholder="예) BRAND_0123"
                disabled={submitting}
              />
            </Field>
            <Field label="챗봇 ID" hint="RCS 양방향 전용 번호">
              <Input
                value={msghubChatbotId}
                onChange={(e) => setMsghubChatbotId(e.target.value)}
                placeholder="예) CHATBOT_0123"
                disabled={submitting}
              />
            </Field>
            <div />
            <Field label="API Key" hint={secretHint(initial.secrets.msghubApiKey)}>
              <Input
                type="password"
                value={msghubApiKey}
                onChange={(e) => setMsghubApiKey(e.target.value)}
                placeholder={initial.secrets.msghubApiKey.configured ? '변경 시에만 입력' : '미설정'}
                autoComplete="new-password"
                disabled={submitting}
              />
            </Field>
            <Field label="API Password" hint={secretHint(initial.secrets.msghubApiPwd)}>
              <Input
                type="password"
                value={msghubApiPwd}
                onChange={(e) => setMsghubApiPwd(e.target.value)}
                placeholder={initial.secrets.msghubApiPwd.configured ? '변경 시에만 입력' : '미설정'}
                autoComplete="new-password"
                disabled={submitting}
              />
            </Field>
            <Field
              label="웹훅 토큰"
              hint={`${secretHint(initial.secrets.msghubWebhookToken)} · msghub 콘솔 수신 URL 의 경로에 포함됩니다. 변경 시 콘솔 URL 도 반드시 재등록.`}
            >
              <div className="flex items-stretch gap-2">
                <Input
                  type="text"
                  value={msghubWebhookToken}
                  onChange={(e) => setMsghubWebhookToken(e.target.value)}
                  placeholder={
                    initial.secrets.msghubWebhookToken.configured
                      ? '변경 시에만 입력'
                      : '랜덤 토큰을 생성하거나 직접 입력'
                  }
                  autoComplete="new-password"
                  disabled={submitting}
                  className="flex-1"
                />
                <Button
                  type="button"
                  variant="secondary"
                  size="md"
                  onClick={() => {
                    // 32-hex 랜덤 — crypto.getRandomValues 면 충분한 엔트로피.
                    const arr = new Uint8Array(16);
                    crypto.getRandomValues(arr);
                    const hex = Array.from(arr)
                      .map((b) => b.toString(16).padStart(2, '0'))
                      .join('');
                    setMsghubWebhookToken(hex);
                  }}
                  disabled={submitting}
                  icon={<Icon name="refresh" size={12} />}
                >
                  생성
                </Button>
              </div>
            </Field>
            <div className="md:col-span-2 rounded border border-line bg-gray-1 p-3 text-[12px] text-ink-muted">
              저장 후{' '}
              <a
                href="/settings/developers"
                className="text-brand underline hover:text-brand-hover"
              >
                설정 → 개발자
              </a>{' '}
              탭에서 생성된 웹훅 URL 을 복사해 msghub 콘솔의 리포트/MO
              수신 URL 에 등록하세요.
            </div>
          </div>
        </section>
      ) : null}

      {section === 'security' ? (
        <>
          <section
            aria-label="Keycloak 설정"
            className="rounded-lg border border-line bg-surface p-5"
          >
            <header className="mb-4">
              <h2 className="text-base font-semibold text-ink">Keycloak (SSO)</h2>
              <p className="mt-0.5 text-[12.5px] text-ink-muted">
                OIDC Authorization Code Flow. issuer 와 client_id 는 Keycloak 의
                Realm/Client 설정과 일치해야 한다.
              </p>
            </header>
            <div className="grid gap-4 md:grid-cols-2">
              <Field
                label="Issuer URL"
                hint="예) https://sso.example.com/realms/kotify"
              >
                <Input
                  value={keycloakIssuer}
                  onChange={(e) => setKeycloakIssuer(e.target.value)}
                  disabled={submitting}
                />
              </Field>
              <Field label="Client ID">
                <Input
                  value={keycloakClientId}
                  onChange={(e) => setKeycloakClientId(e.target.value)}
                  placeholder="kotify-web"
                  disabled={submitting}
                />
              </Field>
              <Field
                label="Client Secret"
                hint={secretHint(initial.secrets.keycloakClientSecret)}
              >
                <Input
                  type="password"
                  value={keycloakClientSecret}
                  onChange={(e) => setKeycloakClientSecret(e.target.value)}
                  placeholder={
                    initial.secrets.keycloakClientSecret.configured
                      ? '변경 시에만 입력'
                      : '미설정'
                  }
                  autoComplete="new-password"
                  disabled={submitting}
                />
              </Field>
            </div>
          </section>

          <section
            aria-label="앱/세션 설정"
            className="rounded-lg border border-line bg-surface p-5"
          >
            <header className="mb-4">
              <h2 className="text-base font-semibold text-ink">앱 / 세션</h2>
              <p className="mt-0.5 text-[12.5px] text-ink-muted">
                외부 접근 URL 과 세션 서명 키. URL 은 Keycloak redirect_uri
                생성 + 로그아웃 post_logout 에 사용.
              </p>
            </header>
            <div className="grid gap-4 md:grid-cols-2">
              <Field
                label="공개 URL"
                hint="예) https://kotify.example.com (뒤 슬래시 없이)"
              >
                <Input
                  value={appPublicUrl}
                  onChange={(e) => setAppPublicUrl(e.target.value)}
                  disabled={submitting}
                />
              </Field>
              <Field
                label="세션 시크릿"
                hint={secretHint(initial.secrets.sessionSecret)}
              >
                <Input
                  type="password"
                  value={sessionSecret}
                  onChange={(e) => setSessionSecret(e.target.value)}
                  placeholder={
                    initial.secrets.sessionSecret.configured
                      ? '변경 시에만 입력 (기존 세션 무효화됨)'
                      : '미설정'
                  }
                  autoComplete="new-password"
                  disabled={submitting}
                />
              </Field>
            </div>
          </section>
        </>
      ) : null}

      <div className="flex items-center justify-between gap-3">
        <div
          role="status"
          aria-live="polite"
          className={
            msg
              ? msg.kind === 'ok'
                ? 'text-sm text-ok'
                : 'text-sm text-danger'
              : 'text-sm text-ink-dim'
          }
        >
          {msg?.text ?? ''}
        </div>
        <div className="flex items-center gap-2">
          {section === 'messaging' ? (
            <Button
              type="button"
              variant="secondary"
              size="md"
              onClick={onTestMsghub}
              disabled={submitting || testing}
              icon={<Icon name="check" size={12} />}
            >
              {testing ? '테스트 중…' : '인증 테스트'}
            </Button>
          ) : null}
          <Button
            type="submit"
            variant="primary"
            size="md"
            loading={submitting}
            icon={<Icon name="check" size={12} />}
          >
            저장
          </Button>
        </div>
      </div>
    </form>
  );
}
