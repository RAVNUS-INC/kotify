import type { MessageAttachment } from '@/types/chat';

/** 받은 MMS 첨부. 이미지는 말풍선 안에 바로, 그 밖의 형식은 내려받기 링크로 보인다. */
export function MessageAttachmentView({ attachment }: { attachment: MessageAttachment }) {
  if (attachment.status === 'pending') {
    return <span className="block text-sm text-ink-dim">첨부 파일을 받아 오는 중입니다</span>;
  }
  if (attachment.status === 'unavailable') {
    return <span className="block text-sm text-ink-dim">첨부 파일을 받을 수 없습니다(보관 기간 7일 경과 등)</span>;
  }
  if (attachment.isImage) {
    return (
      <a href={attachment.url} target="_blank" rel="noreferrer" className="mb-1 block">
        {/* eslint-disable-next-line @next/next/no-img-element -- 인증 쿠키로 받는 사용자 첨부라 최적화 경유 불가 */}
        <img src={attachment.url} alt="받은 사진" className="max-h-64 max-w-full rounded-lg" loading="lazy" />
      </a>
    );
  }
  return (
    <a href={attachment.url} className="mb-1 block text-sm underline" download>
      첨부 파일 받기
    </a>
  );
}
