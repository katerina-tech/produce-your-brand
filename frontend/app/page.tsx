import Link from "next/link";

import { Logo, LogoMark } from "@/components/Logo";

/**
 * The marketing homepage. Full-bleed on purpose - it owns its own nav and
 * footer rather than sharing the app shell in `(app)/layout.tsx`, because a
 * prospective customer and a signed-in user looking at their projects need
 * different chrome. Every CTA here routes into the real product: there is no
 * separate "demo" build of the flow that lives only on this page.
 */

const USE_CASES = [
  "Branded merchandise",
  "Corporate gifts",
  "Textiles",
  "Packaging",
  "Event products",
  "Promotional products",
];

const STEPS = [
  {
    n: "01",
    title: "DESCRIBE",
    body: "Tell us what you want to customise.",
  },
  {
    n: "02",
    title: "DEFINE",
    body: "AI creates the production brief and identifies the right method.",
  },
  {
    n: "03",
    title: "MATCH",
    body: "Compare compatible production partners.",
  },
  {
    n: "04",
    title: "PRODUCE",
    body: "Select a partner and create a production-ready RFQ.",
  },
];

export default function MarketingPage() {
  return (
    <div className="bg-canvas">
      {/* NAV */}
      <header className="border-b border-line">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-5 py-5 sm:px-10">
          <Logo size={24} />
          <nav className="hidden items-center gap-8 md:flex">
            <a href="#how-it-works" className="text-sm font-medium hover:text-accent">
              How it works
            </a>
            <a href="#" className="text-sm font-medium hover:text-accent">
              For businesses
            </a>
            <a href="#" className="text-sm font-medium hover:text-accent">
              Partners
            </a>
            <a href="#" className="text-sm font-medium hover:text-accent">
              About
            </a>
          </nav>
          <div className="flex items-center gap-4">
            <Link
              href="/dashboard"
              className="hidden text-sm font-medium text-ink-soft transition-colors hover:text-ink sm:inline"
            >
              My projects
            </Link>
            <Link
              href="/new"
              className="rounded-lg bg-ink px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-ink/90"
            >
              Start a project
            </Link>
          </div>
        </div>
      </header>

      {/* HERO */}
      <section className="mx-auto max-w-6xl px-5 py-16 sm:px-10 sm:py-24">
        <div className="grid gap-14 lg:grid-cols-[1fr_1fr] lg:items-center lg:gap-16">
          <div className="space-y-6">
            <p className="eyebrow text-accent">
              For requests a normal search can&apos;t solve
            </p>
            <h1 className="text-4xl font-bold tracking-tight sm:text-5xl lg:text-[3.4rem] lg:leading-[1.06]">
              You know what you want.{" "}
              <span className="text-accent">We find who can make it.</span>
            </h1>
            <p className="text-lg text-ink">
              Find the right production partner for complex, non-standard
              requests.
            </p>
            <p className="max-w-md text-[15px] leading-relaxed text-ink-soft">
              Unusual material, a customer-owned product, an odd quantity, a
              tight deadline, or a few of those at once - describe it, and we
              compare production capabilities, lead times and available
              offers to find the right way to make it.
            </p>
            <div className="flex flex-wrap items-center gap-6 pt-2">
              <Link
                href="/new"
                className="rounded-lg bg-ink px-6 py-3.5 text-sm font-semibold text-white transition-colors hover:bg-ink/90"
              >
                Start a production project
              </Link>
              <a
                href="#how-it-works"
                className="text-sm font-semibold text-ink transition-colors hover:text-accent"
              >
                See how it works &rarr;
              </a>
            </div>
          </div>

          <div className="rounded-xl border border-line bg-surface p-7 shadow-[0_24px_60px_-30px_rgba(25,28,35,0.25)]">
            <p className="eyebrow mb-5">
              Product &rarr; Customisation &rarr; Partner &rarr; RFQ
            </p>
            <FlowRow
              step="01 · Product"
              title="100× Black Yoga Mats"
              dot="ink"
            />
            <FlowRow
              step="02 · Customisation"
              title="Gold Logo · Silkscreen Print"
              dot="ink"
            />
            <FlowRow
              step="03 · Production Partner"
              title="Studio Nordlicht · Berlin"
              dot="accent"
              pill={{ tone: "match", label: "94% Match" }}
            />
            <FlowRow
              step="04 · RFQ"
              title="Ready for Review"
              dot="outline"
              pill={{ tone: "partial", label: "Awaiting approval" }}
              last
            />
          </div>
        </div>
      </section>

      {/* HOW IT WORKS */}
      <section id="how-it-works" className="border-t border-line bg-surface">
        <div className="mx-auto max-w-6xl px-5 py-16 sm:px-10 sm:py-20">
          <div className="mb-12 flex flex-wrap items-end justify-between gap-4">
            <h2 className="text-2xl font-bold tracking-tight sm:text-3xl">
              How it works
            </h2>
            <p className="eyebrow">Four steps · One request</p>
          </div>
          <div className="grid gap-8 sm:grid-cols-2 lg:grid-cols-4 lg:divide-x lg:divide-line">
            {STEPS.map((step) => (
              <div key={step.n} className="lg:px-8 lg:first:pl-0">
                <p className="mb-4 text-sm font-semibold text-accent">{step.n}</p>
                <p className="mb-2.5 text-[17px] font-bold tracking-tight">
                  {step.title}
                </p>
                <p className="text-sm leading-relaxed text-ink-soft">{step.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* PRODUCT SHOWCASE */}
      <section className="mx-auto max-w-6xl px-5 py-16 sm:px-10 sm:py-24">
        <div className="mb-10 max-w-xl">
          <p className="eyebrow mb-4 text-accent">Inside the platform</p>
          <h2 className="mb-3 text-2xl font-bold tracking-tight sm:text-3xl">
            This is the actual application &mdash; not a mockup of one.
          </h2>
          <p className="text-[15px] leading-relaxed text-ink-soft">
            Every project moves through the same four surfaces: the
            production brief, the recommended method, partner matches, and
            the resulting RFQ.
          </p>
        </div>

        <div className="overflow-hidden rounded-xl border border-line bg-surface shadow-[0_24px_60px_-30px_rgba(25,28,35,0.25)]">
          <div className="flex items-center gap-2 border-b border-line bg-canvas px-4 py-3">
            <span className="h-2.5 w-2.5 rounded-full bg-line-strong" />
            <span className="h-2.5 w-2.5 rounded-full bg-line-strong" />
            <span className="h-2.5 w-2.5 rounded-full bg-line-strong" />
            <span className="flex-1 text-center text-xs font-medium text-ink-muted">
              app.produceyourbrand.com/projects/1842
            </span>
          </div>

          <div className="flex flex-wrap border-b border-line px-2 sm:px-6">
            <span className="px-3 py-4 text-sm font-medium text-ink-muted sm:px-5">
              Production Brief
            </span>
            <span className="-mb-px border-b-2 border-accent px-3 py-4 text-sm font-semibold text-ink sm:px-5">
              Recommended Method
            </span>
            <span className="px-3 py-4 text-sm font-medium text-ink-muted sm:px-5">
              Partner Matches
            </span>
            <span className="px-3 py-4 text-sm font-medium text-ink-muted sm:px-5">
              RFQ
            </span>
          </div>

          <div className="grid gap-8 p-6 sm:p-8 lg:grid-cols-[1.4fr_1fr]">
            <div>
              <div className="mb-5 flex items-center justify-between gap-3">
                <p className="text-xl font-bold tracking-tight">
                  Screen Printing · Gold Ink
                </p>
                <span className="inline-flex items-center rounded-full bg-match-bg px-2.5 py-1 text-[10.5px] font-semibold uppercase tracking-wide text-match">
                  Compatible
                </span>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <SpecTile label="Material" value="Cotton-blend jersey" />
                <SpecTile label="Max colours" value="4 · incl. metallic" />
                <SpecTile label="Lead time" value="8–10 working days" />
                <SpecTile label="Minimum order" value="50 units" />
              </div>
            </div>

            <div className="border-t border-line pt-6 lg:border-l lg:border-t-0 lg:pl-8 lg:pt-0">
              <p className="eyebrow mb-4">Partner matches</p>
              <div className="space-y-3.5">
                <MatchRow
                  name="Studio Nordlicht · Berlin"
                  score={94}
                  pillLabel="Top match"
                  highlighted
                />
                <MatchRow name="Formwerk GmbH · Leipzig" score={78} />
                <MatchRow name="Kontur Print · Hamburg" score={61} />
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* USE CASES */}
      <section className="border-t border-line bg-surface">
        <div className="mx-auto max-w-6xl px-5 py-16 sm:px-10 sm:py-20">
          <div className="mb-10 flex flex-wrap items-end justify-between gap-4">
            <h2 className="text-2xl font-bold tracking-tight sm:text-3xl">
              Built for physical products
            </h2>
            <p className="eyebrow">Small &amp; medium batches</p>
          </div>
          <div className="grid grid-cols-1 gap-px overflow-hidden border border-line bg-line sm:grid-cols-2 lg:grid-cols-3">
            {USE_CASES.map((label, i) => (
              <div key={label} className="bg-surface p-8">
                <p className="mb-3.5 text-sm font-semibold text-accent">
                  {String(i + 1).padStart(2, "0")}
                </p>
                <p className="text-[17px] font-bold">{label}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* TRUST */}
      <section className="mx-auto max-w-6xl px-5 py-20 text-center sm:px-10 sm:py-28">
        <p className="text-3xl font-bold tracking-tight sm:text-[2.7rem]">
          AI recommends. <span className="text-accent">You decide.</span>
        </p>
        <p className="mx-auto mt-5 max-w-xl text-[16px] leading-relaxed text-ink-soft">
          Supplier matching is transparent and explainable. You always see
          why a method or a partner was suggested &mdash; and you approve
          every production decision before it moves forward.
        </p>
        <div className="mx-auto mt-10 grid max-w-3xl gap-6 border-t border-line pt-8 sm:grid-cols-3 sm:divide-x sm:divide-line">
          <p className="text-sm font-semibold sm:px-6">Transparent matching</p>
          <p className="text-sm font-semibold sm:px-6">
            Human approval at every step
          </p>
          <p className="text-sm font-semibold sm:px-6">Vetted European partners</p>
        </div>
      </section>

      {/* FINAL CTA */}
      <section className="bg-ink py-20 text-center sm:py-28">
        <div className="mx-auto max-w-2xl px-5 sm:px-10">
          <p className="text-3xl font-bold leading-tight tracking-tight text-white sm:text-[2.5rem]">
            Your product.
            <br />
            Your design.
            <br />
            <span className="text-accent">The right production partner.</span>
          </p>
          <Link
            href="/new"
            className="mt-9 inline-flex rounded-lg bg-accent px-7 py-4 text-[15px] font-semibold text-white transition-colors hover:opacity-90"
          >
            Start your first project
          </Link>
        </div>
      </section>

      {/* FOOTER */}
      <footer className="mx-auto max-w-6xl px-5 py-12 sm:px-10">
        <div className="flex flex-wrap items-start justify-between gap-8">
          <div className="flex items-center gap-2.5">
            <LogoMark size={18} />
            <span className="text-xs text-ink-muted">
              &copy; 2026 Produce Your Brand GmbH · Berlin
            </span>
          </div>
          <div className="flex flex-wrap gap-12">
            <div className="space-y-2.5">
              <p className="eyebrow">Product</p>
              <a href="#how-it-works" className="block text-sm text-ink-soft hover:text-ink">
                How it works
              </a>
              <Link href="/dashboard" className="block text-sm text-ink-soft hover:text-ink">
                My projects
              </Link>
            </div>
            <div className="space-y-2.5">
              <p className="eyebrow">Company</p>
              <a href="#" className="block text-sm text-ink-soft hover:text-ink">
                About
              </a>
              <a href="#" className="block text-sm text-ink-soft hover:text-ink">
                Contact
              </a>
            </div>
            <div className="space-y-2.5">
              <p className="eyebrow">Legal</p>
              <a href="#" className="block text-sm text-ink-soft hover:text-ink">
                Privacy
              </a>
              <a href="#" className="block text-sm text-ink-soft hover:text-ink">
                Imprint
              </a>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}

function FlowRow({
  step,
  title,
  dot,
  pill,
  last = false,
}: {
  step: string;
  title: string;
  dot: "ink" | "accent" | "outline";
  pill?: { tone: "match" | "partial"; label: string };
  last?: boolean;
}) {
  const dotClass =
    dot === "ink"
      ? "bg-ink"
      : dot === "accent"
        ? "bg-accent"
        : "border-2 border-ink bg-canvas";
  const pillClass =
    pill?.tone === "match"
      ? "bg-match-bg text-match"
      : "bg-partial-bg text-partial";

  return (
    <div
      className={`flex gap-4 py-4 ${last ? "" : "border-b border-line"}`}
    >
      <span className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-sm ${dotClass}`} />
      <div className="flex flex-1 items-center justify-between gap-3">
        <div>
          <p className="eyebrow mb-1">{step}</p>
          <p className="text-[15px] font-semibold">{title}</p>
        </div>
        {pill ? (
          <span
            className={`inline-flex items-center whitespace-nowrap rounded-full px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide ${pillClass}`}
          >
            {pill.label}
          </span>
        ) : null}
      </div>
    </div>
  );
}

function SpecTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-line px-4 py-3.5">
      <p className="eyebrow mb-1.5">{label}</p>
      <p className="text-sm font-semibold">{value}</p>
    </div>
  );
}

function MatchRow({
  name,
  score,
  pillLabel,
  highlighted = false,
}: {
  name: string;
  score: number;
  pillLabel?: string;
  highlighted?: boolean;
}) {
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between gap-3">
        <span className="text-sm font-semibold">{name}</span>
        {pillLabel ? (
          <span className="inline-flex items-center rounded-full bg-match-bg px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-match">
            {pillLabel}
          </span>
        ) : (
          <span className="text-xs text-ink-muted">{score}%</span>
        )}
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-line">
        <div
          className={`h-full rounded-full ${highlighted ? "bg-accent" : "bg-ink"}`}
          style={{ width: `${score}%` }}
        />
      </div>
    </div>
  );
}
