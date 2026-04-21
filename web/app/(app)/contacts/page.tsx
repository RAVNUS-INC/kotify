import { PageHeader } from '@/components/shell';
import {
  ContactDrawer,
  ContactsFilters,
  ContactsTable,
} from '@/components/contacts';
import { Button, Icon } from '@/components/ui';
import { fetchContact, fetchContacts } from '@/lib/contacts';
import { ApiError } from '@/lib/api';

type PageProps = {
  searchParams?: {
    q?: string;
    selected?: string;
  };
};

export default async function ContactsPage({ searchParams }: PageProps) {
  const q = searchParams?.q;
  const selectedId = searchParams?.selected;

  const contacts = await fetchContacts({ q });

  let selected = null;
  if (selectedId) {
    try {
      selected = await fetchContact(selectedId);
    } catch (err) {
      if (!(err instanceof ApiError && err.status === 404)) throw err;
    }
  }

  return (
    <div className="k-page">
      <PageHeader
        title="주소록"
        sub={`${contacts.length}명`}
        actions={
          <>
            <Button variant="ghost" size="sm" icon={<Icon name="upload" size={12} />}>
              CSV 가져오기
            </Button>
            <Button variant="primary" size="sm" icon={<Icon name="plus" size={12} />}>
              새 연락처
            </Button>
          </>
        }
      />

      <div className="mb-4">
        <ContactsFilters />
      </div>

      <ContactsTable
        contacts={contacts}
        selectedId={selectedId}
        filter={{ q }}
      />

      <ContactDrawer contact={selected} basePath="/contacts" />
    </div>
  );
}
