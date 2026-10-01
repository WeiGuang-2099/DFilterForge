# syntax=docker/dockerfile:1.7

# Builds the static site from committed files only. Stages:
#   export  runs scripts/export_web_data.py over the committed evidence with
#           no network;
#   data    holds only the exported JSON, so `--target data --output
#           type=local,dest=apps/web/data` gives `next dev` the same data;
#   deps    installs the locked workspace packages;
#   build   runs `next build` with no network;
#   out     holds only the static export, for `--output type=local`;
#   site    serves out/ under the base path with scripts/serve.mjs.
#
# From the repository root (Git Bash):
#   MSYS_NO_PATHCONV=1 docker build -f apps/web/Dockerfile --target out \
#     --build-arg SOURCE_COMMIT=$(git rev-parse HEAD) \
#     --output type=local,dest=apps/web/out .
#
# Base images are pinned by tag; digest pins come with the Pages workflow.

ARG PYTHON_IMAGE=python:3.12.14-slim-bookworm
ARG NODE_IMAGE=node:20.20.2-bookworm-slim
# The URL prefix Next inlines at build time and serve.mjs serves under. A
# host that serves the site at the domain root passes an empty value.
ARG PAGES_BASE_PATH=/DFilterForge

FROM ${PYTHON_IMAGE} AS export

WORKDIR /src

COPY scripts/export_web_data.py ./scripts/export_web_data.py
COPY src/dfilterforge/held_out_freeze.json ./src/dfilterforge/held_out_freeze.json
COPY docs/ablations/evidence ./docs/ablations/evidence
COPY docs/decisions/evidence ./docs/decisions/evidence
# Read only to check that every registered test run is named in the note.
COPY docs/decisions/model-bakeoff.md ./docs/decisions/model-bakeoff.md
COPY docs/results ./docs/results

RUN install --directory --owner=nobody --group=nogroup /data

USER nobody

# The commit the data is exported from; site permalinks name it, so the
# build refuses to guess one.
ARG SOURCE_COMMIT

RUN --network=none \
    if [ -z "${SOURCE_COMMIT}" ]; then \
        echo 'Pass --build-arg SOURCE_COMMIT=$(git rev-parse HEAD).' >&2; \
        exit 2; \
    fi \
    && python -I -B scripts/export_web_data.py \
        --repo /src --out /data --source-commit "${SOURCE_COMMIT}"

FROM scratch AS data

COPY --from=export /data /

FROM ${NODE_IMAGE} AS deps

ENV PNPM_HOME=/pnpm
ENV PATH=${PNPM_HOME}:${PATH}

RUN corepack enable \
    && corepack prepare pnpm@10.34.5 --activate

WORKDIR /workspace

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json ./apps/web/package.json

RUN pnpm install --frozen-lockfile

FROM deps AS build

ARG PAGES_BASE_PATH

ENV NEXT_TELEMETRY_DISABLED=1 \
    PAGES_BASE_PATH=${PAGES_BASE_PATH}

COPY apps/web ./apps/web
COPY --from=data / ./apps/web/data/

RUN --network=none pnpm --filter @dfilterforge/web build

FROM scratch AS out

COPY --from=build /workspace/apps/web/out /

FROM ${NODE_IMAGE} AS site

ARG PAGES_BASE_PATH

ENV HOST=0.0.0.0 \
    NODE_ENV=production \
    PAGES_BASE_PATH=${PAGES_BASE_PATH} \
    PORT=3000

RUN groupadd --gid 10001 dfilterforge \
    && useradd --uid 10001 --gid 10001 --no-create-home \
        --home-dir /nonexistent --shell /usr/sbin/nologin dfilterforge

WORKDIR /app

# Owned by root and read-only to the server's user.
COPY --from=build /workspace/apps/web/scripts/base_path.mjs \
    /workspace/apps/web/scripts/serve.mjs ./scripts/
COPY --from=build /workspace/apps/web/out ./out

USER 10001:10001
EXPOSE 3000

CMD ["node", "scripts/serve.mjs"]
