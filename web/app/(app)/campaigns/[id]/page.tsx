import { Placeholder } from '@/components/shell';

type PageProps = {
  params: { id: string };
};

export default function CampaignDetail({ params }: PageProps) {
  const id = decodeURIComponent(params.id);
  return (
    <Placeholder
      title={`캠페인 ${id}`}
      sub="4-KPI · 수신자 테이블 · 원본 프리뷰 · fallback 흐름"
      phase="Phase 7b · S4 Campaign Detail"
      icon="zap"
    />
  );
}
