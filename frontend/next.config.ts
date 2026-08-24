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
};

export default nextConfig;
