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
};

export default nextConfig;
