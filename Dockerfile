# CS4715: Script based on infer @ docker/master/Dockerfile

FROM debian:trixie-slim AS compilator

LABEL maintainer "Infer team"

# mkdir the man/man1 directory due to Debian bug #863199
RUN apt-get update && \
    mkdir -p /usr/share/man/man1 && \
    apt-get install --yes --no-install-recommends \
      autoconf \
      automake \
      bubblewrap \
      bzip2 \
      cmake \
      curl \
      g++ \
      gcc \
      git \
      libc6-dev \
      libgmp-dev \
      libmpfr-dev \
      libsqlite3-dev \
      sqlite3 \
      make \
      opam \
      openjdk-21-jdk-headless \
      patch \
      patchelf \
      pkg-config \
      python3 \
      rsync\
      unzip \
      xz-utils \
      zlib1g-dev && \
    rm -rf /var/lib/apt/lists/*

# Disable sandboxing
# Without this opam fails to compile OCaml for some reason. We don't need sandboxing inside a Docker container anyway.
RUN opam init --reinit --bare --disable-sandboxing --yes --auto-setup

# Download the latest Infer from git
RUN cd / && \
    git clone --depth 1 --branch v1.3.0 --single-branch https://github.com/facebook/infer/

# Build opam deps first, then clang, then infer. This way if any step
# fails we don't lose the significant amount of work done in the
# previous steps.
RUN cd /infer && ./build-infer.sh --only-setup-opam

# CS4715: Apply custom patch to Infer v1.3.0
COPY infer.patch /tmp/infer.patch

RUN cd /infer && \
    git apply --ignore-space-change /tmp/infer.patch

# Build infer
RUN cd /infer && \
    eval $(opam env) && \
    ./autogen.sh && \
    ./configure --disable-swift-analyzers && \
    cd facebook-clang-plugins/clang && \
    ./src/prepare_clang_src.sh && \
    ./setup.sh

# Generate a release
RUN cd /infer && \
    make install-with-libs \
    BUILD_MODE=opt \
    PATCHELF=patchelf \
    DESTDIR="/infer-release" \
    libdir_relative_to_bindir="../lib"

FROM debian:trixie-slim AS executor

RUN apt-get update && \
    apt-get install --yes --no-install-recommends \
      python3 \
	  python3-pip \
	  #python3-hypothesis \
      python3-sortedcontainers \
      python3-tqdm \
      python3-z3 \
	  build-essential \
      sqlite3 && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install --break-system-packages clize

# Get the infer release
COPY --from=compilator /infer-release/usr/local /infer

# Get examples and fuzzer tooling
COPY examples /root/examples
COPY fuzzer /root/fuzzer

# Alias the Python script into a command we can call from anywhere
RUN printf '%s\n' \
      '#!/bin/sh' \
      'exec python3 /root/fuzzer/main.py "$@"' \
      > /usr/local/bin/infer-z3 && \
    chmod +x /usr/local/bin/infer-z3

# Install infer
ENV PATH /infer/bin:${PATH}

# if called with /infer-host mounted then copy infer there
#RUN if test -d /infer-host; then \
#      cp -av /infer/. /infer-host; \
#    fi
