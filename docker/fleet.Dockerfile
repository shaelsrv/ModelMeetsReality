# A running instance — the cockpit and the suites, on the operator's own
# Claude Code subscription.
#
# ## How this differs from the other two images
#
#   sandbox.Dockerfile   --network=none, no credential, no model. Hardened, for
#                        reading untrusted repos.
#   agent.Dockerfile     network on, API key, untrusted repo mounted read-only,
#                        nothing persists. For reasoning ABOUT a stranger's repo.
#   fleet.Dockerfile     THIS. Your own instance, your own models, state that
#                        must survive the container.
#
# The distinction that matters: the other two are for untrusted input and are
# built to lose everything on exit. This one is the opposite — a fleet whose
# ledger and git history do not survive is useless, because freeze-proof IS the
# product.
#
# ## Auth: the subscription path, and what it costs you
#
# `claude -p` (no --bare) reads ~/.claude/.credentials.json. To run on the
# operator's subscription rather than a metered key, that directory is mounted.
#
# It must be mounted READ-WRITE. The OAuth token refreshes in place, so a
# read-only mount works until the token expires and then fails in a way that
# looks like a network problem.
#
# State the exposure plainly: the container can read the operator's account
# session token. That is acceptable HERE because this image runs the operator's
# OWN models over sources they chose. Do not reuse this image for untrusted
# input — that is what agent.Dockerfile exists for, and it deliberately cannot
# reach this credential.
#
# ## Build and run
#
#   docker build -f docker/fleet.Dockerfile -t mmr-fleet .
#   docker run --rm -p 8790:8787 \
#     -v "C:/Users/<you>/.claude:/home/agent/.claude" \
#     -v "C:/Users/<you>/.claude.json:/home/agent/.claude.json" \
#     -v mmr-models:/models \
#     mmr-fleet
#
# The cockpit then answers on http://localhost:8790.
#
# TWO auth mounts are required, not one. The credential lives in .claude/, but
# the CLI also reads .claude.json at the home ROOT and refuses to start without
# it ("Claude configuration file not found"). Mounting only the directory gives
# a confusing half-authenticated state that reads as "Not logged in".
#
# On Docker Desktop for Windows use the WINDOWS path form (C:/Users/...). The
# MSYS form (/c/Users/...) silently mounts an EMPTY directory instead of
# failing, which also presents as "Not logged in".

FROM node:22-slim

# python3 for the suites (stdlib-only, so nothing else is needed for the core);
# git because freeze_check and make_card read commit history and freeze-proof
# depends on it; ca-certificates for HTTPS.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      python3 python3-venv git ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && ln -sf /usr/bin/python3 /usr/local/bin/python

# From npm, not copied from the host: a Windows install will not run here.
RUN npm install -g @anthropic-ai/claude-code \
 && npm cache clean --force

WORKDIR /app
COPY harness/   ./harness/
COPY suites/    ./suites/
COPY ui/        ./ui/
COPY map/       ./map/
COPY fleet.json ./fleet.json

# uid 10001 matches the other images so a shared volume does not end up with
# mixed ownership.
RUN useradd -m -u 10001 agent \
 && mkdir -p /models \
 && chown -R agent:agent /app /models
USER agent

ENV PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MODELS_DIR=/models \
    LLM_BACKEND=claude-code \
    HOME=/home/agent \
    COCKPIT_HOST=0.0.0.0

EXPOSE 8787
CMD ["python", "ui/server.py"]
