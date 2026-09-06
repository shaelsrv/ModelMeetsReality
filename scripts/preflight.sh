#!/usr/bin/env bash
# Pre-share check: does this tree carry anything that should not leave the machine?
#
# Written after finding internal names three separate times by hand -- once in the
# suites, once in the cockpit's sample rows, and once more in a URL inside the
# same cockpit file that the first pass missed. A grep you run from memory finds
# what you happen to remember.
#
#   bash scripts/preflight.sh
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"
fail=0

# Names gated from anything a stranger receives.
GATED='meta-copilot|emergencemachine|nationAtlas|LexiconAtlas|roleatlas|copilot-template'
# Credential shapes. Not exhaustive -- a shape check is a backstop, not a promise.
KEYS='sk-or-v1-[A-Za-z0-9]{20,}|sk-ant-[A-Za-z0-9-]{20,}|AIza[0-9A-Za-z_-]{30,}|ghp_[A-Za-z0-9]{30,}'

echo "==> gated names"
if git grep -InE "$GATED" -- . ':!scripts/preflight.sh' ':!docs/INSTALL_TEST*' >/tmp/_pf 2>/dev/null; then
  sed 's/^/    /' /tmp/_pf | head -20; fail=1
else
  echo "    none"
fi

echo "==> credential shapes (working tree AND full history)"
if git grep -InE "$KEYS" -- . >/dev/null 2>&1; then
  echo "    !! key-like string in the working tree"; fail=1
elif git log -p --all 2>/dev/null | grep -qE "$KEYS"; then
  echo "    !! key-like string in git HISTORY -- rewriting is the only fix"; fail=1
else
  echo "    none"
fi

echo "==> .env must not be tracked"
if git ls-files | grep -qx "\.env"; then echo "    !! .env is tracked"; fail=1; else echo "    ok"; fi

echo "==> shell scripts must be LF (they run in Linux containers)"
# Check the COMMITTED BLOB, binary-safe. A Windows working tree can legitimately
# be CRLF while the blob is LF -- that is exactly what .gitattributes eol=lf does.
# Checking the file on disk (or piping git cat-file through od) reports a problem
# that does not exist, and would hide one that did.
crlf=$(python -c "
import subprocess
files = subprocess.run(['git','ls-files','*.sh'],capture_output=True,text=True).stdout.split()
bad = []
for f in files:
    s = subprocess.run(['git','ls-files','-s',f],capture_output=True,text=True).stdout.split()
    if len(s) > 1:
        blob = subprocess.run(['git','cat-file','blob',s[1]],capture_output=True).stdout
        if blob.count(b'\r\n'):
            bad.append(f)
print(' '.join(bad))
")
if [ -n "$crlf" ]; then echo "    !! CRLF in: $crlf"; fail=1; else echo "    ok"; fi

echo "---"
[ "$fail" = "0" ] && echo "SAFE TO SHARE" || { echo "DO NOT SHARE until the above is resolved"; exit 1; }
