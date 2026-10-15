import { Badge, EmptyState } from '@/components/ui';
import { formatPhone } from '@/lib/phone';
import { FAX_STATUS_KIND, FAX_STATUS_LABEL, fmtKstDateTime } from '@/lib/pbx-format';
import type { FaxJob } from '@/types/pbx';
import { FaxResendButton } from './FaxResendButton';

export type FaxJobsTableProps = {
  jobs: ReadonlyArray<FaxJob>;
  /** 관리자는 전체 이력을 보므로 보낸 사람 열을 보여 준다. */
  showCreator?: boolean;
};

export function FaxJobsTable({ jobs, showCreator = false }: FaxJobsTableProps) {
  if (jobs.length === 0) {
    return (
      <div className="rounded-lg border border-line bg-surface">
        <EmptyState icon="file" title="보낸 팩스 없음" description="위에서 PDF 를 골라 팩스를 보내세요." size="md" />
      </div>
    );
  }
  return (
    <div className="overflow-hidden rounded-lg border border-line bg-surface">
      <div className="overflow-x-auto">
        <table className="k-tbl">
          <thead>
            <tr>
              <th>보낸 시각</th>
              <th>받는 번호</th>
              <th>파일</th>
              <th>상태</th>
              {showCreator ? <th>보낸 사람</th> : null}
              <th className="text-right">작업</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((job) => (
              <tr key={job.id}>
                <td className="mono">{fmtKstDateTime(job.createdAt)}</td>
                <td className="mono text-ink">{formatPhone(job.recipient)}</td>
                <td className="max-w-[240px] truncate">
                  <a
                    href={`/api/fax/${job.id}/pdf`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-ink hover:underline"
                  >
                    {job.filename}
                  </a>
                </td>
                <td>
                  <div className="flex flex-col items-start gap-0.5">
                    <Badge kind={FAX_STATUS_KIND[job.status]} dot>
                      {FAX_STATUS_LABEL[job.status]}
                    </Badge>
                    {job.error ? (
                      <span className="text-[12px] text-ink-muted">{job.error}</span>
                    ) : null}
                  </div>
                </td>
                {showCreator ? <td className="truncate">{job.createdBy ?? '-'}</td> : null}
                <td className="text-right">
                  {job.status === 'FAILED' || job.status === 'UNKNOWN' ? (
                    <FaxResendButton job={job} />
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
