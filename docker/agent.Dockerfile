# Agent sandbox — Claude Code over UNTRUSTED content, in a container.
#
# ## Read this before using it: it is a WEAKER tier than the import sandbox
#
# `docker/sandbox.Dockerfile` runs with `--network=none`, no credential, and no
# model. That is the hardened path and it is unchanged — do not modify it to add
# an LLM. This image exists beside it for the jobs that genuinely need a model
# over content you do not trust: reading a stranger's MODEL.md and reasoning
# about it, which an offline scanner cannot do.
#
# What is given up, stated plainly:
#
#   * NETWORK IS ON. It has to be; the CLI calls an API. The exfiltration-beacon
#     class that `--network=none` closed outright is open again here.
#   * A CREDENTIAL IS PRESENT. See below for how that is limited.
#
# What is kept:
#
#   * the untrusted repo is still mounted READ-ONLY
#   * still non-root
#   * the host home directory is never mounted; nothing persists after exit
#
# ## Two backends, and why the default is OpenRouter
#
# LLM_BACKEND=openrouter (DEFAULT here) — plain HTTPS to an OpenAI-compatible
# endpoint. No CLI, no OAuth, no keychain, and the key is scoped to whatever the
# operator provisioned. This is the recommended path for a container handling
# untrusted input: the credential is a single-purpose API key rather than a
# session token tied to a person's whole account.
#
# LLM_BACKEND=claude-code — the CLI is installed and works, run with `--bare`,
# whose documented behaviour is that "Anthropic auth is strictly
# ANTHROPIC_API_KEY or apiKeyHelper via --settings (OAuth and keychain are NEVER
# read)". So even on this path the operator's ~/.claude/.credentials.json is not
# mounted and cannot be reached. Use it when you want the agentic loop — file
# reads and tool use — rather than a single completion.
#
# Either way: use a key PROVISIONED FOR THIS PURPOSE. A container reading
# untrusted files is the wrong place for a credential you would mind losing, and
# neither backend here can reach the operator's personal session token.

FROM node:22-slim

# Python for the suites; git because freeze_check reads commit history.
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-venv git ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && ln -sf /usr/bin/python3 /usr/local/bin/python

# Installed from npm rather than copied from the host: the host binary is a
# native Windows install and would not run here.
RUN npm install -g @anthropic-ai/claude-code \
 && npm cache clean --force

WORKDIR /app
COPY harness/ ./harness/
COPY suites/  ./suites/

RUN useradd -m -u 10001 agent \
 && mkdir -p /models /import /work \
 && chown -R agent:agent /app /models /work
USER agent

# --bare is not a convenience flag here, it is the control: it is what keeps
# OAuth and the keychain out of this container entirely.
ENV PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    MODELS_DIR=/models \
    LLM_BACKEND=openrouter \
    CLAUDE_CODE_SIMPLE=1 \
    HOME=/home/agent

WORKDIR /work
CMD ["claude", "--bare", "-p", "--help"]
