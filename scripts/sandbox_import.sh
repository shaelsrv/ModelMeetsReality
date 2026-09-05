#!/usr/bin/env bash
# Import a model repo you did not write, inside a container.
#
#   scripts/sandbox_import.sh ../some-downloaded-model            # inspect only
#   scripts/sandbox_import.sh ../some-downloaded-model --yes      # then import
#
# The wrapper is the product. A hardened path that takes more typing than the
# unsafe one does not get used, and an unused control protects nobody.
#
# If Docker is missing this falls back to the HOST allow-list import and says so
# loudly — the allow-list is a real control on its own, and failing closed here
# would just push people back to the unwrapped command.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${1:-}"
shift || true
CONFIRM="${1:-}"

if [ -z "$SRC" ]; then
  echo "usage: scripts/sandbox_import.sh <path-to-model-repo> [--yes]"
  exit 1
fi
if [ ! -d "$SRC" ]; then
  echo "not a directory: $SRC"
  exit 1
fi
SRC="$(cd "$SRC" && pwd)"

# The instance's models dir — the ONLY thing this is allowed to write to.
MODELS="$(python -c "
import json,sys
from pathlib import Path
r = Path('$HERE')
cfg = json.load((r/'fleet.json').open(encoding='utf-8')) if (r/'fleet.json').exists() else {}
print((r / cfg['models_dir']).resolve() if cfg.get('models_dir') else r.parent)
")"

if ! command -v docker >/dev/null 2>&1; then
  echo "!! docker not found — FALLING BACK to host import."
  echo "   The allow-list still applies (only documents reach your disk), but"
  echo "   there is no containment: no read-only mount, no network isolation."
  echo "   Install Docker for the hardened path."
  echo
  if [ "$CONFIRM" = "--yes" ]; then
    (cd "$HERE" && python -m suites.import_model "$SRC")
  else
    (cd "$HERE" && python -m suites.import_model --inspect "$SRC")
    echo
    echo "   inspect only. re-run with --yes to import."
  fi
  exit $?
fi

IMAGE="copilot-sandbox:latest"
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "==> building $IMAGE (first run only)"
  docker build -q -f "$HERE/docker/sandbox.Dockerfile" -t "$IMAGE" "$HERE" >/dev/null
fi

echo "==> sandboxed import"
echo "    untrusted repo : $SRC  (mounted READ-ONLY)"
echo "    writable path  : $MODELS"
echo "    network        : OFF — an import needs none, so exfiltration cannot"
echo "                     leave even if every other control fails"
echo "    user           : non-root"
echo "    no LLM         : import, audit and card generation need no model, so"
echo "                     no claude/API credential is mounted here"
echo

# --network=none is the single highest-value line here. It is in the wrapper
# rather than the docs so nobody has to remember it.
COMMON=(--rm --network=none
        --read-only --tmpfs /tmp
        -v "$SRC:/import:ro"
        -v "$MODELS:/models"
        "$IMAGE")

if [ "$CONFIRM" = "--yes" ]; then
  docker run "${COMMON[@]}" python -m suites.import_model --inspect /import
  echo
  echo "==> importing"
  # The slug must come from the SOURCE directory name, not the mount point —
  # otherwise every sandboxed import lands as a model called "import".
  docker run "${COMMON[@]}" python -m suites.import_model /import \
    --slug "$(basename "$SRC")"
  echo
  echo "    imported into $MODELS. Its claims are quarantined under imported/ —"
  echo "    a track record belongs to the instance that earned it."
else
  docker run "${COMMON[@]}"
  echo
  echo "    inspect only — nothing was written. Re-run with --yes to import."
fi
