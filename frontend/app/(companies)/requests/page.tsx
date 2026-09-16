import { Badge, Card, Notice } from "@/components/ui";
import { getRequests } from "@/lib/api";
import type { PublicRequest } from "@/lib/types";

export const dynamic = "force-dynamic";

/**
 * What buyers are asking for. The third side of the market.
 *
 * Tenders are public demand from government, the directory is supply, and this
 * is private demand — somebody who wants a hundred mats printed and would
 * rather be found than do the finding.
 *
 * Anonymous by design, and the page says so rather than leaving it to be
 * noticed. A board carrying contact details is a board that gets harvested,
 * and the person who wrote "I need 100 mats" would get forty cold emails.
 */
export default async function RequestsPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string; owned?: string }>;
}) {
  const params = await searchParams;
  const query = params.q?.trim() ?? "";
  const ownedOnly = params.owned === "1";

  const board = await getRequests({
    q: query || undefined,
    customerOwned: ownedOnly,
    limit: 100,
  }).catch(() => null);

  if (!board) {
    return (
      <div className="space-y-6">
        <h1 className="text-3xl font-semibold tracking-tight">Open requests</h1>
        <Notice tone="error" title="The board could not be loaded">
          The API is not reachable from this deployment.
        </Notice>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <header className="max-w-3xl">
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">Open requests</h1>
        <p className="mt-3 text-[15px] leading-relaxed text-ink-soft">
          Jobs buyers are looking to place, published by them on purpose. If you
          make things in Berlin, this is demand you would otherwise never hear
          about.
        </p>
        <p className="mt-4 max-w-2xl text-sm text-ink-muted">
          <strong className="font-medium text-ink">No names and no addresses,
          by design.</strong> A board with contact details on it is a board that
          gets harvested, and somebody asking for a hundred printed mats should
          not receive forty cold emails for it. Each buyer chooses who to answer
          — so a listing tells you what the work is, and nothing about who wants
          it.
        </p>
      </header>

      <Card>
        <form className="flex flex-wrap items-end gap-3 border-b border-line px-5 py-4 sm:px-6">
          <div className="min-w-0 flex-1">
            <label htmlFor="q" className="mb-1.5 block text-sm font-medium">
              Search the requests
            </label>
            <input
              id="q"
              name="q"
              defaultValue={query}
              placeholder="Yoga mats, PVC, Textil…"
              className="w-full rounded-lg border border-line bg-surface px-3.5 py-2.5 text-[15px] outline-none transition-colors focus:border-accent"
            />
          </div>
          <label className="flex items-center gap-2 pb-2.5 text-sm text-ink-soft">
            <input type="checkbox" name="owned" value="1" defaultChecked={ownedOnly} className="h-4 w-4" />
            Goods the buyer already owns
          </label>
          <button
            type="submit"
            className="rounded-lg bg-ink px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-ink/90"
          >
            Filter
          </button>
        </form>

        <p className="px-5 py-3 text-xs text-ink-muted sm:px-6">
          Showing <span className="tabular">{board.shown}</span> of{" "}
          <span className="tabular">{board.total}</span> open requests
        </p>

        {board.requests.length === 0 ? (
          <p className="px-5 py-8 text-center text-sm text-ink-soft sm:px-6">
            {board.total === 0
              ? "Nothing is on the board yet. Buyers publish a request from their own project, and only when they choose to."
              : "Nothing open matched that filter."}
          </p>
        ) : (
          <ul>
            {board.requests.map((listing) => (
              <RequestRow key={listing.id} listing={listing} />
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

function RequestRow({ listing }: { listing: PublicRequest }) {
  return (
    <li className="border-t border-line px-5 py-4 sm:px-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[15px] font-semibold">
            {listing.quantity ? (
              <span className="tabular">{listing.quantity}× </span>
            ) : null}
            {listing.product}
          </p>
          <p className="mt-0.5 text-xs text-ink-muted">
            {[listing.material, listing.city].filter(Boolean).join(" · ")}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {/* The most useful line on the board: many shops will not touch
              customer-owned stock, and the ones that will want to know. Shown
              only when the buyer said - silence is not a "no". */}
          {listing.customer_owns_product === true ? (
            <Badge tone="partial">their own goods</Badge>
          ) : null}
          {listing.method ? (
            <Badge tone="neutral">{listing.method.replace(/_/g, " ")}</Badge>
          ) : null}
        </div>
      </div>

      {listing.note ? (
        <p className="mt-2 max-w-2xl text-sm leading-snug text-ink-soft">{listing.note}</p>
      ) : null}

      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-muted">
        {listing.deadline ? <span>needed by {listing.deadline}</span> : null}
        {listing.budget_eur ? (
          <span className="tabular">
            budget {listing.budget_eur.toLocaleString("en-GB", { maximumFractionDigits: 0 })} EUR
          </span>
        ) : null}
        <span>listed {listing.published_at.slice(0, 10)}</span>
        <span>closes {listing.expires_on}</span>
      </div>
    </li>
  );
}
