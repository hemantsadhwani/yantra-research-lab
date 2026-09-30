# Next.js portal — multi-stage build to a small, non-root runtime image.
# Build context is the frontend/ directory:
#     docker build -t yantra-frontend --build-arg NEXT_PUBLIC_BACKEND_URL=http://localhost:8000 frontend/
# NEXT_PUBLIC_* values are inlined at build time by Next.js, so the backend URL is a build arg.
# The public demo still deploys to Vercel; this image is for Compose / Kubernetes (deploy/k8s).

FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM node:20-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ARG NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
ENV NEXT_PUBLIC_BACKEND_URL=$NEXT_PUBLIC_BACKEND_URL \
    NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:20-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0 \
    NEXT_TELEMETRY_DISABLED=1
# Numeric uid/gid so Kubernetes can verify runAsNonRoot (a named user cannot be checked).
RUN addgroup -S -g 10001 app && adduser -S -u 10001 -G app app
COPY --from=build /app/public ./public
COPY --from=build --chown=app:app /app/.next/standalone ./
COPY --from=build --chown=app:app /app/.next/static ./.next/static
USER app
EXPOSE 3000
CMD ["node", "server.js"]
