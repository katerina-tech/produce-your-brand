"use client";

import { useEffect, useRef } from "react";

import "leaflet/dist/leaflet.css";

import type { Partner } from "@/lib/types";

/**
 * The directory, on a map of Berlin.
 *
 * A list answers "who is there"; a map answers "who is near me", and for a
 * pallet of yoga mats that is the question that decides. Every one of these
 * records has coordinates — that is why this is possible here and not for the
 * scored suppliers, whose records carry only `{city, country, region}`.
 *
 * Follows StudioMap.tsx deliberately rather than sharing a component with it:
 * the two show different types, and the honest way to keep a `Partner` and a
 * `NearbyStudio` from blurring is to keep the code that renders them apart.
 * The three Leaflet traps it avoids are the same three, and for the same
 * reasons — plain Leaflet over react-leaflet, create and destroy in one effect
 * so React's double-invoked effects cannot hit an initialised container, and
 * `divIcon` markers so no bundler can break a marker image.
 *
 * Confirmed companies get a filled pin and unconfirmed ones a hollow pin, so
 * the map carries the same distinction the list does. A map that showed them
 * alike would quietly undo the only fact here that a person established.
 */
export function PartnerMap({ partners }: { partners: Partner[] }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const placed = partners.filter(
    (partner): partner is Partner & { lat: number; lon: number } =>
      partner.lat !== null && partner.lon !== null,
  );

  useEffect(() => {
    const container = containerRef.current;
    if (!container || placed.length === 0) return;

    let map: import("leaflet").Map | null = null;
    let cancelled = false;

    // Imported here, never at module scope: Leaflet touches `window` on import
    // and must not be evaluated during server rendering. The dynamic import
    // with ssr:false at the call site is the second belt.
    void import("leaflet").then((L) => {
      if (cancelled) return;

      map = L.map(container, { scrollWheelZoom: false, attributionControl: true });

      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        // Required by the OSM tile usage policy, not decoration.
        attribution:
          '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      }).addTo(map);

      const pin = (confirmed: boolean) =>
        L.divIcon({
          className: "",
          html:
            '<span style="display:block;width:13px;height:13px;border-radius:50%;' +
            `background:${confirmed ? "#3240EB" : "#fff"};` +
            `border:2.5px solid ${confirmed ? "#fff" : "#3240EB"};` +
            'box-shadow:0 1px 4px rgba(25,28,35,0.4);"></span>',
          iconSize: [13, 13],
          iconAnchor: [6.5, 6.5],
          popupAnchor: [0, -10],
        });

      for (const partner of placed) {
        L.marker([partner.lat, partner.lon], {
          icon: pin(partner.verified),
          title: partner.name,
        })
          .addTo(map)
          .bindPopup(popupHtml(partner));
      }

      // Frame what is actually shown rather than hardcoding a view of Berlin:
      // filter to Pankow and the map should go to Pankow. A single result has
      // zero-area bounds, which fitBounds would zoom to maximum.
      const bounds = L.latLngBounds(
        placed.map((partner) => [partner.lat, partner.lon] as [number, number]),
      );
      map.fitBounds(bounds, { padding: [30, 30], maxZoom: placed.length === 1 ? 15 : 16 });
    });

    return () => {
      cancelled = true;
      map?.remove();
      map = null;
    };
  }, [placed]);

  if (placed.length === 0) return null;

  return (
    <div
      ref={containerRef}
      role="region"
      aria-label="Map of the production companies in this directory"
      className="h-[26rem] w-full overflow-hidden rounded-lg border border-line"
      // Leaflet paints into absolutely-positioned panes and needs a stacking
      // context it cannot escape, or its popups sit above the page's chrome.
      style={{ isolation: "isolate" }}
    />
  );
}

/** Popup markup. Mirrors what the list row shows, so the map and the list
 * cannot tell somebody different things about the same company. */
function popupHtml(partner: Partner): string {
  const parts = [`<strong>${escapeHtml(partner.name)}</strong>`];

  const where = partner.district ?? partner.city;
  parts.push(
    `<div style="color:#6B6F7A;font-size:11px;margin-top:2px;">${escapeHtml(where)}` +
      (partner.verified ? " · confirmed" : "") +
      "</div>",
  );
  if (partner.address) {
    parts.push(`<div style="margin-top:4px;">${escapeHtml(partner.address)}</div>`);
  }
  if (partner.email) {
    parts.push(
      `<a href="mailto:${escapeHtml(partner.email)}" ` +
        `style="display:inline-block;margin-top:4px;color:#3240EB;">${escapeHtml(
          partner.email,
        )}</a>`,
    );
  }
  parts.push(
    `<div style="margin-top:5px;"><a href="/companies/${escapeHtml(partner.id)}" ` +
      `style="color:#3240EB;">What they say they do →</a></div>`,
  );
  return `<div style="font-family:inherit;font-size:12.5px;line-height:1.45;">${parts.join(
    "",
  )}</div>`;
}

/** Leaflet popups take an HTML string, so every value goes through this.
 * These names and addresses come from a public map anybody can edit. */
function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
