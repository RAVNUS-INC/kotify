import { MessageBubble } from '@/components/chat';
import { DeviceMockup } from '@/components/send';
import type { CampaignDetail } from '@/types/campaign';

export type CampaignMessagePreviewProps = {
  campaign: CampaignDetail;
  /** mock: 캠페인 본문이 상세 응답에 없으므로 placeholder 텍스트 */
  sampleText?: string;
};

const CHANNEL_KIND_MAP: Record<string, 'rcs' | 'sms' | 'kakao'> = {
  rcs: 'rcs',
  sms: 'sms',
  lms: 'sms',
  mms: 'sms',
  kakao: 'kakao',
};

export function CampaignMessagePreview({
  campaign,
  sampleText,
}: CampaignMessagePreviewProps) {
  const kind = CHANNEL_KIND_MAP[campaign.channel] ?? 'sms';
  const bodyText =
    sampleText ??
    `안녕하세요, ${campaign.name} 안내드립니다.\n자세한 내용은 링크를 확인해주세요.`;

  return (
    <div className="rounded-lg border border-line bg-surface p-4">
      <div className="mb-1 font-mono text-[10.5px] font-medium uppercase tracking-[0.06em] text-ink-dim">
        원본 프리뷰 · {kind.toUpperCase()}
      </div>
      <div className="mb-3 text-[11px] text-ink-muted">
        발신: <span className="font-mono text-ink">{campaign.sender}</span>
      </div>
      <DeviceMockup frame="ios" width={220} senderName="Kotify" timeLabel={campaign.createdAt.split(' ')[1] ?? '지금'}>
        <MessageBubble kind={kind} side="them">
          {bodyText}
        </MessageBubble>
      </DeviceMockup>
    </div>
  );
}
