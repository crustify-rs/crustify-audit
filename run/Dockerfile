# crustify-audit in a container.
#
#   docker build -t crustify-audit run/
#
#   docker run --rm -it --name audit-ippcp \
#       -e ANTHROPIC_API_KEY -e CRUSTIFY_BILLING=api \
#       -v "$PWD:/opt/crustify-audit" \
#       -v /path/to/target-repo:/subject \
#       -v audit-ippcp-work:/work \
#       -v /path/to/ffibox:/opt/ffibox \
#       crustify-audit
#
# THREE MOUNTS, THREE LIFETIMES:
#
#   /opt/crustify-audit  Read-WRITE host checkout of this repo. Read-write
#                        because an agent that finds a flaw in the tool should
#                        be able to fix it; point it at a branch you can review.
#   /subject             The REPOSITORY under audit, read-WRITE: the agent
#                        writes its advisories, notes and reproductions to
#                        `<subject>/crustify/audit/`. A bind mount, so those
#                        land on the host and survive `--rm`.
#   /work                Named volume, and `HOME`. Everything the agent does
#                        OUTSIDE the artifact tree lives here — a C library it
#                        cloned and built, the cargo registry, the CLI's own
#                        config under `/work/.claude`. Without it that work is
#                        in the container layer and `--rm` destroys it: one run
#                        spent 25 minutes building libippcp with nasm and lost
#                        all of it on exit.
#
#                        What does NOT need this volume is anything installed
#                        at image BUILD time — the Rust toolchain, miri, cmake,
#                        nasm. Those are in the image layer, so every container
#                        has them. The image is the persistence layer for
#                        installs; a dev library a subject needs every time
#                        belongs in the apt line below, not in a volume.
#
# THE SUBJECT IS A REPOSITORY, not a bare cargo workspace. The crate is the
# root when that is itself a crate, otherwise `crustify/rust`. The entrypoint
# checks both and exits 2 rather than letting the run discover it later.
#
# The repo, because `ub` demands a reproduction that links the audited crate,
# so a wrapper whose `-sys` crates do not build cannot produce an advisory —
# and getting them to build means building the C library, whose sources are in
# the repo beside the Rust. Mounting `crustify/rust` alone cut an agent off
# from them and it cloned the C project from GitHub to get them back.
#
# A CAMPAIGN TREE NEEDS FFIBOX AT /opt/ffibox. crustify-cli's scaffold writes
# `ffibox = { path = "/opt/ffibox" }` into every crate it generates — an
# absolute path, which `cli-config.json` cannot override — so without that
# mount cargo cannot even load the manifests, and the failure arrives as an
# unloadable workspace member rather than a missing dependency. The entrypoint
# checks for it when the crate resolves to `crustify/rust`.
#
# HOW to build that library is still the agent's problem. The image carries a
# generic toolchain (cmake, ninja, nasm, yasm, autotools, clang) so it does not
# start by fetching a build tool from source.
#
# SUBSCRIPTION AUTH needs the CLI's stored login, which lives under `HOME`:
# mount it at `/work/.claude` (claude) or `/work/.codex` (codex). Copy the
# credential file rather than binding your real config — the agent runs with
# permissions bypassed.

FROM debian:12-slim

ARG PYTHON_VERSION=3.13
# Both backends by default; either can be dropped from the image.
ARG INSTALL_CLAUDE=1
ARG INSTALL_CODEX=1

ENV DEBIAN_FRONTEND=noninteractive \
    PATH=/opt/venv/bin:/root/.cargo/bin:/root/.local/bin:$PATH \
    CARGO_TERM_COLOR=never \
    # bindgen dlopens libclang at run time, and the versioned package ships it
    # as libclang-19.so.1 rather than the libclang.so.1 clang-sys looks for.
    LIBCLANG_PATH=/usr/lib/llvm-19/lib \
    # Claude Code refuses --dangerously-skip-permissions as root without this.
    IS_SANDBOX=1

