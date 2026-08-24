import Link from "next/link";
import type { ReactNode } from "react";

import { Logo } from "@/components/Logo";

/**
 * Chrome for the working app (new project, project detail, dashboard) - as
 * opposed to the marketing page at `/`, which is full-bleed and has none of
 * this. Kept as its own layout (route group `(app)`) so the two never fight
 * over the same header/footer.
 */
export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <>
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-5 py-4 sm:px-8">
          <Link href="/" className="group flex items-center gap-2.5">
            <Logo size={22} />
            <span className="hidden text-xs text-ink-muted sm:inline">
              Sourcing &amp; production orchestration
            </span>
          </Link>
          <div className="flex items-center gap-5">
            <Link
              href="/dashboard"
              className="hidden text-sm font-medium text-ink-soft transition-colors hover:text-ink sm:inline"
            >
              My projects
            </Link>
            <Link
              href="/new"
              className="rounded-lg bg-ink px-3.5 py-2 text-sm font-medium text-white transition-colors hover:bg-ink/90"
            >
              New project
            </Link>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-5 py-8 sm:px-8 sm:py-12">
        {children}
      </main>

      <footer className="mx-auto max-w-5xl px-5 pb-10 sm:px-8">
        <p className="border-t border-line pt-6 text-xs text-ink-muted">
          The agent recommends; you decide. Nothing is ordered and no partner is
          contacted by this system. Partner data in this build is synthetic.
        </p>
      </footer>
    </>
  );
}
