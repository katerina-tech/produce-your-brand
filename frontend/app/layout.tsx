import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";

import "./globals.css";

export const metadata: Metadata = {
  title: "Produce Your Stuff",
  description:
    "Describe what you want to customise. Produce Your Stuff works out how it can be made and who can make it.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <header className="border-b border-line bg-surface">
          <div className="mx-auto flex max-w-5xl items-center justify-between px-5 py-4 sm:px-8">
            <Link href="/" className="group flex items-baseline gap-2.5">
              <span className="text-[15px] font-semibold tracking-tight">
                Produce Your Stuff
              </span>
              <span className="hidden text-xs text-ink-muted sm:inline">
                Sourcing &amp; production orchestration
              </span>
            </Link>
            <Link
              href="/new"
              className="rounded-lg bg-ink px-3.5 py-2 text-sm font-medium text-white transition-colors hover:bg-ink/90"
            >
              New project
            </Link>
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
      </body>
    </html>
  );
}