# 1. A generic C toolchain, plus the assemblers a crypto library expects.
#    `nasm` and `yasm` are here because a subject that needs one otherwise
#    costs the agent a source build before it can even start.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl git unzip xz-utils pkg-config file \
        build-essential clang-19 lld-19 cmake ninja-build \
        nasm yasm autoconf automake libtool m4 python3 \
    && rm -rf /var/lib/apt/lists/* \
    && ln -s clang-19   /usr/bin/clang \
    && ln -s clang++-19 /usr/bin/clang++ \
    && ln -s ld.lld-19  /usr/bin/ld.lld

# 2. Python. crustify-audit needs >= 3.13; bookworm ships 3.11.
RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && uv python install "${PYTHON_VERSION}" \
    && uv venv --python "${PYTHON_VERSION}" /opt/venv

# 3. Rust. Nightly with `rustc-dev` and `llvm-tools` is what the metrics driver
#    is built against; `miri` is what the agent checks its reproductions with,
#    and installing it here saves every run the download.
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
      | sh -s -- -y --default-toolchain stable --component clippy \
    && rustup toolchain install nightly \
         --component rustc-dev --component llvm-tools --component miri \
    && cargo +nightly miri --version

# 4. Agent backends.
RUN if [ "${INSTALL_CLAUDE}" = "1" ]; then \
        curl -fsSL https://claude.ai/install.sh | bash; \
    fi \
    && if [ "${INSTALL_CODEX}" = "1" ]; then \
        curl -fsSL https://chatgpt.com/codex/install.sh | sh; \
    fi

# 5. The tool comes from the MOUNT, not from the image. It declares no
#    third-party dependencies, so there is nothing to install ahead of time and
#    a clone would buy only the ability to run unmounted — at the cost of
#    baking in a revision and needing credentials for a private repo at build
#    time. `PYTHONPATH` is what makes the mounted checkout importable.
#
#    The metrics driver is not prebuilt either: its source is under the same
#    mount, so only a build done at run time matches the checkout driving the
#    run. `driver.py` builds it on first use into the checkout's own target/,
#    which persists on the host.
ENV PYTHONPATH=/opt/crustify-audit/src

# Which verb to run: `unsafe` (deterministic, no LLM) or `ub` (agentic, spends).
ENV CRUSTIFY_VERB=ub

# Drives `ub` only. `<provider>/<model>`; the prefix selects the backend.
ENV CRUSTIFY_MODEL=anthropic/claude-opus-5

# How the provider CLI authenticates. Neither CLI uses a key from the
# environment on its own, so this is not decoration: `api` adds `--bare`
# (claude) or an env-key provider block (codex). `subscription` needs the CLI's
# stored login mounted under HOME.
ENV CRUSTIFY_BILLING=subscription

# Wall-clock BUDGET in minutes for the whole run, not a per-agent leash:
# agents are spawned one after another until it is reached and none is killed,
# so the run overshoots by however long the last one takes. 0 runs one agent.
ENV CRUSTIFY_TIMEOUT=60

# HOME is the volume. Everything the agent fetches, clones or builds outside
# the artifact tree lands here and survives `--rm` — including the provider
# CLI's own config, which is why credentials mount at /work/.claude.
#
# RUSTUP_HOME is pinned back to /root, because rustup resolves it from HOME:
# with HOME on an empty volume, `cargo +nightly` finds no toolchain, silently
# downloads a fresh nightly WITHOUT the components this image installs, and the
# agent loses miri without being told why. The toolchain itself needs no volume
# — it is installed at image BUILD time, so it is in the image layer and
# present in every container.
#
# CARGO_HOME does go on the volume, for the registry: the proxies are found on
# PATH and the toolchain through RUSTUP_HOME, so all that moves is the crate
# cache, which a subject's build otherwise re-downloads every run.
ENV HOME=/work \
    RUSTUP_HOME=/root/.rustup \
    CARGO_HOME=/work/.cargo
RUN mkdir -p /work

RUN printf '%s\n' '#!/usr/bin/env bash' 'set -euo pipefail' \
      '# The subject must hold a crate, at the root or under crustify/rust —' \
      '# checking here costs one exit instead of a confusing failure later.' \
      '[ -d /opt/crustify-audit/src/crustify_audit ] || {' \
      '    echo "no checkout at /opt/crustify-audit — mount this repo there" >&2' \
      '    exit 2; }' \
      '[ -f /subject/Cargo.toml ] || [ -f /subject/crustify/rust/Cargo.toml ] || {' \
      '    echo "no crate at /subject — looked for Cargo.toml there and at" >&2' \
      '    echo "crustify/rust/. Mount the target REPOSITORY there." >&2; exit 2; }' \
      '# Checked here rather than left to the CLI: an agent with no usable auth' \
      '# issues no request and exits 0, which reads as a hunt that found nothing.' \
      '# A campaign tree hard-codes ffibox at this path; see the header.' \
      'if [ ! -f /subject/Cargo.toml ] && [ ! -d /opt/ffibox ]; then' \
      '    echo "/subject is a campaign tree (crate at crustify/rust) and its" >&2' \
      '    echo "manifests reference /opt/ffibox — mount an ffibox checkout" >&2' \
      '    echo "there, or cargo cannot load the workspace." >&2; exit 2' \
      'fi' \
      'case "${CRUSTIFY_BILLING}" in' \
      '    subscription) ;;' \
      '    api)' \
      '        case "${CRUSTIFY_MODEL%%/*}" in' \
      '        anthropic) [ -n "${ANTHROPIC_API_KEY:-}" ] || {' \
      '            echo "CRUSTIFY_BILLING=api needs ANTHROPIC_API_KEY" >&2; exit 2; } ;;' \
      '        openai)    [ -n "${OPENAI_API_KEY:-}" ] || {' \
      '            echo "CRUSTIFY_BILLING=api needs OPENAI_API_KEY" >&2; exit 2; } ;;' \
      '        esac ;;' \
      '    *) echo "bad CRUSTIFY_BILLING: ${CRUSTIFY_BILLING}" >&2; exit 2 ;;' \
      'esac' \
      'case "${CRUSTIFY_VERB}" in' \
      '    unsafe) exec python3 -m crustify_audit.cli /subject unsafe "$@" ;;' \
      '    ub) exec python3 -m crustify_audit.cli /subject ub \' \
      '            --model "${CRUSTIFY_MODEL}" \' \
      '            --billing "${CRUSTIFY_BILLING}" \' \
      '            --timeout "${CRUSTIFY_TIMEOUT}" "$@" ;;' \
      '    *) echo "bad CRUSTIFY_VERB: ${CRUSTIFY_VERB} (unsafe|ub)" >&2; exit 2 ;;' \
      'esac' \
      > /usr/local/bin/crustify-audit-run \
    && chmod +x /usr/local/bin/crustify-audit-run

# The agent starts in the workspace it audits.
WORKDIR /subject
CMD ["crustify-audit-run"]
