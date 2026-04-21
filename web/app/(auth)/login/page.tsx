import { Card, CardBody } from '@/components/ui';

export default function Login() {
  return (
    <Card>
      <CardBody>
        <div className="text-center">
          <div className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-brand">
            Phase 4b · S14 Login
          </div>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight">Kotify</h1>
          <p className="mt-2 text-sm text-ink-muted">
            Keycloak OIDC 로그인은 Phase 4b에서 연결됩니다.
          </p>
        </div>
      </CardBody>
    </Card>
  );
}
