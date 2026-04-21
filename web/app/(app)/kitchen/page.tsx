import { FormsSample } from '@/components/demo/FormsSample';
import { MotionSample } from '@/components/demo/MotionSample';
import { MessageBubble } from '@/components/chat';
import { DeviceMockup } from '@/components/send';
import { PageHeader } from '@/components/shell';
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardFooter,
  CardHeader,
  Icon,
  Kbd,
  Pill,
} from '@/components/ui';

export default function Kitchen() {
  return (
    <div className="k-page">
      <PageHeader
        title="Kitchen Sink"
        sub="UI 프리미티브 · 폼 · 모션 검증용. 프로덕션 라우트 아님."
      />

      <Section title="Buttons">
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="primary" icon={<Icon name="send" />}>발송</Button>
          <Button variant="secondary">취소</Button>
          <Button variant="ghost" icon={<Icon name="download" />}>내보내기</Button>
          <Button variant="danger" icon={<Icon name="trash" />}>삭제</Button>
          <Button variant="primary" loading>저장 중</Button>
          <Button variant="secondary" disabled>비활성</Button>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button size="sm">sm</Button>
          <Button size="md">md</Button>
          <Button size="lg" iconRight={<Icon name="arrowRight" />}>lg</Button>
        </div>
      </Section>

      <Section title="Badges & Pills">
        <div className="flex flex-wrap items-center gap-2">
          <Badge kind="neutral">neutral</Badge>
          <Badge kind="success" dot>도달</Badge>
          <Badge kind="warning" dot>대기</Badge>
          <Badge kind="danger" dot>실패</Badge>
          <Badge kind="info" icon={<Icon name="info" size={10} />}>안내</Badge>
          <Badge kind="brand">RCS</Badge>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Pill tone="neutral">v0.3.0</Pill>
          <Pill tone="brand">NEW</Pill>
          <Pill tone="success">LIVE</Pill>
          <Pill tone="warning">BETA</Pill>
          <Pill tone="danger">DOWN</Pill>
        </div>
      </Section>

      <Section title="Kbd">
        <div className="flex flex-wrap items-center gap-2 text-ink-muted">
          <span>검색:</span>
          <Kbd>⌘</Kbd>
          <Kbd>K</Kbd>
          <span className="ml-4">취소:</span>
          <Kbd>Esc</Kbd>
        </div>
      </Section>

      <Section title="Icon sample">
        <div className="flex flex-wrap items-center gap-4 text-ink">
          {['home', 'send', 'inbox', 'users', 'bell', 'search', 'settings', 'chart', 'shield', 'zap'].map((n) => (
            <div key={n} className="flex flex-col items-center gap-1">
              <Icon name={n as 'home'} size={20} strokeWidth={1.6} />
              <span className="font-mono text-[10.5px] text-ink-dim">{n}</span>
            </div>
          ))}
        </div>
      </Section>

      <Section title="Forms (client)">
        <FormsSample />
      </Section>

      <Section title="Motion (client)">
        <MotionSample />
      </Section>

      <Section title="Device preview · Message bubbles">
        <div className="flex flex-wrap items-start gap-8">
          <DeviceMockup frame="ios" senderName="Kotify" timeLabel="14:02">
            <MessageBubble kind="rcs" side="them" timestamp="14:02">
              안녕하세요 박지훈 님,{'\n'}내일 배송 예정입니다.
            </MessageBubble>
            <MessageBubble kind="rcs" side="us" timestamp="14:03">
              네 확인했습니다.
            </MessageBubble>
            <MessageBubble kind="sms" side="them" timestamp="14:05">
              배송 일정 변경 안내입니다.
            </MessageBubble>
          </DeviceMockup>

          <DeviceMockup frame="android" senderName="Kotify" timeLabel="지금">
            <MessageBubble kind="kakao" side="them" timestamp="11:20">
              카카오톡 테스트 메시지
            </MessageBubble>
            <MessageBubble kind="kakao" side="us" timestamp="11:21">
              알겠습니다.
            </MessageBubble>
          </DeviceMockup>
        </div>
      </Section>

      <Section title="Card">
        <Card>
          <CardHeader
            eyebrow="오늘의 발송"
            title="RCS 도달률"
            subtitle="조직 전체 기준, 최근 24시간"
            actions={<Button variant="ghost" size="sm">더보기</Button>}
          />
          <CardBody>
            <div className="flex items-baseline gap-3">
              <div className="font-mono text-3xl font-semibold tracking-[-0.03em] tabular-nums">
                72.4%
              </div>
              <Badge kind="success" dot>+2.1p</Badge>
            </div>
            <p className="mt-2 text-md text-ink-muted">
              이전 주 대비 도달률이 상승했습니다. SMS fallback은 2.7%로 정상 범위.
            </p>
          </CardBody>
          <CardFooter align="between">
            <span className="font-mono text-xs text-ink-dim">업데이트 14:02</span>
            <Button variant="secondary" size="sm" iconRight={<Icon name="external" />}>
              리포트로
            </Button>
          </CardFooter>
        </Card>
      </Section>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-10">
      <h2 className="mb-3 text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-dim">
        {title}
      </h2>
      {children}
    </section>
  );
}
