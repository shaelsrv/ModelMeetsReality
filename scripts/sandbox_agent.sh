#!/usr/bin/env bash
# Have a model read an UNTRUSTED model repo, in a container.
#
#   scripts/sandbox_agent.sh ../some-model
#   scripts/sandbox_agent.sh ../some-model "is this a real model or a stunt?"
#
# This is the WEAKER of the two sandboxes. Use scripts/sandbox_import.sh unless
# you actually need a model to read the content — that one runs with no network,
# no credential and no LLM, and covers import, audit and card generation.
#
# This exists for the job the offline scanner cannot do: reading a stranger's
# document and judging whether it is a real falsifiable theory or a stunt.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${1:-}"
PROMPT="${2:-}"

if [ -z "$SRC" ] || [ ! -d "$SRC" ]; then
  echo "usage: scripts/sandbox_agent.sh <path-to-model-repo> [prompt]"
  exit 1
fi
SRC="$(cd "$SRC" && pwd)"
# Git Bash on Windows reports POSIX paths ("/c/Users/…"), which the Docker
# daemon rejects as non-absolute. `pwd -W` gives the Windows form it accepts.
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*)
    SRC="$(cd "$SRC" && pwd -W)"
    # Git Bash rewrites POSIX-looking arguments into Windows paths, which mangles
    # the CONTAINER-side half of a -v mount ("/import" becomes a drive path).
    # MSYS_NO_PATHCONV=1 turns that off for these calls.
    export MSYS_NO_PATHCONV=1 ;;
esac

ENV_ARGS=""
NET_ARGS=""
BACKEND=""
NOTE=""

# A LOCAL model changes the picture materially: no credential exists, and
# nothing the container says reaches the internet. It is the strongest
# configuration this tier can run in, so it is preferred when configured.
if [ -n "${OPENROUTER_BASE:-}" ] && \
   echo "$OPENROUTER_BASE" | grep -qiE "localhost|127\.0\.0\.1|host\.docker\.internal"; then
  # Rewrite localhost to the docker-host alias. Inside a container "localhost"
  # is the CONTAINER, not your machine — the classic silent failure here.
  LOCAL_BASE="$(echo "$OPENROUTER_BASE" | sed -E 's#(localhost|127\.0\.0\.1)#host.docker.internal#')"
  ENV_ARGS="-e OPENROUTER_BASE=$LOCAL_BASE -e LLM_BACKEND=openrouter"
  NET_ARGS="--add-host=host.docker.internal:host-gateway"
  BACKEND="LOCAL model at $LOCAL_BASE"
  NOTE="no credential exists, and nothing leaves your machine"
elif [ -n "${OPENROUTER_API_KEY:-}" ]; then
  ENV_ARGS="-e OPENROUTER_API_KEY -e LLM_BACKEND=openrouter"
  [ -n "${OPENROUTER_BASE:-}" ] && ENV_ARGS="$ENV_ARGS -e OPENROUTER_BASE"
  BACKEND="OpenRouter (single-purpose API key)"
  NOTE="the key is passed as an env var and nothing is written to your home dir"
elif [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  ENV_ARGS="-e ANTHROPIC_API_KEY -e LLM_BACKEND=claude-code -e CLAUDE_CODE_SIMPLE=1"
  BACKEND="Claude Code --bare"
  NOTE="--bare means OAuth and the keychain are NEVER read, so your subscription
                     token cannot enter this container"
fi

if [ -z "$ENV_ARGS" ]; then
  cat <<'MSG'
!! No model configured. Pick one:

   FULLY LOCAL — strongest, no credential, nothing leaves the machine:
       ollama serve                         # or start LM Studio's server
       export OPENROUTER_BASE=http://localhost:11434/v1
       scripts/sandbox_agent.sh <repo>

   OpenRouter — a single-purpose key:
       export OPENROUTER_API_KEY=...

   Claude Code — run with --bare, which never reads OAuth or the keychain:
       export ANTHROPIC_API_KEY=...

   A container that reads untrusted files is the wrong place for a credential
   you would mind losing, which is why local is listed first.
MSG
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "!! docker not found. There is no host fallback for this one, on purpose:"
  echo "   running a model over untrusted content WITHOUT a container is the"
  echo "   thing the container exists to prevent. Use sandbox_import.sh, which"
  echo "   degrades safely to a host allow-list import."
  exit 1
fi

IMAGE="mmr-agent:latest"
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "==> building $IMAGE (first run only)"
  docker build -q -f "$HERE/docker/agent.Dockerfile" -t "$IMAGE" "$HERE" >/dev/null
fi

cat <<MSG
==> agent sandbox — WEAKER TIER than sandbox_import.sh
    untrusted repo : $SRC  (mounted READ-ONLY)
    model          : $BACKEND
                     $NOTE
    network        : ON — required to reach the model. The isolation that
                     sandbox_import.sh gets from --network=none is NOT here.
    user           : non-root
    persistence    : none — --rm, and no host home is mounted

MSG

# shellcheck disable=SC2086
docker run --rm $NET_ARGS \
  --read-only --tmpfs /tmp --tmpfs /home/agent --tmpfs /work \
  $ENV_ARGS \
  -v "$SRC:/import:ro" \
  "$IMAGE" \
  python -m suites.review_untrusted /import ${PROMPT:+--ask "$PROMPT"}
