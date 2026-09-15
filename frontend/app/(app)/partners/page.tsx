import Link from "next/link";

import { CapabilitySearch } from "@/components/partners/CapabilitySearch";
import { Badge, Card, CardHeader, Notice } from "@/components/ui";
import { getPartners } from "@/lib/api";
import type { Partner } from "@/lib/types";

export const dynamic = "force-dynamic";

/**
 * The directory of real businesses.
 *
 * Separate from the matcher on purpose, and the page says so rather than
 * leaving it to be inferred. These companies exist; nobody has established
 * what they can do. Showing them beside scored matches without that line would
 * be the product implying it knows more about a named Berlin firm than it
 * does.
 *
 * Filtering happens on the server through the query string, so a filtered view
 * is a URL somebody can bookmark and come back to - which is how a person
 * actually works through a list of 135 companies over several days.
 */
export default async function PartnersPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string; email?: string }>;
}) {
  const params = await searchParams;
  const query = params.q?.trim() ?? "";
  const onlyContactable = params.email === "1";

  const directory = await getPartners({
    q: query || undefined,
    withEmail: onlyContactable,
  }).catch(() => null);

  if (!directory) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-semibold tracking-tight">Berlin directory</h1>
        <Notice tone="error" title="The directory could not be loaded">
          The API is not reachable, or the directory file has not been built on
          this deployment.
        </Notice>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Berlin directory</h1>
        <p className="mt-1.5 max-w-2xl text-sm text-ink-soft">
          <span className="tabular">{directory.total}</span> real production
          businesses in Berlin, with the contact details they published
          themselves.{" "}
          <span className="tabular">{directory.contactable}</span> of them list an
          email address.
        </p>
        <p className="mt-2 max-w-2xl text-sm text-ink-muted">
          These are <strong className="font-medium text-ink">not scored matches</strong>.
          The source knows a company exists and where; it does not know its
          materials, minimum order or lead time — and this product does not
          invent those for a company that exists by name. Confirming them is
          what turns a listing here into a partner the matcher can rank.
        </p>
      </div>

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
        <form className="flex flex-wrap items-end gap-3 border-b border-line px-5 py-4 sm:px-6">
          <div className="min-w-0 flex-1">
            <label htmlFor="q" className="mb-1.5 block text-sm font-medium">
              Search by name or address
            </label>
            <input
              id="q"
              name="q"
              defaultValue={query}
              placeholder="Kreuzberg, Druck, Copy…"
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
          {query || onlyContactable ? (
            <Link
              href="/partners"
              className="pb-2.5 text-sm text-ink-muted underline underline-offset-4 hover:text-ink"
            >
              Clear
            </Link>
          ) : null}
        </form>

        <p className="px-5 py-3 text-xs text-ink-muted sm:px-6">
          Showing <span className="tabular">{directory.shown}</span> of{" "}
          <span className="tabular">{directory.total}</span>
        </p>

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
                      href={`/partners/${partner.id}`}
                      className="text-[15px] font-semibold underline decoration-line-strong underline-offset-4 hover:text-accent"
                    >
                      {partner.name}
                    </Link>
                    {partner.address ? (
                      <p className="mt-0.5 text-xs text-ink-muted">{partner.address}</p>
                    ) : null}
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    {partner.verified ? <Badge tone="match">confirmed</Badge> : null}
                    <Badge tone="neutral">
                      {partner.implied_method
                        ? partner.implied_method.replace(/_/g, " ")
                        : "unclassified"}
                    </Badge>
                  </div>
                </div>

                <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
                  {partner.email ? (
                    <a
                      href={`mailto:${partner.email}`}
                      className="text-accent underline underline-offset-4"
                    >
                      {partner.email}
                    </a>
                  ) : (
                    <span className="text-xs text-ink-muted">no email published</span>
                  )}
                  {partner.phone ? (
                    <span className="text-ink-soft">{partner.phone}</span>
                  ) : null}
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
        <code className="font-mono">scripts/build_berlin_partners.py</code>
      </p>
    </div>
  );
}
