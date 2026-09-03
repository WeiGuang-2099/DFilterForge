# syntax=docker/dockerfile:1.7

ARG NODE_IMAGE=node:20.20.2-bookworm-slim

FROM ${NODE_IMAGE} AS dependencies

ENV PNPM_HOME=/pnpm
ENV PATH=${PNPM_HOME}:${PATH}

RUN corepack enable \
    && corepack prepare pnpm@10.34.5 --activate

WORKDIR /workspace

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json ./apps/web/package.json

RUN pnpm install --frozen-lockfile

FROM dependencies AS build

COPY apps/web ./apps/web

RUN pnpm --filter @dfilterforge/web build

FROM ${NODE_IMAGE} AS runtime

ENV HOSTNAME=0.0.0.0 \
    NODE_ENV=production \
    PORT=3000

RUN groupadd --gid 10001 dfilterforge \
    && useradd --uid 10001 --gid 10001 --no-create-home \
        --home-dir /nonexistent --shell /usr/sbin/nologin dfilterforge

WORKDIR /app

COPY --from=build --chown=10001:10001 \
    /workspace/apps/web/.next/standalone ./
COPY --from=build --chown=10001:10001 \
    /workspace/apps/web/.next/static ./apps/web/.next/static

USER 10001:10001
EXPOSE 3000

CMD ["node", "apps/web/server.js"]
