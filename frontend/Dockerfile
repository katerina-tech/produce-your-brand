# Multi-stage build for the Next.js frontend. Produces a small runtime image
# using `output: "standalone"` (see next.config.ts) - the final stage ships
# only the compiled server and its own minimal node_modules, not the full
# dev dependency tree.
#
# Build context is the `frontend/` directory (set as this service's root
# directory in Railway).

FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# The API base URL is read server-side at request time (see lib/api.ts), not
# baked in at build time, so no build-time env vars are needed here.
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production

COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

EXPOSE 3000
# Next's standalone server.js reads $PORT itself; Railway injects it.
CMD ["node", "server.js"]
