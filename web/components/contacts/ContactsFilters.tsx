import { ListSearchInput } from '@/components/ui';

export function ContactsFilters() {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <div className="w-full max-w-xs">
        <ListSearchInput placeholder="이름·번호·이메일 검색" />
      </div>
      {/* 팀·태그 필터는 Phase 후속에 실제 데이터 연결 시 */}
    </div>
  );
}
