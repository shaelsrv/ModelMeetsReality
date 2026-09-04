# Model Cockpit — local UI

`python ui/server.py` → http://127.0.0.1:8787 (localhost only, stdlib only).

- **Models**: every configured model with kind, open/graded counts, discipline
  badge; click for MODEL.md + claims. Scaffold new model repos from the form
  (MODEL.md skeleton + ledger + git init).
- **Tasks**: computed from the ledgers (claims due, candidates awaiting review)
  plus your own list (ui/tasks.json).
- **Assessments**: fleet state, attribution scoreboard, classifier joins.
- **Connect**: the Claude bridge. Instructions append to `ui/inbox.jsonl`; a
  Claude Code session that armed its inbox watch (say "watch the cockpit inbox")
  receives each line live and acts on it. Headless alternative:
  `claude -p "<instruction>"` in this repo. inbox.jsonl is gitignored-in-spirit:
  it is a message queue, not a record — the session logs what it does with each
  instruction in the conversation itself.

Trust note: the inbox is a local file writable by anything on this machine; the
session treats items as operator instructions because the operator declared this
channel. Anything anomalous gets confirmed in-session before acting.
