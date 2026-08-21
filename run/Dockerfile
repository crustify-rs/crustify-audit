# crustify-audit in a container. The run starts with the container.
#
#   docker build -t crustify-audit run/
#   mkdir -p ~/.claude-audit && cp ~/.claude/.credentials.json ~/.claude-audit/
#
#   docker run -d --name audit-ippcp \
#       -v "$PWD:/opt/crustify-audit" \
#       -v /path/to/target-repo:/target \
#       -v ~/.claude-audit:/work/.claude \
#       -v audit-ippcp-work:/work \
#       crustify-audit
#
#   /target              The repository to audit, read-write, on whatever branch
#                        the host has checked out — there is no ref to pass and
#                        no clone. The agent's `crustify/audit/` artifacts land
#                        in that working tree, and it runs with permissions
#                        bypassed, so point it at a checkout you can review.
#                        A repository, not a bare workspace: the crate is the
#                        root or `crustify/rust`, and `ub` needs the C sources
#                        beside it to build a reproduction that links the crate.
#   /opt/crustify-audit  This repo, read-write so an agent that finds a flaw in
#                        the tool can fix it.
#   /work/.claude        A DIRECTORY holding a COPY of the OAuth token
#                        `subscription` billing spends against. Not your real
#                        `~/.claude`, which holds every project's history; not
#                        the file alone, because the CLI refreshes the token by
#                        rename and a rename across a single-file bind mount
#                        fails. Re-copy when a run fails to authenticate. Codex
#                        is `/work/.codex` with `auth.json`.
#   /work                Named volume, and `HOME`: the C library the agent
#                        builds, the cargo registry. Not the audit artifacts —
#                        those are in the target checkout. Nothing installed at
#                        image BUILD time needs it; that is in the image layer.
#
# Target-specific dependencies are the agent's, all of them — the C library, a
# campaign tree's `ffibox`. The image carries a generic toolchain so the agent
# does not start by building one, and stops there: what a subject needs is not
# something this file can know, and pinning it dates the image to one target.

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

