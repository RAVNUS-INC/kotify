'use client';

import { useState, type FormEvent } from 'react';
import {
  completeSetup,
  testSetupKeycloak,
  testSetupMsghub,
  verifySetupToken,
  type SetupStatus,
} from '@/lib/setup';
import { Button, Field, Icon, Input } from '@/components/ui';

export type SetupWizardProps = {
  initial: SetupStatus;
};

type StepKind = 'token' | 'config' | 'done';
type TestFlag = { kind: 'ok' | 'err'; text: string } | null;
type DoneInfo = { next: string; restartRecommended: boolean };

/**
 * Fresh install 1-페이지 wizard. 3 파트:
 *   1) Setup token 검증 — CT 콘솔/SSH 에서 `cat ${tokenPath}` 로 읽어서 입력.
 *   2) Keycloak + msghub + App 설정 입력 (인증 테스트 버튼 포함).
 *   3) 완료 → `/auth/login` 으로 이동.
 *
 * 단순 client-side 폼 하나로 구성. 멀티 스텝이지만 한 페이지에 조건부 렌더.
 */
export function SetupWizard({ initial }: SetupWizardProps) {
  const [step, setStep] = useState<StepKind>(
    initial.tokenVerified ? 'config' : 'token',
  );
  const [doneInfo, setDoneInfo] = useState<DoneInfo | null>(null);

  // Token 단계
  const [token, setToken] = useState('');
  const [tokenErr, setTokenErr] = useState<string | null>(null);
  const [verifying, setVerifying] = useState(false);

  // Config 단계
  const [keycloakIssuer, setKeycloakIssuer] = useState('');
  const [keycloakClientId, setKeycloakClientId] = useState('kotify-web');
  const [keycloakClientSecret, setKeycloakClientSecret] = useState('');
  const [msghubApiKey, setMsghubApiKey] = useState('');
  const [msghubApiPwd, setMsghubApiPwd] = useState('');
  const [msghubEnv, setMsghubEnv] = useState('production');
  const [msghubBrandId, setMsghubBrandId] = useState('');
  const [msghubChatbotId, setMsghubChatbotId] = useState('');
  const [appPublicUrl, setAppPublicUrl] = useState('');
  const [firstAdminEmail, setFirstAdminEmail] = useState('');

  const [submitting, setSubmitting] = useState(false);
  const [submitErr, setSubmitErr] = useState<string | null>(null);
  const [kcTest, setKcTest] = useState<TestFlag>(null);
  const [mhTest, setMhTest] = useState<TestFlag>(null);
  const [kcTesting, setKcTesting] = useState(false);
  const [mhTesting, setMhTesting] = useState(false);

  const verifyToken = async (e: FormEvent) => {
    e.preventDefault();
    if (verifying) return;
    setVerifying(true);
    setTokenErr(null);
    try {
      await verifySetupToken(token.trim());
      setStep('config');
    } catch (err) {
      setTokenErr(err instanceof Error ? err.message : '토큰 검증 실패');
    } finally {
      setVerifying(false);
    }
  };

  const runKeycloakTest = async () => {
    if (!keycloakIssuer.trim() || kcTesting) return;
    setKcTesting(true);
    setKcTest(null);
    try {
      const r = await testSetupKeycloak(keycloakIssuer.trim());
      setKcTest({ kind: 'ok', text: `✓ ${r.issuer || '연결 성공'}` });
    } catch (err) {
      setKcTest({
        kind: 'err',
        text: err instanceof Error ? err.message : '테스트 실패',
      });
    } finally {
      setKcTesting(false);
    }
  };

  const runMsghubTest = async () => {
    if (!msghubApiKey || !msghubApiPwd || mhTesting) return;
    setMhTesting(true);
    setMhTest(null);
    try {
      const r = await testSetupMsghub({
        msghubApiKey,
        msghubApiPwd,
        msghubEnv,
      });
      setMhTest({ kind: 'ok', text: `✓ 인증 성공 (env=${r.env})` });
    } catch (err) {
      setMhTest({
        kind: 'err',
        text: err instanceof Error ? err.message : '테스트 실패',
      });
    } finally {
      setMhTesting(false);
    }
  };

  const onComplete = async (e: FormEvent) => {
    e.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setSubmitErr(null);
    try {
      const r = await completeSetup({
        token: token.trim(),
        keycloakIssuer: keycloakIssuer.trim(),
        keycloakClientId: keycloakClientId.trim(),
        keycloakClientSecret,
        msghubApiKey,
        msghubApiPwd,
        msghubEnv,
        msghubBrandId: msghubBrandId.trim(),
        msghubChatbotId: msghubChatbotId.trim(),
        appPublicUrl: appPublicUrl.trim(),
        firstAdminEmail: firstAdminEmail.trim(),
      });
      setDoneInfo({
        next: r.next,
        restartRecommended: Boolean(r.restartRecommended),
      });
      setStep('done');
      // 재시작 권장 시엔 자동 네비게이트 생략 — 사용자가 재시작 후 수동으로
      // 로그인 페이지로 이동. 그렇지 않으면 짧은 딜레이 후 이동.
      if (!r.restartRecommended) {
        setTimeout(() => {
          window.location.href = r.next;
        }, 800);
      }
    } catch (err) {
      setSubmitErr(err instanceof Error ? err.message : '설정 저장 실패');
      setSubmitting(false);
    }
  };

  if (step === 'done') {
    const restart = doneInfo?.restartRecommended ?? false;
    return (
      <div className="mx-auto max-w-2xl rounded-lg border border-line bg-surface p-8 text-center">
        <div className="mb-3 flex justify-center text-ok">
          <Icon name="check" size={40} />
        </div>
        <h1 className="text-xl font-semibold text-ink">초기 설정 완료</h1>
        {restart ? (
          <>
            <p className="mt-3 text-sm text-ink-muted">
              설정이 저장되었습니다. <strong>앱을 재시작한 후 로그인하세요.</strong>
              <br />
              새 session.secret 은 프로세스 재시작 시점에 활성화됩니다.
              재시작 전에 만든 세션은 재시작 후 무효화됩니다.
            </p>
            <div className="mt-4 rounded border border-line bg-gray-1 p-3 text-left font-mono text-[12px] text-ink-muted">
              # 예) systemd 기반 배포:
              <br />$ sudo systemctl restart kotify
            </div>
            <p className="mt-4 text-sm text-ink-muted">
              재시작 후{' '}
              <a
                className="text-brand underline hover:text-brand-hover"
                href={doneInfo?.next ?? '/auth/login'}
              >
                로그인 페이지
              </a>
              로 이동하세요.
            </p>
          </>
        ) : (
          <p className="mt-2 text-sm text-ink-muted">
            로그인 페이지로 이동합니다…
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl">
      <header className="mb-6">
        <h1 className="text-xl font-semibold text-ink">Kotify 초기 설정</h1>
        <p className="mt-1 text-sm text-ink-muted">
          {step === 'token'
            ? 'CT 콘솔/SSH 에서 아래 경로의 setup token 을 확인해 입력하세요.'
            : 'Keycloak + msghub 자격증명을 입력하고 저장합니다.'}
        </p>
      </header>

      {step === 'token' ? (
        <form
          onSubmit={verifyToken}
          className="rounded-lg border border-line bg-surface p-5"
        >
          <div className="mb-4 rounded bg-gray-1 p-3 font-mono text-[12.5px] text-ink-muted">
            $ cat {initial.tokenPath}
          </div>
          <Field label="Setup token" hint="128-bit hex. 완료 후 파일은 자동 삭제.">
            <Input
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="예) a1b2c3...(32 hex chars)"
              autoFocus
              disabled={verifying}
              required
            />
          </Field>
          {tokenErr ? (
            <div className="mt-3 rounded border border-danger/30 bg-danger/5 p-2 text-sm text-danger" role="alert">
              {tokenErr}
            </div>
          ) : null}
          <div className="mt-4 flex justify-end">
            <Button
              type="submit"
              variant="primary"
              size="md"
              loading={verifying}
              icon={<Icon name="check" size={12} />}
            >
              토큰 확인
            </Button>
          </div>
        </form>
      ) : null}

      {step === 'config' ? (
        <form onSubmit={onComplete} className="flex flex-col gap-5">
          <section
            aria-label="Keycloak"
            className="rounded-lg border border-line bg-surface p-5"
          >
            <header className="mb-4">
              <h2 className="text-base font-semibold text-ink">Keycloak (SSO)</h2>
            </header>
            <div className="grid gap-4 md:grid-cols-2">
              <Field label="Issuer URL">
                <Input
                  value={keycloakIssuer}
                  onChange={(e) => setKeycloakIssuer(e.target.value)}
                  placeholder="https://sso.example.com/realms/kotify"
                  disabled={submitting}
                  required
                />
              </Field>
              <Field label="Client ID">
                <Input
                  value={keycloakClientId}
                  onChange={(e) => setKeycloakClientId(e.target.value)}
                  disabled={submitting}
                  required
                />
              </Field>
              <Field label="Client Secret">
                <Input
                  type="password"
                  value={keycloakClientSecret}
                  onChange={(e) => setKeycloakClientSecret(e.target.value)}
                  disabled={submitting}
                  autoComplete="new-password"
                  required
                />
              </Field>
              <div className="flex flex-col justify-end gap-1">
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  onClick={runKeycloakTest}
                  disabled={kcTesting || !keycloakIssuer.trim()}
                  icon={<Icon name="check" size={12} />}
                >
                  {kcTesting ? '테스트 중…' : 'Issuer 테스트'}
                </Button>
                {kcTest ? (
                  <span
                    className={
                      kcTest.kind === 'ok'
                        ? 'text-[12px] text-ok'
                        : 'text-[12px] text-danger'
                    }
                  >
                    {kcTest.text}
                  </span>
                ) : null}
              </div>
            </div>
          </section>

          <section
            aria-label="msghub"
            className="rounded-lg border border-line bg-surface p-5"
          >
            <header className="mb-4">
              <h2 className="text-base font-semibold text-ink">msghub</h2>
            </header>
            <div className="grid gap-4 md:grid-cols-2">
              <Field label="API Key">
                <Input
                  type="password"
                  value={msghubApiKey}
                  onChange={(e) => setMsghubApiKey(e.target.value)}
                  disabled={submitting}
                  autoComplete="new-password"
                  required
                />
              </Field>
              <Field label="API Password">
                <Input
                  type="password"
                  value={msghubApiPwd}
                  onChange={(e) => setMsghubApiPwd(e.target.value)}
                  disabled={submitting}
                  autoComplete="new-password"
                  required
                />
              </Field>
              <Field label="환경" hint="production / staging / sandbox">
                <Input
                  value={msghubEnv}
                  onChange={(e) => setMsghubEnv(e.target.value)}
                  disabled={submitting}
                />
              </Field>
              <div className="flex flex-col justify-end gap-1">
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  onClick={runMsghubTest}
                  disabled={mhTesting || !msghubApiKey || !msghubApiPwd}
                  icon={<Icon name="check" size={12} />}
                >
                  {mhTesting ? '테스트 중…' : '인증 테스트'}
                </Button>
                {mhTest ? (
                  <span
                    className={
                      mhTest.kind === 'ok'
                        ? 'text-[12px] text-ok'
                        : 'text-[12px] text-danger'
                    }
                  >
                    {mhTest.text}
                  </span>
                ) : null}
              </div>
              <Field label="브랜드 ID (선택)">
                <Input
                  value={msghubBrandId}
                  onChange={(e) => setMsghubBrandId(e.target.value)}
                  disabled={submitting}
                />
              </Field>
              <Field label="챗봇 ID (선택)" hint="RCS 양방향 사용 시">
                <Input
                  value={msghubChatbotId}
                  onChange={(e) => setMsghubChatbotId(e.target.value)}
                  disabled={submitting}
                />
              </Field>
            </div>
          </section>

          <section
            aria-label="앱"
            className="rounded-lg border border-line bg-surface p-5"
          >
            <header className="mb-4">
              <h2 className="text-base font-semibold text-ink">앱 / 관리자</h2>
            </header>
            <div className="grid gap-4 md:grid-cols-2">
              <Field
                label="공개 URL"
                hint="예) https://kotify.example.com (뒤 슬래시 자동 제거)"
              >
                <Input
                  value={appPublicUrl}
                  onChange={(e) => setAppPublicUrl(e.target.value)}
                  placeholder="https://kotify.example.com"
                  disabled={submitting}
                />
              </Field>
              <Field
                label="첫 관리자 이메일"
                hint="이 이메일로 Keycloak 로그인 시 admin 자동 승격."
              >
                <Input
                  type="email"
                  value={firstAdminEmail}
                  onChange={(e) => setFirstAdminEmail(e.target.value)}
                  placeholder="admin@example.com"
                  disabled={submitting}
                />
              </Field>
            </div>
          </section>

          {submitErr ? (
            <div className="rounded border border-danger/30 bg-danger/5 p-3 text-sm text-danger" role="alert">
              {submitErr}
            </div>
          ) : null}

          <div className="flex items-center justify-end">
            <Button
              type="submit"
              variant="primary"
              size="md"
              loading={submitting}
              icon={<Icon name="check" size={12} />}
            >
              설정 저장 및 완료
            </Button>
          </div>
        </form>
      ) : null}
    </div>
  );
}
