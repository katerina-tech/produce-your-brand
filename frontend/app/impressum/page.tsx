import Link from "next/link";
import type { Metadata } from "next";

import { Logo } from "@/components/Logo";
import { operator } from "@/lib/legal";

export const metadata: Metadata = {
  title: "Impressum — Produce Your Brand",
  description: "Provider identification under § 5 DDG.",
};

export const dynamic = "force-dynamic";

/**
 * Impressum (Anbieterkennzeichnung, § 5 DDG - until 2024 § 5 TMG).
 *
 * German law requires this page to be easy to find, reachable in one click
 * from anywhere, and permanently available. It is linked from the footer of
 * every page for that reason and not as a formality.
 *
 * The details come from the environment. When they are missing this page says
 * so rather than printing a placeholder, because a plausible-looking Impressum
 * with invented details is a false statement about who is responsible for a
 * website - which is the precise thing the law exists to prevent.
 */
export default function ImpressumPage() {
  const details = operator();

  return (
    <div className="mx-auto max-w-2xl px-5 py-12 sm:px-10 sm:py-16">
      <Link href="/" className="inline-block">
        <Logo size={22} />
      </Link>

      <h1 className="mt-10 text-2xl font-bold tracking-tight">Impressum</h1>
      <p className="mt-1.5 text-sm text-ink-muted">
        Provider identification under § 5 DDG
      </p>

      {details ? (
        <div className="mt-8 space-y-6 text-[15px] leading-relaxed">
          <section>
            <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-muted">
              Responsible for this site
            </h2>
            <p className="mt-2 font-medium">{details.name}</p>
            {details.address.map((line) => (
              <p key={line} className="text-ink-soft">
                {line}
              </p>
            ))}
          </section>

          <section>
            <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-muted">
              Contact
            </h2>
            <p className="mt-2">
              <a
                href={`mailto:${details.email}`}
                className="text-accent underline underline-offset-4"
              >
                {details.email}
              </a>
            </p>
            {details.phone ? <p className="text-ink-soft">{details.phone}</p> : null}
          </section>

          {details.register || details.vatId ? (
            <section>
              <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-muted">
                Registration
              </h2>
              {details.register ? <p className="mt-2 text-ink-soft">{details.register}</p> : null}
              {details.vatId ? (
                <p className="text-ink-soft">VAT ID: {details.vatId}</p>
              ) : null}
            </section>
          ) : null}
        </div>
      ) : (
        <div className="mt-8 rounded-lg border border-blocked/30 bg-blocked/5 px-5 py-4 text-[15px] leading-relaxed">
          <p className="font-medium text-blocked">
            This deployment has no operator details configured.
          </p>
          <p className="mt-2 text-ink-soft">
            A German site must name the person or company responsible for it,
            with a postal address and a way to reach them. Until{" "}
            <code className="font-mono text-xs">LEGAL_OPERATOR_NAME</code>,{" "}
            <code className="font-mono text-xs">LEGAL_OPERATOR_ADDRESS</code> and{" "}
            <code className="font-mono text-xs">LEGAL_OPERATOR_EMAIL</code> are
            set, this page says nothing rather than something invented — and the
            site should be treated as a prototype that is not yet published.
          </p>
        </div>
      )}

      <section className="mt-10 border-t border-line pt-6 text-sm leading-relaxed text-ink-soft">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-muted">
          About the content
        </h2>
        <p className="mt-2">
          Partner data shown in this build is synthetic sample data unless a
          screen says otherwise. Businesses shown as nearby studios come from{" "}
          <a
            href="https://www.openstreetmap.org/copyright"
            className="text-accent underline underline-offset-4"
            target="_blank"
            rel="noopener noreferrer"
          >
            OpenStreetMap
          </a>
          , © OpenStreetMap contributors, under the Open Database Licence. This
          site neither verifies nor endorses them.
        </p>
        <p className="mt-3">
          Links to other websites lead to content this site does not control and
          is not responsible for.
        </p>
      </section>

      <p className="mt-10 text-sm">
        <Link href="/privacy" className="text-accent underline underline-offset-4">
          Privacy notice
        </Link>
        {" · "}
        <Link href="/" className="text-accent underline underline-offset-4">
          Back to the site
        </Link>
      </p>
    </div>
  );
}
