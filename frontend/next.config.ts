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

  // The directory used to live at /partners, inside the working app. It is its
  // own thing now - its own front door, its own chrome, no sign-in - so it has
  // its own address. Anything already linked or bookmarked still arrives.
  async redirects() {
    return [
      { source: "/partners", destination: "/directory", permanent: true },
      { source: "/partners/:path*", destination: "/directory/:path*", permanent: true },
    ];
  },
};

export default nextConfig;
