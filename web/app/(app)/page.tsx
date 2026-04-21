import { Placeholder } from '@/components/shell';

export default function Home() {
  return (
    <Placeholder
      title="안녕하세요 👋"
      sub="오늘 발송 현황과 미답 대화가 여기에 표시됩니다."
      phase="Phase 5 · S1 Dashboard"
      icon="home"
    >
      Timeline ribbon + 미답 대화 인박스 + KPI 스택(RCS 도달률, 오늘 발송,
      예약, 비용)이 구현될 예정입니다. Kitchen sink가 필요하면{' '}
      <a href="/kitchen" className="text-brand underline underline-offset-2">
        /kitchen
      </a>
      으로 이동하세요.
    </Placeholder>
  );
}
