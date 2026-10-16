'use client';

import { useState } from 'react';
import type { MessageAttachment as Attachment } from '@/types/chat';

export type MessageAttachmentProps = {
  attachment: Attachment;
};

// 사진이 아닌 상태는 말풍선 안의 회색 한 줄 — 본문과 구분되게 작고 흐린 글자.
const NOTE = 'block text-sm text-ink-muted';

/**
 * 고객이 보낸 파일. 사진은 서버가 보관한 원본(`/api/chat/media/{moId}`)을 그대로 보여 주고,
 * 누르면 새 탭에서 원본 크기로 연다. 사진이 아닌 MMS 첨부는 내려받기 링크만 준다.
 * 통신사·msghub 주소는 브라우저에 오지 않는다.
 */
export function MessageAttachment({ attachment }: MessageAttachmentProps) {
  // 로그인 만료 등으로 원본 요청이 실패해도 깨진 그림 대신 문구를 보인다.
  const [broken, setBroken] = useState(false);
  const noun = attachment.kind === 'file' ? '첨부 파일을' : '사진을';

  if (attachment.status === 'pending') {
    return <span className={NOTE}>{noun} 불러오는 중입니다</span>;
  }
  if (attachment.status === 'unsupported') {
    return <span className={NOTE}>사진이 아닌 첨부 파일은 볼 수 없습니다</span>;
  }
  if (attachment.status === 'failed' || !attachment.url || broken) {
    return <span className={NOTE}>{noun} 불러올 수 없습니다</span>;
  }
  if (attachment.kind === 'file') {
    return (
      <a href={attachment.url} download className="block text-sm underline">
        첨부 파일 내려받기
      </a>
    );
  }
  return (
    <a
      href={attachment.url}
      target="_blank"
      rel="noopener noreferrer"
      className="block rounded-lg"
      aria-label="고객이 보낸 사진 원본 보기 (새 탭)"
    >
      {/* eslint-disable-next-line @next/next/no-img-element -- 인증 쿠키로 받는 원본이라 next/image 최적화 경로를 쓰지 않는다 */}
      <img
        src={attachment.url}
        alt="고객이 보낸 사진"
        loading="lazy"
        onError={() => setBroken(true)}
        className="block max-h-72 w-auto max-w-full rounded-lg"
      />
    </a>
  );
}
