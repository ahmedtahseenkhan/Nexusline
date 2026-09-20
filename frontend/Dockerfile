FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install

FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
# Node sizes its heap from the container's memory, which on a small server is far
# less than this build needs: it died with "heap out of memory" part-way through,
# leaving no .next/standalone for the runner stage to copy. Give it a fixed heap
# and skip telemetry. A 2 GB host still needs swap — see docs/deployment.md.
ARG NODE_BUILD_HEAP_MB=2048
ENV NODE_OPTIONS=--max-old-space-size=$NODE_BUILD_HEAP_MB
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build && test -d .next/standalone

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
# Standalone output traces only the deps actually used at runtime, so the final
# image needs no full node_modules copy — cuts the image (and every rebuild's
# layer churn) from ~1GB+ down to tens of MB.
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
ENV HOSTNAME=0.0.0.0
ENV PORT=3000
EXPOSE 3000
CMD ["node", "server.js"]
