import { PageHeader } from '@/components/shell';
import { ComposeForm } from '@/components/send';

export default function SendNew() {
  return (
    <div className="k-page">
      <PageHeader
        title="새 발송"
        sub="발신번호 · 수신자 · 메시지 입력 후 즉시 또는 예약으로 전송"
      />
      <ComposeForm />
    </div>
  );
}
