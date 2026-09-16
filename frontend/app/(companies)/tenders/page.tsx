import Link from "next/link";

import { Badge, Card, Notice } from "@/components/ui";
import { getTenders } from "@/lib/api";
import type { Tender } from "@/lib/types";

export const dynamic = "force-dynamic";

/**
 * Public contracts, from Germany's open procurement data.
 *
 * The other half of the market, and the reason it sits next to the company
 * directory rather than on a site of its own: a tender aggregator can tell you
 * a contract exists, and only this one can also tell you which Berlin shop
 * said, in its own words, that it does this work.
 *
 * Soonest deadline first. A board sorted by publication date is a board that
 * shows you a contract you can no longer bid for above one closing on Friday.
 */
export default async function TendersPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string; family?: string; berlin?: string; smes?: string }>;
}) {
  const params = await searchParams;
  const query = params.q?.trim() ?? "";
  const family = params.family?.trim() ?? "";
  const berlinOnly = params.berlin === "1";
  const smesOnly = params.smes === "1";
  const filtered = Boolean(query || family || berlinOnly || smesOnly);

  const board = await getTenders({
    q: query || undefined,
    family: family || undefined,
    berlin: berlinOnly,
    smes: smesOnly,
    limit: 120,
  }).catch(() => null);

  if (!board) {
    return (
      <div className="space-y-6">
        <h1 className="text-3xl font-semibold tracking-tight">Public tenders</h1>
        <Notice tone="error" title="The tender board could not be loaded">
          The API is not reachable from this deployment.
        </Notice>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <header className="max-w-3xl">
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">Public tenders</h1>
        <p className="mt-3 text-[15px] leading-relaxed text-ink-soft">
          Printing, textile and engraving contracts put out by German public
          buyers — federal, state and municipal, including the smaller{" "}
          <strong className="font-medium text-ink">below-threshold</strong>{" "}
          contracts that never reach the EU journal and are the ones a small shop
          can actually win.
        </p>

        <dl className="mt-6 flex flex-wrap gap-x-10 gap-y-4">
          <div>
            <dt className="text-xs uppercase tracking-wide text-ink-muted">Open notices</dt>
            <dd className="tabular text-2xl font-semibold">{board.total}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wide text-ink-muted">Work in Berlin</dt>
            <dd className="tabular text-2xl font-semibold">{board.berlin}</dd>
          </div>
        </dl>
      </header>

      <Card>
        <form className="space-y-4 border-b border-line px-5 py-4 sm:px-6">
          <div className="flex flex-wrap items-end gap-3">
            <div className="min-w-0 flex-1">
              <label htmlFor="q" className="mb-1.5 block text-sm font-medium">
                Search the notices
              </label>
              <input
                id="q"
                name="q"
                defaultValue={query}
                placeholder="Broschüren, Bekleidung, Kuvertierung…"
                className="w-full rounded-lg border border-line bg-surface px-3.5 py-2.5 text-[15px] outline-none transition-colors focus:border-accent"
              />
            </div>
            <label className="flex items-center gap-2 pb-2.5 text-sm text-ink-soft">
              <input type="checkbox" name="berlin" value="1" defaultChecked={berlinOnly} className="h-4 w-4" />
              Berlin only
            </label>
            <label className="flex items-center gap-2 pb-2.5 text-sm text-ink-soft">
              <input type="checkbox" name="smes" value="1" defaultChecked={smesOnly} className="h-4 w-4" />
              Suitable for small firms
            </label>
            <button
              type="submit"
              className="rounded-lg bg-ink px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-ink/90"
            >
              Filter
            </button>
          </div>

          {board.families.length > 0 ? (
            <div>
              <p className="mb-2 text-sm font-medium">Kind of contract</p>
              <div className="flex flex-wrap gap-1.5">
                <FamilyChip
                  label="All kinds"
                  count={board.total}
                  query={queryFor({ query, berlinOnly, smesOnly, family: "" })}
                  active={!family}
                />
                {board.families.map((item) => (
                  <FamilyChip
                    key={item.prefix}
                    label={item.label}
                    count={item.count}
                    title={`CPV ${item.prefix}…`}
                    query={queryFor({ query, berlinOnly, smesOnly, family: item.prefix })}
                    active={family === item.prefix}
                  />
                ))}
              </div>
            </div>
          ) : null}
        </form>

        <div className="flex flex-wrap items-center justify-between gap-2 px-5 py-3 sm:px-6">
          <p className="text-xs text-ink-muted">
            Showing <span className="tabular">{board.shown}</span> of{" "}
            <span className="tabular">{board.total}</span> open notices
          </p>
          {filtered ? (
            <Link
              href="/tenders"
              className="text-xs text-ink-muted underline underline-offset-4 hover:text-ink"
            >
              Clear filters
            </Link>
          ) : null}
        </div>

        {board.tenders.length === 0 ? (
          <p className="px-5 py-8 text-center text-sm text-ink-soft sm:px-6">
            {board.total === 0
              ? "No notices have been imported yet. Run scripts/fetch_tenders.py."
              : "Nothing open matched that filter."}
          </p>
        ) : (
          <ul>
            {board.tenders.map((tender) => (
              <TenderRow key={tender.id} tender={tender} />
            ))}
          </ul>
        )}
      </Card>

      <p className="max-w-3xl text-xs text-ink-muted">{board.attribution}</p>
    </div>
  );
}

function TenderRow({ tender }: { tender: Tender }) {
  return (
    <li className="border-t border-line px-5 py-4 sm:px-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <Link
            href={`/tenders/${tender.id}`}
            className="text-[15px] font-semibold underline decoration-line-strong underline-offset-4 hover:text-accent"
          >
            {tender.title}
          </Link>
          <p className="mt-0.5 text-xs text-ink-muted">
            {tender.buyer}
            {tender.place_city ? ` · ${tender.place_city}` : ""}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {tender.in_berlin ? <Badge tone="match">Berlin</Badge> : null}
          {/* Three-valued on screen too: "the buyer did not say" is not "no",
              and a badge that collapsed them would turn silence into a refusal. */}
          {tender.suitable_for_smes ? <Badge tone="partial">for small firms</Badge> : null}
          <Badge tone="neutral">{tender.family_label}</Badge>
        </div>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
        <Deadline deadline={tender.deadline} />
        <Money value={tender.estimated_value} currency={tender.currency} />
        <a
          href={tender.source_url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs text-ink-muted underline underline-offset-4 hover:text-ink"
        >
          the notice
        </a>
      </div>
    </li>
  );
}

/** How long is left, in the words somebody deciding whether to bid would use. */
export function Deadline({ deadline }: { deadline: string | null }) {
  if (!deadline) {
    return <span className="text-xs text-ink-muted">no deadline stated</span>;
  }
  const closes = new Date(deadline);
  const days = Math.ceil((closes.getTime() - Date.now()) / 86_400_000);
  const when = closes.toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });

  if (days < 0) return <span className="text-xs text-ink-muted">closed {when}</span>;
  return (
    <span className={days <= 7 ? "text-sm font-medium text-mismatch" : "text-sm text-ink-soft"}>
      closes {when}
      {days <= 14 ? ` · ${days === 0 ? "today" : `${days} day${days === 1 ? "" : "s"} left`}` : ""}
    </span>
  );
}

