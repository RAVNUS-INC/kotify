export default function Home() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-12">
      <div className="font-mono text-xs uppercase tracking-[0.08em] text-ink-dim">
        Phase 0 — smoke
      </div>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight">Kotify</h1>
      <p className="mt-2 text-md text-ink-muted">
        토큰·타입·빌드 파이프라인 검증용 페이지. Phase 1에서 UI 프리미티브로 교체됩니다.
      </p>

      <section className="mt-8 grid grid-cols-3 gap-3">
        <Swatch label="brand" className="bg-brand text-white" />
        <Swatch label="brand-soft" className="bg-brand-soft text-brand" />
        <Swatch label="gray-2" className="bg-gray-2 text-gray-11" />
        <Swatch label="success" className="bg-success text-white" />
        <Swatch label="warning" className="bg-warning text-white" />
        <Swatch label="danger" className="bg-danger text-white" />
      </section>

      <section className="mt-8 flex items-center gap-3">
        <button className="inline-flex items-center gap-1.5 rounded bg-brand px-3 py-1.5 text-sm font-medium text-white transition-colors duration-fast ease-out hover:bg-brand-hover">
          Primary
        </button>
        <button className="inline-flex items-center gap-1.5 rounded border border-line-strong bg-surface px-3 py-1.5 text-sm font-medium text-ink transition-colors duration-fast ease-out hover:bg-gray-1">
          Secondary
        </button>
        <kbd className="rounded-xs border border-line bg-gray-1 px-1.5 py-0.5 font-mono text-xs text-ink-dim">
          ⌘K
        </kbd>
      </section>
    </main>
  );
}

function Swatch({ label, className }: { label: string; className: string }) {
  return (
    <div className={`rounded-lg px-3 py-6 text-center font-mono text-xs ${className}`}>{label}</div>
  );
}
