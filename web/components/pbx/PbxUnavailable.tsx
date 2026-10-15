import { EmptyState } from '@/components/ui';
import { ApiError } from '@/lib/api';

/** PBX 미설정·장애 안내. 그 밖의 오류는 다시 던져 error.tsx 가 처리한다. */
export function pbxErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === 'pbx_not_configured') {
      return '전화 교환기(PBX) 연동이 설정되지 않았습니다. 관리자가 설정 → 메시징에서 PBX 정보를 입력해야 합니다.';
    }
    if (err.code === 'pbx_error') return `전화 교환기에 연결하지 못했습니다. 잠시 후 다시 시도하세요. (${err.message})`;
    return err.message;
  }
  throw err;
}

export function PbxUnavailable({ message }: { message: string }) {
  return (
    <div className="rounded-lg border border-line bg-surface">
      <EmptyState icon="alertTri" title="통화 기록을 불러오지 못했습니다" description={message} size="md" />
    </div>
  );
}