/** Euros when the buyer stated a figure. Most do not, and this says so rather
 * than printing a zero that would read as free. */
export function Money({ value, currency }: { value: number | null; currency: string }) {
  if (!value) return <span className="text-xs text-ink-muted">value not stated</span>;
  return (
    <span className="tabular text-sm text-ink-soft">
      {value.toLocaleString("en-GB", { maximumFractionDigits: 0 })} {currency || "EUR"}
    </span>
  );
}

function FamilyChip({
  label,
  count,
  query,
  active,
  title,
}: {
  label: string;
  count: number;
  query: Record<string, string>;
  active: boolean;
  title?: string;
}) {
  return (
    <Link
      title={title}
      href={{ pathname: "/tenders", query }}
      className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs transition-colors ${
        active
          ? "border-ink bg-ink text-white"
          : "border-line bg-surface text-ink-soft hover:border-line-strong hover:text-ink"
      }`}
    >
      {label}
      <span className={`tabular ${active ? "text-white/70" : "text-ink-muted"}`}>{count}</span>
    </Link>
  );
}

function queryFor({
  query,
  berlinOnly,
  smesOnly,
  family,
}: {
  query: string;
  berlinOnly: boolean;
  smesOnly: boolean;
  family: string;
}): Record<string, string> {
  const params: Record<string, string> = {};
  if (query) params.q = query;
  if (berlinOnly) params.berlin = "1";
  if (smesOnly) params.smes = "1";
  if (family) params.family = family;
  return params;
}
