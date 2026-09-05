# Sandbox for handling STRANGER CONTENT — importing a model repo you did not
# write, and running the cockpit over models you have imported.
#
# This is the third layer of a three-layer defence, not a replacement for the
# other two:
#
#   1. FENCE       (make_use / make_tasks) — stops hostile prose from acquiring
#                  authority over the reader's ASSISTANT.
#   2. ALLOW-LIST  (import_model) — stops hostile FILES from reaching the disk.
#   3. CONTAINMENT (this) — bounds the blast radius if 1 or 2 are wrong.
#
# What containment adds, precisely:
#   * the hostile repo is mounted READ-ONLY; nothing can write back to it
#   * the only writable path is the instance's models directory
#   * `--network=none` at run time — an import needs no network at all, which
#     kills the exfiltration-beacon class outright even if every other control
#     fails
#   * a non-root user, so a container escape lands somewhere unprivileged
#
# What it does NOT touch, said plainly because overclaiming is worse than the
# gap: the paste-into-ChatGPT surface. A user copying USE.md into their own
# assistant is outside every container — the FENCE is the control there. And a
# user who clones a Garden repo with plain `git clone`, outside this tooling,
# gets no sandbox at all, which is why the card's payload disclosure exists.

FROM python:3.12-slim

# git is a real dependency, not convenience: freeze_check proves a claim
# predates its own resolve date from commit history, and without it the
# criteria-frozen tier silently degrades to self-graded.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# No pip install, deliberately. import_model and the audit are stdlib-only, so
# the sandbox has ZERO third-party packages — every dependency is a dependency
# an attacker could target, and a container for handling hostile input is the
# last place to add optional ones. (The optional extras in requirements.txt are
# for memory search and transcript pulling; neither runs here.)
COPY harness/ ./harness/
COPY suites/  ./suites/

# Non-root. Nothing here needs privilege, and an import least of all.
RUN useradd -m -u 10001 sandbox \
 && mkdir -p /models /import \
 && chown -R sandbox:sandbox /app /models
USER sandbox

# /import  — the untrusted repo, mounted read-only by the wrapper
# /models  — the instance's models dir, the only writable mount
ENV PYTHONPATH=/app PYTHONDONTWRITEBYTECODE=1 MODELS_DIR=/models
VOLUME ["/models"]

# Default to INSPECT, not import. Looking is safe; importing is a decision, and
# the default action of a security tool should never be the irreversible one.
CMD ["python", "-m", "suites.import_model", "--inspect", "/import"]
