import { Badge, Icon } from '@/components/ui';

export function SecuritySection() {
  return (
    <div className="flex flex-col gap-4">
      <Card
        icon="key"
        title="Keycloak OIDC"
        description="조직 전체 SSO. 계정 관리·비밀번호 재설정은 Keycloak 콘솔에서."
        badge={<Badge kind="success" dot>연결됨</Badge>}
      />
      <Card
        icon="clock"
        title="세션 정책"
        description="기본 8시간 만료 · HttpOnly · SameSite=Lax · production에서 Secure."
      />
      <Card
        icon="shield"
        title="2단계 인증 (2FA)"
        description="Keycloak의 Required Actions로 강제. 설정은 IdP 콘솔."
        badge={<Badge kind="neutral">IdP 위임</Badge>}
      />
      <Card
        icon="alert"
        title="위험 영역"
        description="조직 삭제·데이터 내보내기는 owner만 실행 가능. 현재 UI 미제공."
        badge={<Badge kind="danger">owner only</Badge>}
      />
    </div>
  );
}

type CardProps = {
  icon: 'key' | 'clock' | 'shield' | 'alert';
  title: string;
  description: string;
  badge?: React.ReactNode;
};

function Card({ icon, title, description, badge }: CardProps) {
  return (
    <div className="flex items-start gap-3 rounded-lg border border-line bg-surface p-4">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gray-1 text-ink-muted">
        <Icon name={icon} size={14} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-ink">{title}</span>
          {badge}
        </div>
        <p className="mt-0.5 text-[12.5px] text-ink-muted">{description}</p>
      </div>
    </div>
  );
}
