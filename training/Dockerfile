# syntax=docker/dockerfile:1.7

# The training image. By default it carries CPU torch, for the smoke and the
# parity test, which compose runs with no network (profile train). Built
# with --build-arg TORCH_EXTRA=cu126 it is the same image for a CUDA host;
# training/README.md has the docker run line. The build fetches only the
# pinned tokenizer and tiny smoke model into /opt/hf; the real run
# downloads the pinned Qwen/Qwen3-1.7B weights when it starts.

ARG UBUNTU_IMAGE=ubuntu:24.04
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.9.28

FROM ${UV_IMAGE} AS uv-bin

FROM ${UBUNTU_IMAGE} AS env

ARG TORCH_EXTRA=cpu

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=UTC \
    UV_PROJECT_ENVIRONMENT=/opt/train \
    UV_PYTHON_DOWNLOADS=never \
    UV_CACHE_DIR=/tmp/uv-cache \
    HF_HOME=/opt/hf \
    HOME=/tmp \
    PATH=/opt/train/bin:${PATH}

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        ca-certificates \
        python3.12 \
        python3.12-venv \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 dfilterforge \
    && useradd --uid 10001 --gid 10001 --no-create-home \
        --home-dir /nonexistent --shell /usr/sbin/nologin dfilterforge

COPY --from=uv-bin /uv /usr/local/bin/uv

WORKDIR /workspace

COPY training/pyproject.toml training/uv.lock ./training/

RUN uv sync --project training --frozen --extra "${TORCH_EXTRA}" \
        --python python3.12 \
    && rm -rf /tmp/uv-cache

FROM env AS train

COPY training/train_sft.py ./training/
# The same loaders the run uses, so the cache holds exactly what they read.
RUN python -c "import sys; sys.path.insert(0, 'training'); \
import train_sft; train_sft.load_tokenizer(); train_sft.load_model(smoke=True)"

COPY training/tests ./training/tests
COPY data/train/v1/sft.jsonl.gz data/train/v1/sft-manifest.json \
    ./data/train/v1/

USER 10001:10001

CMD ["python", "training/train_sft.py", "--help"]
