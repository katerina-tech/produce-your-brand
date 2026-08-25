"use client";

import { useState, useTransition } from "react";

import { Button, Card, CardHeader, Notice } from "@/components/ui";
import { loadNearbyStudios } from "@/lib/actions";
import type { NearbyStudio } from "@/lib/types";

/**
 * A live, unscored complement to the partner matches above - real businesses
 * found on OpenStreetMap for the confirmed method, not ranked or vetted the
 * way `MatchList` ranks a supplier record. Collapsed by default and fetched
 * only on request: this queries a shared public service (Overpass), and a
 * project's confirmed method rarely changes, so there is no reason to call it
 * on every page load the way the supplier matches above are already loaded.
 */
export function NearbyStudios({ projectId }: { projectId: string }) {
  const [open, setOpen] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [studios, setStudios] = useState<NearbyStudio[]>([]);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  const reveal = () => {
    setOpen(true);
    if (loaded) return;
    startTransition(async () => {
      const result = await loadNearbyStudios(projectId);
      if (result.error) {
        setError(result.error);
      } else {
        setStudios(result.studios ?? []);
        setNote(result.note ?? null);
      }
      setLoaded(true);
    });
  };

  if (!open) {
    return (
      <button
        type="button"
        onClick={reveal}
        className="text-sm text-ink-soft underline decoration-line-strong underline-offset-4 transition-colors hover:text-ink"
      >
        Also see nearby studios in Berlin on OpenStreetMap →
      </button>
    );
  }

  return (
    <Card>
      <CardHeader
        title="Nearby studios · OpenStreetMap"
        hint="Berlin only for now - more cities as coverage grows. Unverified leads, not scored or vetted like the matches above: contact them yourself to confirm they can do this job."
      />
      <div className="px-5 py-4 sm:px-6">
        {pending ? (
          <p className="text-sm text-ink-soft">Searching OpenStreetMap…</p>
        ) : error ? (
          <Notice tone="warning">{error}</Notice>
        ) : studios.length === 0 ? (
          <p className="text-sm text-ink-soft">{note ?? "No nearby businesses found for this method."}</p>
        ) : (
          <ul className="space-y-4">
            {studios.map((studio) => (
              <li key={studio.osm_id} className="border-b border-line pb-3 last:border-0 last:pb-0">
                <p className="text-[15px] font-semibold">{studio.name}</p>
                <p className="mt-0.5 text-xs text-ink-muted">{studio.osm_category}</p>
                {studio.address ? (
                  <p className="mt-1 text-sm text-ink-soft">{studio.address}</p>
                ) : null}
                <p className="mt-1 flex flex-wrap gap-3 text-sm">
                  {studio.website ? (
                    <a
                      href={studio.website}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-ink underline decoration-line-strong underline-offset-4 hover:no-underline"
                    >
                      Website
                    </a>
                  ) : null}
                  {studio.phone ? <span className="text-ink-soft">{studio.phone}</span> : null}
                </p>
              </li>
            ))}
          </ul>
        )}
      </div>
      <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-5 py-3 sm:px-6">
        <p className="text-xs text-ink-muted">
          This is a prototype - unlike the synthetic partner matches above,
          these are real businesses, and nothing here contacts them. Reaching
          out is a future phase; for now this is just a starting point for
          your own outreach.
        </p>
        <Button tone="quiet" onClick={() => setOpen(false)}>
          Hide
        </Button>
      </footer>
    </Card>
  );
}
