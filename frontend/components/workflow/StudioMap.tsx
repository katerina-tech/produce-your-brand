"use client";

import { useEffect, useRef } from "react";

import "leaflet/dist/leaflet.css";

import type { NearbyStudio } from "@/lib/types";

/**
 * The OpenStreetMap leads, on a map. Complements the list in
 * NearbyStudios.tsx rather than replacing it: a list is what you scan and
 * copy contact details from, a map is what answers "which of these is
 * actually near my office".
 *
 * Only these results can be mapped, and that is a data fact rather than a
 * design choice: an OSM element carries `lat`/`lon`, whereas a
 * `Supplier` record carries only `{city, country, region}` (see
 * app/domain/supplier.py). Putting the scored supplier matches on a map
 * would mean geocoding them first - see the README's Roadmap.
 *
 * Three implementation notes, each avoiding a known Leaflet-in-React trap:
 *
 * - **Plain Leaflet, not react-leaflet.** One dependency instead of two, no
 *   peer-version coupling to React 19, and explicit control of the map
 *   lifecycle - which the next note needs.
 * - **The map is created and destroyed by the same effect.** `reactStrictMode`
 *   double-invokes effects in development, and Leaflet throws "Map container
 *   is already initialized" if a second init hits the same DOM node. Cleaning
 *   up unconditionally is what makes the remount safe; guarding with
 *   "already built, skip" would instead leave the second mount with a dead
 *   container.
 * - **Markers are `divIcon`, not the default icon.** Leaflet's default marker
 *   resolves its PNGs relative to the stylesheet, which bundlers routinely
 *   break (the classic missing-marker bug). A styled div needs no image
 *   assets at all, and it lets the pin carry the brand accent.
 */
export function StudioMap({ studios }: { studios: NearbyStudio[] }) {
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || studios.length === 0) return;

    let map: import("leaflet").Map | null = null;
    let cancelled = false;

    // Imported here rather than at module scope: Leaflet touches `window` on
    // import, so it must not be evaluated during server rendering. The
    // component is also only ever loaded via next/dynamic with ssr: false -
    // this is the second belt.
    void import("leaflet").then((L) => {
      if (cancelled) return;

      map = L.map(container, {
        // A read-only overview: dragging and zooming a small embedded map
        // tends to hijack page scroll more than it helps.
        scrollWheelZoom: false,
        attributionControl: true,
      });

      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        // Required by the OSM tile usage policy, not decoration.
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      }).addTo(map);

      const pin = L.divIcon({
        className: "",
        html:
          '<span style="display:block;width:14px;height:14px;border-radius:50%;' +
          'background:#3240EB;border:2.5px solid #fff;' +
          'box-shadow:0 1px 4px rgba(25,28,35,0.45);"></span>',
        iconSize: [14, 14],
        iconAnchor: [7, 7],
        popupAnchor: [0, -10],
      });

      for (const studio of studios) {
        L.marker([studio.lat, studio.lon], { icon: pin, title: studio.name })
          .addTo(map)
          .bindPopup(popupHtml(studio));
      }

      // Frame every result rather than guessing a centre and zoom. A single
      // result has zero-area bounds, which fitBounds would zoom to maximum,
      // so pad it into something readable.
      const bounds = L.latLngBounds(studios.map((s) => [s.lat, s.lon] as [number, number]));
      map.fitBounds(bounds, { padding: [28, 28], maxZoom: studios.length === 1 ? 14 : 15 });
    });

    return () => {
      cancelled = true;
      map?.remove();
      map = null;
    };
  }, [studios]);

  if (studios.length === 0) return null;

  return (
    <div
      ref={containerRef}
      role="region"
      aria-label="Map of nearby studios found on OpenStreetMap"
      className="h-72 w-full overflow-hidden rounded-lg border border-line"
      // Leaflet paints tiles into absolutely-positioned panes and needs a
      // stacking context it cannot escape; without this the popups can sit
      // above the page's own sticky chrome.
      style={{ isolation: "isolate" }}
    />
  );
}

/** Popup markup. Mirrors the fields the list shows, so the two cannot tell
 * the user different things about the same business. */
function popupHtml(studio: NearbyStudio): string {
  const parts = [
    `<strong>${escapeHtml(studio.name)}</strong>`,
    `<div style="color:#6B6F7A;font-size:11px;margin-top:2px;">${escapeHtml(
      studio.osm_category,
    )}</div>`,
  ];
  if (studio.address) {
    parts.push(`<div style="margin-top:4px;">${escapeHtml(studio.address)}</div>`);
  }
  if (studio.phone) {
    parts.push(`<div style="margin-top:2px;">${escapeHtml(studio.phone)}</div>`);
  }
  if (studio.website) {
    const href = escapeHtml(studio.website);
    parts.push(
      `<a href="${href}" target="_blank" rel="noopener noreferrer" ` +
        `style="display:inline-block;margin-top:4px;color:#3240EB;">Website</a>`,
    );
  }
  return `<div style="font-family:inherit;font-size:12.5px;line-height:1.45;">${parts.join(
    "",
  )}</div>`;
}

/**
 * These strings come from OpenStreetMap, which anyone can edit, and they are
 * injected as popup HTML - so they are untrusted input in exactly the sense
 * ETHICS.md describes, and escaping them is not optional. Leaflet's
 * `bindPopup` accepts an HTML string, which is the whole reason this needs
 * doing by hand instead of relying on React's automatic escaping.
 */
function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
