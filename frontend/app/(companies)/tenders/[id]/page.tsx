import { notFound } from "next/navigation";

import { TenderMatches } from "@/components/partners/TenderMatches";
import { BackLink, Badge, Card, CardHeader, Notice } from "@/components/ui";
import { getTender } from "@/lib/api";

import { Deadline, Money } from "../page";

export const dynamic = "force-dynamic";

/**
 * One public contract, and the companies that say they can do it.
 *
 * Everything above the fold is the buyer's own text. This product does not
 * summarise a tender: a paraphrase of a legal notice is a paraphrase somebody
 * might bid against, and the notice itself is one click away for the parts
 * that decide.
 */
export default async function TenderPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const tender = await getTender(id).catch(() => null);

  if (!tender) notFound();

  return (
    <div className="space-y-6">
      <BackLink href="/tenders">← All tenders</BackLink>

      <div>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <h1 className="max-w-3xl text-2xl font-semibold tracking-tight">{tender.title}</h1>
          <div className="flex flex-wrap items-center gap-2">
            {tender.in_berlin ? <Badge tone="match">Berlin</Badge> : null}
            {tender.suitable_for_smes ? <Badge tone="partial">for small firms</Badge> : null}
            <Badge tone="neutral">{tender.family_label}</Badge>
          </div>
        </div>

        <p className="mt-2 text-sm text-ink-soft">
          {tender.buyer}
          {tender.place_city ? ` · ${tender.place_city}` : ""}
        </p>

        <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1">
          <Deadline deadline={tender.deadline} />
          <Money value={tender.estimated_value} currency={tender.currency} />
          <span className="text-xs text-ink-muted">
            published {tender.published_on} · CPV {tender.cpv}
          </span>
        </div>
      </div>

      {tender.description ? (
        <Card>
          <CardHeader
            title="What the buyer asked for"
            hint="Their words, unedited. This product does not summarise a legal notice."
          />
          <p className="whitespace-pre-line px-5 py-4 text-[15px] leading-relaxed text-ink-soft sm:px-6">
            {tender.description}
          </p>
        </Card>
      ) : null}

      <Card>
        <CardHeader
          title="Who could do this"
          hint="The directory, searched by what each company says about itself."
        />
        <div className="px-5 py-4 sm:px-6">
          <TenderMatches tenderId={tender.id} />
        </div>
      </Card>

      <Notice tone="neutral" title="Before you bid">
        This page is a pointer, not the tender. The binding text, the documents
        and the submission channel are on the official notice — and public
        procurement has form requirements that a summary cannot carry.
        {" "}
        <a
          href={tender.source_url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-accent underline underline-offset-4"
        >
          Open the official notice
        </a>
        .
      </Notice>
    </div>
  );
}
