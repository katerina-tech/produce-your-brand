import Link from "next/link";
import type { ReactNode } from "react";

import { Logo } from "@/components/Logo";

/**
 * Chrome for the directory, which is its own thing.
 *
 * Three layouts now, for three audiences: `/` sells the product, `(app)` is
 * the working tool behind an optional sign-in, and this is a public reference
 * anybody can read without an account and without a project. Giving it the
 * working app's header would have put "My projects" and "New project" in front
 * of somebody who came looking for a print shop in Kreuzberg.
 *
 * Same brand, same tokens, same components — a separate deployment would have
 * bought a second domain at the price of a second design system, a second API
 * client and a second Impressum, and the directory's whole point is that
 * confirmed companies feed the matcher next door.
 */
export default function DirectoryLayout({ children }: { children: ReactNode }) {
  return (
    <>
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-5 py-4 sm:px-8">
          <Link href="/companies" className="flex items-center gap-3">
            <Logo size={22} />
            <span className="hidden border-l border-line pl-3 text-sm font-medium text-ink-soft sm:inline">
              Berlin Production Directory
            </span>
          </Link>
          <div className="flex items-center gap-5">
            <Link
              href="/companies"
              className="text-sm font-medium text-ink-soft transition-colors hover:text-ink"
            >
              Companies
            </Link>
            <Link
              href="/tenders"
              className="text-sm font-medium text-ink-soft transition-colors hover:text-ink"
            >
              Tenders
            </Link>
            <Link
              href="/new"
              className="rounded-lg border border-line-strong bg-surface px-3.5 py-2 text-sm font-medium text-ink transition-colors hover:bg-canvas"
            >
              Get quotes for a job
            </Link>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-5 py-8 sm:px-8 sm:py-12">{children}</main>

      <footer className="mx-auto max-w-6xl px-5 pb-10 sm:px-8">
        <p className="border-t border-line pt-6 text-xs text-ink-muted">
          Company details are as the businesses published them, collected from{" "}
          <a
            href="https://www.openstreetmap.org/copyright"
            target="_blank"
            rel="noopener noreferrer"
            className="underline underline-offset-4 hover:text-ink"
          >
            OpenStreetMap
          </a>{" "}
          under the ODbL. Nothing here is an endorsement, and no company listed
          has been contacted by this system.
        </p>
        <p className="mt-3 text-xs text-ink-muted">
          <Link href="/privacy" className="hover:text-ink">
            Privacy
          </Link>
          {" · "}
          <Link href="/impressum" className="hover:text-ink">
            Impressum
          </Link>
          {" · "}
          <Link href="/" className="hover:text-ink">
            Produce Your Brand
          </Link>
        </p>
      </footer>
    </>
  );
}
