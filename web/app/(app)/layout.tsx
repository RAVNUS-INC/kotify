import { redirect } from 'next/navigation';
import { getSession } from '@/lib/auth';
import { Sidebar, Topbar } from '@/components/shell';

export default async function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const user = await getSession();
  if (!user) redirect('/login');

  return (
    <div className="k-shell min-h-screen">
      <Sidebar user={user} />
      <main className="k-main" id="main">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-surface focus:px-2 focus:py-1 focus:text-sm focus:shadow-sm"
        >
          본문으로 건너뛰기
        </a>
        <Topbar />
        {children}
      </main>
    </div>
  );
}
