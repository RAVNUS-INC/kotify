import { Sidebar, Topbar } from '@/components/shell';

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="k-shell min-h-screen">
      <Sidebar />
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
