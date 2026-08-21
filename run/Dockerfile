# crustify-audit in a container.
#
#   docker build -t crustify-audit run/
#
#   docker run --rm -it --name audit-ippcp \
#       -e ANTHROPIC_API_KEY -e CRUSTIFY_BILLING=api \
#       -e CRUSTIFY_TARGET=/src -e CRUSTIFY_TARGET_REF=marvinte/wrap-2026-08-21 \
#       -v "$PWD:/opt/crustify-audit" \
#       -v /path/to/target-repo:/src:ro \
#       -v audit-ippcp-work:/work \
#       crustify-audit
#
# `CRUSTIFY_TARGET` is a git URL or a path inside the container. A path is the
# common case — an on-disk checkout, bind-mounted READ-ONLY as above — and it
# is still cloned rather than audited in place, so the agent's writes land in
# the volume and the tree you pointed at is untouched.
#
# ONE MOUNT, ONE VOLUME:
#
#   /opt/crustify-audit  Read-WRITE host checkout of this repo, and the only
#                        bind mount. Read-write because an agent that finds a
#                        flaw in the tool should be able to fix it; point it at
#                        a branch you can review.
#   /work                Named volume, and `HOME`. EVERYTHING else lives here:
#                        the target clone under `/work/target`, its
#                        `crustify/audit/` artifacts, the C library the agent
#                        builds, the cargo registry, the provider CLI's config
#                        at `/work/.claude`. Drop the volume and the run is
#                        throwaway — one earlier run built libippcp with nasm
#                        over 25 minutes into the container layer and lost all
#                        of it to `--rm`.
#
#                        What does NOT need the volume is anything installed at
#                        image BUILD time — the Rust toolchain, miri, cmake,
#                        nasm. Those are in the image layer, so every container
#                        has them. The image is the persistence layer for
#                        installs; a dev library every subject needs belongs in
#                        the apt line below, not in a volume.
#
# THE TARGET IS CLONED, NOT AUDITED IN PLACE. `CRUSTIFY_TARGET` names it — a
# git URL, or a path to a checkout you mounted read-only — and
# `CRUSTIFY_TARGET_REF` picks the branch. The entrypoint clones into
# `/work/target` on first run and reuses it afterwards, so a second run against
# the same volume continues the first: the agent reads the advisories and notes
# already there. An on-disk source stays read-only and unmodified; what the run
# produces is read out of the volume rather than found in someone's working
# tree, which matters for an agent running with permissions bypassed.
#
# THE SUBJECT IS A REPOSITORY, not a bare cargo workspace. The crate is the
# root when that is itself a crate, otherwise `crustify/rust`. The entrypoint
# checks both after cloning and exits 2 rather than letting the run discover it
# later.
#
# The repo, because `ub` demands a reproduction that links the audited crate,
# so a wrapper whose `-sys` crates do not build cannot produce an advisory —
# and getting them to build means building the C library, whose sources are in
# the repo beside the Rust.
#
# TARGET-SPECIFIC DEPENDENCIES ARE THE AGENT'S PROBLEM, all of them: the C
# library, and anything else a particular tree needs — a campaign tree's
# manifests reference `ffibox` at an absolute path, and putting it there is the
# same job. The image carries a generic toolchain (cmake, ninja, nasm, yasm,
# autotools, clang, git, curl) so the agent does not start by fetching a build
# tool from source, and stops there. What a given subject needs is not
# something this Dockerfile can know, and pinning it here would date the image
# to one target.
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

# The repository to audit: a git URL, or a path inside the container to a
# checkout mounted read-only. Cloned into /work/target on first run either way.
# A ref is optional; without one the clone's default branch is used.
ENV CRUSTIFY_TARGET= \
    CRUSTIFY_TARGET_REF=

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
      '[ -d /opt/crustify-audit/src/crustify_audit ] || {' \
      '    echo "no checkout at /opt/crustify-audit — mount this repo there" >&2' \
      '    exit 2; }' \
      '# Clone once per volume. A second run against the same volume is a' \
      '# CONTINUATION: the agent reads the advisories and notes the first left.' \
      'target=/work/target' \
      'if [ ! -d "$target/.git" ]; then' \
      '    [ -n "${CRUSTIFY_TARGET:-}" ] || {' \
      '        echo "CRUSTIFY_TARGET is unset — name the repository to audit," >&2' \
      '        echo "as a git URL or a path to a checkout mounted here" >&2' \
      '        exit 2; }' \
      '    case "${CRUSTIFY_TARGET}" in' \
      '        /*) [ -d "${CRUSTIFY_TARGET}/.git" ] || {' \
      '            echo "no git repo at ${CRUSTIFY_TARGET} — mount the checkout" >&2' \
      '            echo "there, e.g. -v /path/to/repo:${CRUSTIFY_TARGET}:ro" >&2' \
      '            exit 2; } ;;' \
      '    esac' \
      '    echo "[crustify-audit] cloning ${CRUSTIFY_TARGET}"' \
      '    git clone ${CRUSTIFY_TARGET_REF:+--branch "${CRUSTIFY_TARGET_REF}"} \' \
      '        "${CRUSTIFY_TARGET}" "$target" || exit 2' \
      'else' \
      '    echo "[crustify-audit] reusing $target ($(git -C "$target" rev-parse --abbrev-ref HEAD))"' \
      'fi' \
      '[ -f "$target/Cargo.toml" ] || [ -f "$target/crustify/rust/Cargo.toml" ] || {' \
      '    echo "no crate in $target — looked for Cargo.toml there and at" >&2' \
      '    echo "crustify/rust/." >&2; exit 2; }' \
      '# Checked here rather than left to the CLI: an agent with no usable auth' \
      '# issues no request and exits 0, which reads as a hunt that found nothing.' \
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
      '    unsafe) exec python3 -m crustify_audit.cli "$target" unsafe "$@" ;;' \
      '    ub) exec python3 -m crustify_audit.cli "$target" ub \' \
      '            --model "${CRUSTIFY_MODEL}" \' \
      '            --billing "${CRUSTIFY_BILLING}" \' \
      '            --timeout "${CRUSTIFY_TIMEOUT}" "$@" ;;' \
      '    *) echo "bad CRUSTIFY_VERB: ${CRUSTIFY_VERB} (unsafe|ub)" >&2; exit 2 ;;' \
      'esac' \
      > /usr/local/bin/crustify-audit-run \
    && chmod +x /usr/local/bin/crustify-audit-run

# The agent starts in the repository it audits; the entrypoint clones it here.
WORKDIR /work
CMD ["crustify-audit-run"]
