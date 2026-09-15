import type { NextConfig } from "next";

/**
 * The browser never talks to FastAPI directly. Reads happen in server
 * components and writes go through server actions, so the API base URL stays
 * server-side and no CORS configuration is needed in the browser at all.
 */
const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  typedRoutes: true,
  // Produces a self-contained .next/standalone server (its own minimal
  // node_modules) so the deploy image doesn't need the full node_modules
  // tree copied in. Only affects `next build` output, not `next dev`.
  output: "standalone",

  // This section used to live at /partners inside the working app, and briefly
  // at /directory. It is "Companies" now, because that is what a person
  // looking for a print shop would click. Both old addresses still arrive.
  async redirects() {
    return [
      { source: "/partners", destination: "/companies", permanent: true },
      { source: "/partners/:path*", destination: "/companies/:path*", permanent: true },
      { source: "/directory", destination: "/companies", permanent: true },
      { source: "/directory/:path*", destination: "/companies/:path*", permanent: true },
    ];
  },
};

export default nextConfig;
