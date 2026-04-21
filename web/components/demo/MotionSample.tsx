'use client';

import { useState } from 'react';
import {
  AnimatedBars,
  Counter,
  Progress,
  PulseDot,
  Rise,
  Skeleton,
  SkeletonText,
  Sparkline,
  Spinner,
  Stagger,
} from '@/components/motion';
import { Badge, Button, Card, CardBody, CardHeader, EmptyState, Icon } from '@/components/ui';

export function MotionSample() {
  const [n, setN] = useState(0);

  return (
    <div className="grid gap-6">
      <div className="grid grid-cols-4 gap-3">
        <Kpi label="오늘 발송" value={1248} delay={100} />
        <Kpi label="예약" value={42} delay={180} />
        <Kpi
          label="도달률"
          value={72.4}
          delay={260}
          format={(v) => `${v.toFixed(1)}%`}
        />
        <Kpi
          label="오늘 비용"
          value={83500}
          delay={340}
          format={(v) => `₩${v.toLocaleString('ko-KR')}`}
        />
      </div>

      <Card>
        <CardHeader
          eyebrow="일별 발송량"
          title="최근 7일"
          actions={
            <Button
              size="sm"
              variant="ghost"
              icon={<Icon name="refresh" size={12} />}
              onClick={() => setN((k) => k + 1)}
            >
              재생
            </Button>
          }
        />
        <CardBody>
          <AnimatedBars
            key={n}
            data={[18, 32, 24, 49, 36, 58, 71]}
            labels={['월', '화', '수', '목', '금', '토', '일']}
            height={120}
          />
        </CardBody>
      </Card>

      <div className="grid grid-cols-2 gap-3">
        <Card>
          <CardHeader eyebrow="스파크라인" title="RCS 도달률 추세" />
          <CardBody>
            <div className="flex items-baseline gap-3">
              <div className="font-mono text-2xl font-semibold tracking-tight tabular-nums">
                72.4%
              </div>
              <Sparkline
                data={[62, 64, 61, 66, 68, 70, 72]}
                width={140}
                height={36}
              />
            </div>
          </CardBody>
        </Card>

        <Card>
          <CardHeader eyebrow="진행도" title="발송 중" />
          <CardBody>
            <div className="flex items-center gap-2 text-sm">
              <PulseDot size={8} />
              <span>전송 중 · 348/1000</span>
            </div>
            <div className="mt-3 space-y-2">
              <Progress value={348} max={1000} duration={1200} ariaLabel="발송 진행도" />
              <Progress
                value={2.7}
                max={100}
                color="var(--warning)"
                duration={900}
                delay={200}
                ariaLabel="SMS fallback 비율"
              />
            </div>
            <div className="mt-2 flex justify-between font-mono text-[11px] text-ink-dim">
              <span>RCS 97.3%</span>
              <span>SMS fallback 2.7%</span>
            </div>
          </CardBody>
        </Card>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Card>
          <CardHeader eyebrow="Stagger entrance" title="알림 피드" />
          <CardBody>
            <div className="flex flex-col gap-1.5 text-sm">
              <Stagger step={60}>
                <FeedRow kind="success" text="신규 캠페인 '4월 공지' 발송 완료" />
                <FeedRow kind="info" text="API 키가 갱신되었습니다" />
                <FeedRow kind="warning" text="발신번호 010-1234 승인 대기" />
                <FeedRow kind="danger" text="webhook 전달 실패 (3회)" />
              </Stagger>
            </div>
          </CardBody>
        </Card>

        <Card>
          <CardHeader eyebrow="Skeleton" title="로딩 상태" />
          <CardBody>
            <div className="flex items-center gap-2">
              <Spinner size={14} />
              <span className="text-sm text-ink-muted">데이터 가져오는 중</span>
            </div>
            <div className="mt-4 space-y-2">
              <Skeleton height={18} width="60%" />
              <SkeletonText lines={3} />
            </div>
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader eyebrow="Empty state" title="메시지 없음" />
        <CardBody padded={false}>
          <EmptyState
            icon="inbox"
            title="아직 메시지가 없습니다"
            description="첫 캠페인을 발송하면 이곳에 수신자 반응이 쌓입니다."
            action={<Button variant="primary" icon={<Icon name="send" />}>새 발송</Button>}
          />
        </CardBody>
      </Card>

      <Rise delay={200}>
        <div className="text-center font-mono text-[10.5px] text-ink-dim">
          Rise 단일 연출 · reduced-motion 환경에서는 즉시 표시
        </div>
      </Rise>
    </div>
  );
}

function Kpi({
  label,
  value,
  delay,
  format,
}: {
  label: string;
  value: number;
  delay: number;
  format?: (n: number) => string;
}) {
  return (
    <Card>
      <CardBody>
        <div className="font-mono text-[10.5px] uppercase tracking-[0.06em] text-ink-dim">
          {label}
        </div>
        <div className="mt-1.5 text-[28px] font-semibold leading-none tracking-[-0.03em]">
          <Counter value={value} delay={delay} format={format} />
        </div>
      </CardBody>
    </Card>
  );
}

function FeedRow({
  kind,
  text,
}: {
  kind: 'success' | 'info' | 'warning' | 'danger';
  text: string;
}) {
  const icon = kind === 'success'
    ? 'check'
    : kind === 'warning'
      ? 'alert'
      : kind === 'danger'
        ? 'error'
        : 'info';
  return (
    <div className="flex items-center gap-2">
      <Badge kind={kind} icon={<Icon name={icon} size={10} />}>
        {kind}
      </Badge>
      <span className="truncate">{text}</span>
    </div>
  );
}
