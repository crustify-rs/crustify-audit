# Bootstraps a crustify-audit ORCHESTRATOR. Nothing here is target-specific.
#
# The container starts an agent that resolves the audit plan and then spawns
# `crustify-audit ... ub` itself. Run it INTERACTIVELY (`-it`) to answer any
# mandatory questions not already filled in TASK.md. A headless run needs all
# mandatory TASK answers.
#
#   docker build -t crustify-audit examples/
#
#   docker run --rm -it --name audit-ippcp \
#       -e ANTHROPIC_API_KEY \
#       -v "$PWD:/opt/crustify-audit" \
#       -v /path/to/target-repo:/target \
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

# `orchestrate` starts the interviewing agent, which spawns the auditors.
# `unsafe` is the deterministic scan: no agent, no spend, useful on its own.
ENV CRUSTIFY_VERB=orchestrate

# The CLI and model used by the ORCHESTRATOR. The model string is passed to the
# selected CLI verbatim.
ENV CRUSTIFY_BACKEND=claude
ENV CRUSTIFY_MODEL=claude-opus-5

# Headless mode cannot resolve missing mandatory TASK answers interactively.
ENV CRUSTIFY_HEADLESS=0

# codex only; the CLI accepts any string locally and rejects it at the API.
ENV CRUSTIFY_EFFORT=high

# Not decoration: neither CLI uses an environment key on its own, so `api` adds
# `--bare` (claude) or an env-key provider block (codex) -- a key in the
# environment does nothing until this says to use it. `api` is the default
# since a fresh image holds no login; `subscription` spends the session the
# CLI finds under HOME, which is the named volume, so a `claude` or `codex`
# login done once inside the container survives every later run against it.
ENV CRUSTIFY_BILLING=api

# Wall-clock BUDGET in minutes PER AUDITOR, not a leash: agents are spawned one
# after another until it is reached and none is killed, so a run overshoots by
# however long the last one takes. 0 runs one agent. With N auditors at once,
# spend is roughly N times this -- the orchestrator is told to say that number
# out loud before you agree to it.
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

# /target is a bind mount owned by the HOST user while the container runs as
# root, so git rejects it for "dubious ownership" -- which breaks recording the
# audited revision and every worktree the patch objective creates. --system,
# not --global: HOME is the named volume, and a gitconfig written under it at
# build time is masked whenever that volume already exists.
RUN git config --system --add safe.directory '*'

