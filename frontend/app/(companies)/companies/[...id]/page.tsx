import { notFound } from "next/navigation";

import { ConfirmReading } from "@/components/partners/ConfirmReading";
import { Badge, BackLink, Card, CardHeader, Notice } from "@/components/ui";
import { getPartnerDetail } from "@/lib/api";

export const dynamic = "force-dynamic";

/**
 * One company, and what its own website says it does.
 *
 * A catch-all segment because the id is an OpenStreetMap reference with a
 * slash in it — "node/6532305050". Encoding the slash would make the URL
 * unshareable in practice: proxies normalise %2F back, and some refuse it.
 *
 * Public, like the rest of the directory: no sign-in, no project, nothing here
 * belongs to an account.
 *
 * The page is built around the quotes rather than the claims. A claim on its
 * own is this product's summary of a named business; the quote is the business
 * speaking. Anybody being asked to confirm a reading needs the second to judge
 * the first, so they sit together and neither is shown alone.
 */
export default async function PartnerPage({
  params,
}: {
  params: Promise<{ id: string[] }>;
}) {
  const { id } = await params;
  const partnerId = id.join("/");
  const detail = await getPartnerDetail(partnerId).catch(() => null);

  if (!detail) notFound();

  const { partner, claims } = detail;
  const neverRead = detail.extracted_on === null;

  return (
    <div className="space-y-6">
      <BackLink href="/companies">← All companies</BackLink>

      <div>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <h1 className="text-2xl font-semibold tracking-tight">{partner.name}</h1>
          {partner.verified ? (
            <Badge tone="match">confirmed</Badge>
          ) : (
            <Badge tone="neutral">unconfirmed</Badge>
          )}
        </div>
        {partner.address || partner.district ? (
          <p className="mt-1.5 text-sm text-ink-soft">
            {partner.district ? <span>{partner.district}</span> : null}
            {partner.district && partner.address ? " · " : null}
            {partner.address}
          </p>
        ) : null}

        {/* Their own line, from their site's meta description. The page quotes
            it rather than paraphrasing, so nothing here is this product's
            opinion about a named business. */}
        {partner.summary ? (
          <p className="mt-3 max-w-2xl text-[15px] leading-relaxed text-ink-soft">
            {partner.summary}
          </p>
        ) : null}

        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
          {partner.email ? (
            <span className="flex items-center gap-1.5">
              <a
                href={`mailto:${partner.email}`}
                className="text-accent underline underline-offset-4"
              >
                {partner.email}
              </a>
              {/* Where it came from, said plainly. A map tag and a company's
                  own contact page are not equally likely to still be watched,
                  and somebody about to write deserves to know which they have. */}
              <span className="text-xs text-ink-muted">
                {partner.email_source === "website" ? "from their website" : "from OpenStreetMap"}
              </span>
            </span>
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
              {partner.website.replace(/^https?:\/\//, "")}
            </a>
          ) : null}
        </div>
      </div>

      <Card>
        <CardHeader
          title="What their website says they do"
          hint={
            neverRead
              ? "Nobody has read this company's site yet."
              : `Read on ${detail.extracted_on} from ${detail.source_urls.length} page${
                  detail.source_urls.length === 1 ? "" : "s"
                }.`
          }
        />

        <div className="space-y-4 px-5 py-4 sm:px-6">
          {claims.length === 0 ? (
            <Notice tone={neverRead ? "neutral" : "warning"} title="Nothing to show">
              {detail.reading_note}
            </Notice>
          ) : (
            <ul className="space-y-3">
              {claims.map((claim, index) => (
                <li key={index} className="rounded-lg border border-line bg-canvas px-4 py-3">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <p className="text-[15px] font-medium">{claim.text}</p>
                    <Badge tone="neutral">
                      {claim.method ? claim.method.replace(/_/g, " ") : claim.kind}
                    </Badge>
                  </div>
                  <blockquote className="mt-2 border-l-2 border-line-strong pl-3 text-sm italic text-ink-soft">
                    “{claim.quote}”
                  </blockquote>
                </li>
              ))}
            </ul>
          )}

          {detail.dropped_count > 0 ? (
            <p className="text-xs text-ink-muted">
              <span className="tabular">{detail.dropped_count}</span> further
              claim{detail.dropped_count === 1 ? " was" : "s were"} proposed and
              deleted: the words quoted for{" "}
              {detail.dropped_count === 1 ? "it" : "them"} were not on the page.
              Shown rather than hidden — a reading that dropped a lot is one
              worth a closer look.
            </p>
          ) : null}

          {detail.source_urls.length > 0 ? (
            <div className="border-t border-line pt-3">
              <p className="text-xs font-medium text-ink-soft">Read from</p>
              <ul className="mt-1 space-y-0.5">
                {detail.source_urls.map((url) => (
                  <li key={url}>
                    <a
                      href={url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="break-all text-xs text-ink-muted underline underline-offset-4 hover:text-ink"
                    >
                      {url}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      </Card>

      <Card>
        <CardHeader
          title="Is this right?"
          hint="A reading nobody checked is a lead. A reading somebody confirmed is a partner."
        />
        <div className="px-5 py-4 sm:px-6">
          <ConfirmReading
            partnerId={partner.id}
            verified={partner.verified}
            hasClaims={claims.length > 0}
          />
        </div>
      </Card>
    </div>
  );
}
