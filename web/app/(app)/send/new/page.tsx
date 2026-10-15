import { PageHeader } from '@/components/shell';
import { ComposeForm } from '@/components/send';

export default function SendNew() {
  return (
    <div className="k-page max-w-[1240px]">
      <PageHeader
        title="새 발송"
        sub="받는 사람과 메시지를 정하면 오른쪽에서 미리 보고 바로 보내거나 예약할 수 있습니다."
      />
      <ComposeForm />
    </div>
  );
}