# A generic C toolchain. `nasm`/`yasm` because a crypto subject needing one
# otherwise costs the agent a source build before it can start.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl git unzip xz-utils pkg-config file \
        build-essential clang-19 lld-19 cmake ninja-build \
        nasm yasm autoconf automake libtool m4 python3 \
    && rm -rf /var/lib/apt/lists/* \
    && ln -s clang-19   /usr/bin/clang \
    && ln -s clang++-19 /usr/bin/clang++ \
    && ln -s ld.lld-19  /usr/bin/ld.lld

# crustify-audit needs Python >= 3.13; bookworm ships 3.11.
RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && uv python install "${PYTHON_VERSION}" \
    && uv venv --python "${PYTHON_VERSION}" /opt/venv

# Nightly with `rustc-dev` and `llvm-tools` is what the metrics driver is built
# against; `miri` is what the agent checks its reproductions with.
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
      | sh -s -- -y --default-toolchain stable --component clippy \
    && rustup toolchain install nightly \
         --component rustc-dev --component llvm-tools --component miri \
    && cargo +nightly miri --version

RUN if [ "${INSTALL_CLAUDE}" = "1" ]; then \
        curl -fsSL https://claude.ai/install.sh | bash; \
    fi \
    && if [ "${INSTALL_CODEX}" = "1" ]; then \
        curl -fsSL https://chatgpt.com/codex/install.sh | sh; \
    fi

# The tool comes from the MOUNT, not the image: it has no third-party
# dependencies, so installing it would buy only unmounted runs, at the cost of
# baking in a revision. Nor is the metrics driver prebuilt — only a run-time
# build matches the checkout driving the run.
ENV PYTHONPATH=/opt/crustify-audit/src

# `unsafe` is deterministic and free; `ub` is agentic and spends.
ENV CRUSTIFY_VERB=ub

# `<provider>/<model>`; the prefix selects the backend. Drives `ub` only.
ENV CRUSTIFY_MODEL=anthropic/claude-opus-5

# Not decoration: neither CLI uses an environment key on its own, so `api` adds
# `--bare` (claude) or an env-key provider block (codex).
ENV CRUSTIFY_BILLING=subscription

# Wall-clock BUDGET in minutes, not a per-agent leash: agents are spawned one
# after another until it is reached and none is killed, so the run overshoots
# by however long the last one takes. 0 runs one agent.
ENV CRUSTIFY_TIMEOUT=60

# HOME is the volume, so what the agent fetches or builds survives `--rm`.
# RUSTUP_HOME is pinned back out of it: rustup resolves from HOME, and against
# an empty volume `cargo +nightly` finds no toolchain and silently downloads a
# fresh nightly WITHOUT this image's components — losing miri unannounced.
# CARGO_HOME does belong on the volume, for the registry cache.
ENV HOME=/work \
    RUSTUP_HOME=/root/.rustup \
    CARGO_HOME=/work/.cargo
RUN mkdir -p /work /target

# `crustify-audit` is the CLI, for a `docker exec` with your own arguments;
# `crustify-audit-run` is what the container runs, off the CRUSTIFY_* env.
RUN printf '%s\n' '#!/usr/bin/env bash' \
      'exec python3 -m crustify_audit.cli "$@"' \
      > /usr/local/bin/crustify-audit \
    && chmod +x /usr/local/bin/crustify-audit

RUN printf '%s\n' '#!/usr/bin/env bash' 'set -euo pipefail' \
      '[ -d /opt/crustify-audit/src/crustify_audit ] || {' \
      '    echo "no checkout at /opt/crustify-audit — mount this repo there" >&2' \
      '    exit 2; }' \
      'target=/target' \
      '[ -f "$target/Cargo.toml" ] || [ -f "$target/crustify/rust/Cargo.toml" ] || {' \
      '    echo "no crate at $target — mount the repository to audit there," >&2' \
      '    echo "e.g. -v /path/to/repo:/target. Looked for Cargo.toml at the" >&2' \
      '    echo "root and at crustify/rust/." >&2; exit 2; }' \
      '# Without git the run cannot record WHICH revision it audited.' \
      'if [ -d "$target/.git" ]; then' \
      '    echo "[crustify-audit] target $(git -C "$target" rev-parse --abbrev-ref HEAD) @ $(git -C "$target" rev-parse --short HEAD)"' \
      'else' \
      '    echo "[crustify-audit] warning: $target is not a git checkout, so the" >&2' \
      '    echo "audited revision cannot be recorded" >&2' \
      'fi' \
      '# Checked here: an agent with no usable auth issues no request and exits' \
      '# 0, which reads as a hunt that found nothing.' \
      'case "${CRUSTIFY_BILLING}" in' \
      '    subscription)' \
      '        case "${CRUSTIFY_MODEL%%/*}" in' \
      '        anthropic) [ -s "$HOME/.claude/.credentials.json" ] || {' \
      '            echo "no OAuth token at $HOME/.claude/.credentials.json." >&2' \
      '            echo "Copy one in:  mkdir -p ~/.claude-audit &&" >&2' \
      '            echo "  cp ~/.claude/.credentials.json ~/.claude-audit/" >&2' \
      '            echo "then mount it:  -v ~/.claude-audit:/work/.claude" >&2' \
      '            exit 2; } ;;' \
      '        openai)    [ -s "$HOME/.codex/auth.json" ] || {' \
      '            echo "no login at $HOME/.codex/auth.json — mount a copy of" >&2' \
      '            echo "~/.codex at /work/.codex" >&2; exit 2; } ;;' \
      '        esac ;;' \
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
      '    unsafe) exec crustify-audit "$target" unsafe "$@" ;;' \
      '    ub) exec crustify-audit "$target" ub \' \
      '            --model "${CRUSTIFY_MODEL}" \' \
      '            --billing "${CRUSTIFY_BILLING}" \' \
      '            --timeout "${CRUSTIFY_TIMEOUT}" "$@" ;;' \
      '    *) echo "bad CRUSTIFY_VERB: ${CRUSTIFY_VERB} (unsafe|ub)" >&2; exit 2 ;;' \
      'esac' \
      > /usr/local/bin/crustify-audit-run \
    && chmod +x /usr/local/bin/crustify-audit-run

# The agent starts in the repository it audits, and so does a later `exec`.
WORKDIR /target
CMD ["crustify-audit-run"]
