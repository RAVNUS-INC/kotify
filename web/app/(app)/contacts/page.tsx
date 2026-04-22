import { PageHeader } from '@/components/shell';
import {
  ContactDrawer,
  ContactsAdminShell,
  ContactsFilters,
  ContactsTable,
} from '@/components/contacts';
import { ApiError } from '@/lib/api';
import { getSession, hasRole } from '@/lib/auth';
import { fetchContact, fetchContacts } from '@/lib/contacts';

type PageProps = {
  searchParams?: {
    q?: string;
    selected?: string;
  };
};

export default async function ContactsPage({ searchParams }: PageProps) {
  const q = searchParams?.q;
  const selectedId = searchParams?.selected;

  const [session, contacts] = await Promise.all([
    getSession(),
    fetchContacts({ q }),
  ]);
  const canManage = session ? hasRole(session, 'admin', 'owner', 'sender') : false;

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
        actions={<ContactsAdminShell canManage={canManage} />}
      />

      <div className="mb-4">
        <ContactsFilters />
      </div>

      <ContactsTable
        contacts={contacts}
        selectedId={selectedId}
        filter={{ q }}
      />

      <ContactDrawer
        contact={selected}
        basePath="/contacts"
        canManage={canManage}
      />
    </div>
  );
}
