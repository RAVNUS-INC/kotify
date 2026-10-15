import { describe, expect, it, vi } from 'vitest';

// Topbar 모듈은 검색 팔레트 등 클라이언트 컴포넌트를 함께 불러오므로 경로 계산만 쓰는 이 테스트에선 가볍게 막는다.
vi.mock('next/navigation', () => ({ usePathname: () => '/' }));
vi.mock('@/components/search', () => ({ CommandPalette: () => null }));

import { buildCrumbs } from './Topbar';

const labels = (path: string) => buildCrumbs(path).map((c) => c.label);

describe('buildCrumbs', () => {
  it('대화방 상세의 내부 키(caller:phone)를 경로에 노출하지 않는다', () => {
    expect(labels('/chat/0215880000%3A01055500037')).toEqual(['홈', '대화방', '대화']);
  });

  it('캠페인·그룹 상세는 id 대신 상세 이름을 쓴다', () => {
    expect(labels('/campaigns/42')).toEqual(['홈', '발송 이력', '캠페인 상세']);
    expect(labels('/groups/7')).toEqual(['홈', '그룹', '그룹 상세']);
  });

  it('설정 탭 슬러그를 한국어 탭 이름으로 바꾼다', () => {
    expect(labels('/settings/org')).toEqual(['홈', '설정', '조직']);
    expect(labels('/settings/developers')).toEqual(['홈', '설정', '개발자']);
  });

  it('페이지가 없는 /send 구간은 링크로 만들지 않는다', () => {
    const crumbs = buildCrumbs('/send/new');
    expect(crumbs.map((c) => [c.label, c.linkable])).toEqual([
      ['홈', true],
      ['발송', false],
      ['새 발송', true],
    ]);
  });

  it('모르는 구간은 디코딩해서 그대로 보여준다', () => {
    expect(labels('/%ED%85%8C%EC%8A%A4%ED%8A%B8')).toEqual(['홈', '테스트']);
  });
});
