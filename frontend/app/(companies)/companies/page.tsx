import Link from "next/link";

import { CapabilitySearch } from "@/components/partners/CapabilitySearch";
import { PartnerMap } from "@/components/partners/PartnerMap";
import { Badge, Card, CardHeader, Notice } from "@/components/ui";
import { getPartners } from "@/lib/api";
import type { Partner } from "@/lib/types";

export const dynamic = "force-dynamic";

/**
 * The directory's front door.
 *
 * Its own page with its own chrome rather than a tab inside the working app,
 * because the person reading it is a different person: somebody looking for a
 * print shop in Kreuzberg, not somebody mid-project. No sign-in, no project,
 * nothing here belongs to an account.
 *
 * Filtering happens on the server through the query string, so a filtered view
 * is a URL that can be bookmarked and shared - which is how anybody actually
 * works through 135 companies over several days, and what makes the page worth
 * indexing.
 */
export default async function DirectoryPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string; email?: string; borough?: string; type?: string }>;
}) {
  const params = await searchParams;
  const query = params.q?.trim() ?? "";
  const borough = params.borough?.trim() ?? "";
  const category = params.type?.trim() ?? "";
  const onlyContactable = params.email === "1";
  const filtered = Boolean(query || borough || category || onlyContactable);

  const directory = await getPartners({
    q: query || undefined,
    borough: borough || undefined,
    category: category || undefined,
    withEmail: onlyContactable,
  }).catch(() => null);

  if (!directory) {
    return (
      <div className="space-y-6">
        <h1 className="text-3xl font-semibold tracking-tight">Berlin production companies</h1>
        <Notice tone="error" title="The companies could not be loaded">
          The API is not reachable from this deployment.
        </Notice>
      </div>
    );
  }

  const confirmed = directory.partners.filter((partner) => partner.verified).length;

  return (
    <div className="space-y-8">
      <header className="max-w-3xl">
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
          Berlin production companies
        </h1>
        <p className="mt-3 text-[15px] leading-relaxed text-ink-soft">
          Every printing, textile, engraving and finishing business in Berlin
          that publishes its own contact details — collected from
          OpenStreetMap, kept as the companies wrote it, and free to read.
        </p>

        <dl className="mt-6 flex flex-wrap gap-x-10 gap-y-4">
          <div>
            <dt className="text-xs uppercase tracking-wide text-ink-muted">Companies</dt>
            <dd className="tabular text-2xl font-semibold">{directory.total}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wide text-ink-muted">
              With an email address
            </dt>
            <dd className="tabular text-2xl font-semibold">{directory.contactable}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wide text-ink-muted">Boroughs covered</dt>
            <dd className="tabular text-2xl font-semibold">{directory.boroughs.length}</dd>
          </div>
        </dl>

        <p className="mt-5 max-w-2xl text-sm text-ink-muted">
          These are <strong className="font-medium text-ink">listings, not vetted
          suppliers</strong>. The source knows a company exists and where; it does
          not know its materials, minimum order or lead time, and this directory
          does not invent those. Reading a company&rsquo;s own website and having
          a person confirm what it says is what turns a listing into a partner.
        </p>
      </header>

      {directory.incomplete_categories.length > 0 ? (
        <Notice tone="warning" title="This survey came back short">
          {directory.incomplete_categories.join(", ")} could not be fetched when
          the directory was built, so those businesses are missing entirely.
          Their absence is a gap, not a finding.
        </Notice>
      ) : null}

      <Card>
        <CardHeader
          title="Who can do this job?"
          hint="Searched against what each company wrote about itself, not against its name."
        />
        <div className="px-5 py-4 sm:px-6">
          <CapabilitySearch />
        </div>
      </Card>

      <Card>
        <CardHeader
          title={filtered ? "Where these companies are" : "Where they are"}
          hint={
            filtered
              ? "The map follows the filter below."
              : "Filled pins are companies somebody has confirmed."
          }
        />
        <div className="px-5 py-4 sm:px-6">
          <PartnerMap partners={directory.partners} />
        </div>
      </Card>

      <Card>
        <form className="space-y-4 border-b border-line px-5 py-4 sm:px-6">
          <div className="flex flex-wrap items-end gap-3">
            <div className="min-w-0 flex-1">
              <label htmlFor="q" className="mb-1.5 block text-sm font-medium">
                Search by name or address
              </label>
              <input
                id="q"
                name="q"
                defaultValue={query}
                placeholder="Druck, Copy, Leibnizstraße…"
                className="w-full rounded-lg border border-line bg-surface px-3.5 py-2.5 text-[15px] outline-none transition-colors focus:border-accent"
              />
            </div>
            <label className="flex items-center gap-2 pb-2.5 text-sm text-ink-soft">
              <input
                type="checkbox"
                name="email"
                value="1"
                defaultChecked={onlyContactable}
                className="h-4 w-4"
              />
              With an email address
            </label>
            <button
              type="submit"
              className="rounded-lg bg-ink px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-ink/90"
            >
              Filter
            </button>
          </div>

          {/* Links rather than selects: each filtered view is its own URL, so
              "Druckereien in Pankow" is something you can send to somebody. */}
          {directory.categories.length > 0 ? (
            <div>
              <p className="mb-2 text-sm font-medium">Kind of business</p>
              <div className="flex flex-wrap gap-1.5">
                <FilterChip
                  label="All kinds"
                  count={directory.total}
                  query={queryFor({ query, onlyContactable, borough, category: "" })}
                  active={!category}
                />
                {directory.categories.map((item) => (
                  <FilterChip
                    key={item.tag}
                    label={item.label}
                    count={item.count}
                    title={item.tag}
                    query={queryFor({ query, onlyContactable, borough, category: item.tag })}
                    active={category === item.tag}
                  />
                ))}
              </div>
            </div>
          ) : null}

          {directory.boroughs.length > 0 ? (
            <div>
              <p className="mb-2 text-sm font-medium">Borough</p>
              <div className="flex flex-wrap gap-1.5">
                <FilterChip
                  label="All of Berlin"
                  count={directory.total}
                  query={queryFor({ query, onlyContactable, borough: "", category })}
                  active={!borough}
                />
                {directory.boroughs.map((item) => (
                  <FilterChip
                    key={item.name}
                    label={item.name}
                    count={item.count}
                    query={queryFor({ query, onlyContactable, borough: item.name, category })}
                    active={borough === item.name}
                  />
                ))}
              </div>
            </div>
          ) : null}
        </form>

        <div className="flex flex-wrap items-center justify-between gap-2 px-5 py-3 sm:px-6">
          <p className="text-xs text-ink-muted">
            Showing <span className="tabular">{directory.shown}</span> of{" "}
            <span className="tabular">{directory.total}</span>
            {confirmed > 0 ? (
              <>
                {" · "}
                <span className="tabular">{confirmed}</span> confirmed by a person
              </>
            ) : null}
          </p>
          {filtered ? (
            <Link
              href="/companies"
              className="text-xs text-ink-muted underline underline-offset-4 hover:text-ink"
            >
              Clear filters
            </Link>
          ) : null}
        </div>

        {directory.partners.length === 0 ? (
          <p className="px-5 py-8 text-center text-sm text-ink-soft sm:px-6">
            Nothing matched that filter.
          </p>
        ) : (
          <ul>
            {directory.partners.map((partner: Partner) => (
              <li key={partner.id} className="border-t border-line px-5 py-4 sm:px-6">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <Link
                      href={`/companies/${partner.id}`}
                      className="text-[15px] font-semibold underline decoration-line-strong underline-offset-4 hover:text-accent"
                    >
                      {partner.name}
                    </Link>
                    <p className="mt-0.5 text-xs text-ink-muted">
                      {partner.district ? (
                        <span className="text-ink-soft">{partner.district}</span>
                      ) : null}
                      {partner.district && partner.address ? " · " : null}
                      {partner.address}
                    </p>
                    {/* Their own line about themselves, from their site's meta
                        description. Quoted rather than paraphrased, so the page
                        never puts words in a named business's mouth. */}
                    {partner.summary ? (
                      <p className="mt-1.5 max-w-2xl text-sm leading-snug text-ink-soft">
                        {partner.summary}
                      </p>
                    ) : null}
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    {partner.verified ? <Badge tone="match">confirmed</Badge> : null}
                    {/* What the business calls itself, not the method derived
                        from it: three of the survey's tags mean "digital
                        printing", so the method said the same thing about 134
                        of 135 companies. */}
                    <Badge tone="neutral">
                      {partner.category_label ??
                        partner.implied_method?.replace(/_/g, " ") ??
                        "unclassified"}
                    </Badge>
                  </div>
                </div>

                <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
                  {partner.email ? (
                    <a
                      href={`mailto:${partner.email}`}
                      className="text-accent underline underline-offset-4"
                      title={
                        partner.email_source === "website"
                          ? "Read from the company's own website"
                          : "From the company's OpenStreetMap entry"
                      }
                    >
                      {partner.email}
                    </a>
                  ) : (
                    <span className="text-xs text-ink-muted">no email published</span>
                  )}
                  {partner.phone ? <span className="text-ink-soft">{partner.phone}</span> : null}
                  {partner.website ? (
                    <a
                      href={partner.website}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-ink-soft underline underline-offset-4 hover:text-ink"
                    >
                      website
                    </a>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <p className="text-xs text-ink-muted">
        {directory.attribution || "© OpenStreetMap contributors"} · rebuilt with{" "}
        <code className="font-mono">scripts/build_berlin_partners.py</code>, placed
        by <code className="font-mono">scripts/enrich_districts.py</code>
      </p>
    </div>
  );
}

/** One filter chip. A link, so the filtered view has its own address. */
function FilterChip({
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
      href={{ pathname: "/companies", query }}
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

/** Keep the other filters when one of them changes. Dropping them would make
 * every borough click silently clear the search somebody just typed. */
function queryFor({
  query,
  onlyContactable,
  borough,
  category,
}: {
  query: string;
  onlyContactable: boolean;
  borough: string;
  category: string;
}): Record<string, string> {
  const params: Record<string, string> = {};
  if (query) params.q = query;
  if (onlyContactable) params.email = "1";
  if (borough) params.borough = borough;
  if (category) params.type = category;
  return params;
}
