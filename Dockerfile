# syntax=docker/dockerfile:1.7

ARG UBUNTU_IMAGE=ubuntu:24.04
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.9.28

FROM ${UBUNTU_IMAGE} AS tshark-build

ARG WIRESHARK_VERSION=4.6.8
ARG WIRESHARK_SHA256=c0f1ccf217bc0d3b51a9c03ea178b0f7df682e475da26a2d21cd4a1bdd9579d0

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        bison \
        build-essential \
        ca-certificates \
        cmake \
        curl \
        flex \
        libc-ares-dev \
        libgcrypt20-dev \
        libglib2.0-dev \
        libgnutls28-dev \
        liblz4-dev \
        libmaxminddb-dev \
        libnghttp2-dev \
        libpcap-dev \
        libpcre2-dev \
        libsnappy-dev \
        libspeexdsp-dev \
        libxml2-dev \
        libzstd-dev \
        ninja-build \
        pkg-config \
        python3 \
        xz-utils \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

RUN curl --fail --location --proto '=https' --tlsv1.2 \
        --output wireshark.tar.xz \
        "https://www.wireshark.org/download/src/wireshark-${WIRESHARK_VERSION}.tar.xz" \
    && echo "${WIRESHARK_SHA256}  wireshark.tar.xz" | sha256sum --check - \
    && tar --extract --file wireshark.tar.xz \
    && cmake \
        -S "wireshark-${WIRESHARK_VERSION}" \
        -B out \
        -G Ninja \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX=/opt/wireshark \
        -DBUILD_wireshark=OFF \
        -DBUILD_stratoshark=OFF \
        -DBUILD_tshark=ON \
        -DBUILD_dumpcap=OFF \
        -DBUILD_rawshark=OFF \
        -DBUILD_text2pcap=OFF \
        -DBUILD_mergecap=OFF \
        -DBUILD_reordercap=OFF \
        -DBUILD_editcap=OFF \
        -DBUILD_capinfos=OFF \
        -DBUILD_captype=OFF \
        -DBUILD_randpkt=OFF \
        -DBUILD_androiddump=OFF \
        -DBUILD_sshdump=OFF \
        -DBUILD_ciscodump=OFF \
        -DBUILD_dpauxmon=OFF \
        -DBUILD_randpktdump=OFF \
        -DENABLE_PLUGINS=OFF \
    && cmake --build out --parallel --target tshark \
    && cmake --install out \
    && /opt/wireshark/bin/tshark --version | grep --fixed-strings \
        "TShark (Wireshark) ${WIRESHARK_VERSION}"

FROM ${UV_IMAGE} AS uv-bin

FROM ${UBUNTU_IMAGE} AS python-build

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates python3.12 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv-bin /uv /usr/local/bin/uv

WORKDIR /workspace

COPY pyproject.toml uv.lock README.md ./
COPY src ./src

RUN uv build --frozen --wheel --out-dir /wheels

FROM ${UBUNTU_IMAGE} AS runtime

ARG WIRESHARK_VERSION=4.6.8

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PATH=/opt/dfilterforge/bin:/opt/wireshark/bin:${PATH} \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=UTC \
    WIRESHARK_CONFIG_DIR=/opt/dfilterforge-profile

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        ca-certificates \
        libc-ares2 \
        libgcrypt20 \
        libglib2.0-0t64 \
        libgnutls30t64 \
        liblz4-1 \
        libmaxminddb0 \
        libnghttp2-14t64 \
        libpcap0.8t64 \
        libpcre2-8-0 \
        libsnappy1v5 \
        libspeexdsp1 \
        libxml2 \
        libzstd1 \
        python3.12 \
        python3.12-venv \
        tzdata \
        zlib1g \
    && rm -rf /var/lib/apt/lists/* \
    && python3.12 -m venv /opt/dfilterforge \
    && groupadd --gid 10001 dfilterforge \
    && useradd --uid 10001 --gid 10001 --no-create-home \
        --home-dir /nonexistent --shell /usr/sbin/nologin dfilterforge \
    && install --directory --owner=10001 --group=10001 \
        /opt/dfilterforge-profile /workspace /workspace/artifacts \
    && printf '%s\n' '/opt/wireshark/lib' \
        >/etc/ld.so.conf.d/wireshark.conf

COPY --from=tshark-build /opt/wireshark /opt/wireshark
COPY --from=python-build /wheels /wheels

RUN ldconfig \
    && /opt/dfilterforge/bin/pip install --no-cache-dir /wheels/*.whl \
    && rm -rf /wheels \
    && tshark --version | grep --fixed-strings \
        "TShark (Wireshark) ${WIRESHARK_VERSION}" \
    && dfilterforge --version

WORKDIR /workspace
USER 10001:10001

ENTRYPOINT ["dfilterforge"]
CMD ["doctor"]

FROM runtime AS test

USER root
COPY --from=uv-bin /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY tests ./tests

RUN uv sync --frozen --extra dev

USER 10001:10001
ENTRYPOINT ["uv", "run", "--frozen", "--extra", "dev"]
CMD ["pytest", "--cov=dfilterforge", "--cov-branch"]

FROM test AS dev

CMD ["python", "-m", "dfilterforge", "doctor"]