# `crustify-audit` is the CLI the orchestrator spawns auditors with;
# `crustify-audit-orchestrator` is what the container runs, off the CRUSTIFY_*
# env.
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
      '    rev="$(git -C "$target" rev-parse --abbrev-ref HEAD) @ $(git -C "$target" rev-parse --short HEAD)"' \
      '    echo "[crustify-audit] target $rev"' \
      'else' \
      '    rev="not a git checkout"' \
      '    echo "[crustify-audit] warning: $target is not a git checkout, so the" >&2' \
      '    echo "audited revision cannot be recorded" >&2' \
      'fi' \
      '# The deterministic scan needs no agent and no auth: run it and stop.' \
      'if [ "${CRUSTIFY_VERB}" = "unsafe" ]; then' \
      '    exec crustify-audit "$target" unsafe "$@"' \
      'fi' \
      '[ "${CRUSTIFY_VERB}" = "orchestrate" ] || {' \
      '    echo "bad CRUSTIFY_VERB: ${CRUSTIFY_VERB} (orchestrate|unsafe)" >&2' \
      '    exit 2; }' \
      'case "${CRUSTIFY_BACKEND:-}" in' \
      '    claude) backend=claude; auditor_provider=anthropic ;;' \
      '    codex)  backend=codex;  auditor_provider=openai ;;' \
      '    *) echo "bad CRUSTIFY_BACKEND: ${CRUSTIFY_BACKEND:-<empty>} (claude|codex)" >&2' \
      '       exit 2 ;;' \
      'esac' \
      '[ -n "${CRUSTIFY_MODEL:-}" ] || {' \
      '    echo "CRUSTIFY_MODEL must name the orchestrator model" >&2; exit 2; }' \
      '# Checked here: an agent with no usable auth issues no request and exits' \
      '# 0, which reads as a hunt that found nothing.' \
      'auth=()' \
      'case "${CRUSTIFY_BILLING:-}" in' \
      '    subscription) ;;' \
      '    api|"")' \
      '        case "$backend" in' \
      '        claude) [ -n "${ANTHROPIC_API_KEY:-}" ] || {' \
      '            echo "CRUSTIFY_BILLING=api needs ANTHROPIC_API_KEY" >&2; exit 2; }' \
      '            auth=(--bare) ;;' \
      '        codex)  [ -n "${OPENAI_API_KEY:-}" ] || {' \
      '            echo "CRUSTIFY_BILLING=api needs OPENAI_API_KEY" >&2; exit 2; }' \
      '            auth=(-c "model_provider=openai_apikey"' \
      '                  -c "model_providers.openai_apikey.name=\"OpenAI\""' \
      '                  -c "model_providers.openai_apikey.base_url=\"https://api.openai.com/v1\""' \
      '                  -c "model_providers.openai_apikey.env_key=\"OPENAI_API_KEY\""' \
      '                  -c "model_providers.openai_apikey.wire_api=\"responses\"") ;;' \
      '        esac ;;' \
      '    *) echo "bad CRUSTIFY_BILLING: ${CRUSTIFY_BILLING}" >&2; exit 2 ;;' \
      'esac' \
      'effort=()' \
      'case "${CRUSTIFY_EFFORT:-}" in' \
      '    "") ;;' \
      '    low|medium|high|xhigh|max|ultra)' \
      '        effort=(-c "model_reasoning_effort=\"${CRUSTIFY_EFFORT}\"") ;;' \
      '    *) echo "bad CRUSTIFY_EFFORT: ${CRUSTIFY_EFFORT}" >&2; exit 2 ;;' \
      'esac' \
      '# The prompt comes from the MOUNT, so editing it does not mean rebuilding.' \
      'prompt=/opt/crustify-audit/src/crustify_audit/prompts/orchestrator.md' \
      '[ -f "$prompt" ] || { echo "no orchestrator prompt at $prompt" >&2; exit 2; }' \
      '# What only the container knows, appended rather than templated into the' \
      '# prompt: the file stays usable outside a container.' \
      'text="$(cat "$prompt")' \
      '' \
      '---' \
      '' \
      'Container context, for the questions you are about to ask:' \
      '' \
      '- The target checkout is mounted at /target: $rev. It is the only one' \
      '  available, so confirm it rather than asking where it is.' \
      '- Defaults you may propose: --model' \
      '  $auditor_provider/$CRUSTIFY_MODEL, --billing' \
      '  $CRUSTIFY_BILLING, --timeout $CRUSTIFY_TIMEOUT (minutes per auditor).' \
      '- Interaction mode: $CRUSTIFY_HEADLESS (0 is interactive, 1 is' \
      '  headless).' \
      '- The crustify-audit CLI is on PATH. Spawn auditors with it. Run the' \
      '  deterministic scan first -- crustify-audit /target unsafe -- for the' \
      '  data that tells you how to partition worksets."' \
      '# Append a task only when the conventional external mount is present.' \
      'task=' \
      'if [ -f /campaign/TASK.md ]; then' \
      '    task=/campaign/TASK.md' \
      'fi' \
      '# A pre-filled task answers part of the interview. Appended, not' \
      '# merged: the orchestrator reads it and resolves what is missing.' \
      'if [ -n "$task" ]; then' \
      '    echo "[crustify-audit] task $task"' \
      '    text="$text' \
      '' \
      '---' \
      '' \
      'The user pre-filled the task below. Concrete answers are decided. Ask' \
      'for mandatory answers that are missing or still in angle brackets;' \
      'choose unanswered optional values yourself. In headless mode, do not' \
      'launch while a mandatory answer is unresolved.' \
      '' \
      '$(cat "$task")"' \
      'fi' \
      'skip=--dangerously-skip-permissions' \
      'bypass=--dangerously-bypass-approvals-and-sandbox' \
      'case "${backend}:${CRUSTIFY_HEADLESS}" in' \
      '    claude:0) exec claude "$skip" "${auth[@]}" --model "$CRUSTIFY_MODEL" "$text" "$@" ;;' \
      '    claude:1) exec claude "$skip" "${auth[@]}" --model "$CRUSTIFY_MODEL" -p "$text" "$@" ;;' \
      '    codex:0)  exec codex "$bypass" "${auth[@]}" "${effort[@]}" --model "$CRUSTIFY_MODEL" "$text" "$@" ;;' \
      '    codex:1)  exec codex exec "$bypass" "${auth[@]}" "${effort[@]}" --model "$CRUSTIFY_MODEL" "$text" "$@" ;;' \
      '    *) echo "bad CRUSTIFY_BACKEND/CRUSTIFY_HEADLESS:" \' \
      '            "${CRUSTIFY_BACKEND}/${CRUSTIFY_HEADLESS}" >&2; exit 2 ;;' \
      'esac' \
      > /usr/local/bin/crustify-audit-orchestrator \
    && chmod +x /usr/local/bin/crustify-audit-orchestrator

# The orchestrator starts in the repository it will have auditors work on.
WORKDIR /target
CMD ["crustify-audit-orchestrator"]
