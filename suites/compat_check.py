"""Does this change still work at every installation level?

There are three ways a person runs a model from this system, and they have
almost nothing in common:

  1. ASSISTANT — no install at all. Paste USE.md into ChatGPT or Claude. No
     Python, no repo, no tooling. The largest audience and the easiest to break
     without noticing, because nothing here executes to tell you.
  2. LOCAL — the suites on the host. Python, a clone, the cockpit.
  3. DOCKER — the sandboxes, for untrusted content.

And inside the local and docker levels, three model backends:

  a. claude-code   the CLI, billing an existing subscription
  b. openrouter    a hosted API key
  c. local         Ollama / LM Studio, no key, nothing leaves the machine

A change is only done when it works at every level it touches. That is easy to
say and easy to forget, so this checks it rather than trusting a checklist —
the same reason freeze_check exists rather than a promise that claims were
registered early.

What it cannot check, stated so nobody reads a green run as more than it is:
whether a PASTED prompt still behaves correctly in someone else's assistant.
That needs a live session, which is why the USE.md flow gets tested by hand and
this reports it as UNVERIFIABLE rather than silently passing.

    python -m suites.compat_check              # every level reachable from here
    python -m suites.compat_check --json
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

from harness.fleet import ROOT, MODELS_DIR  # noqa: E402

OK, FAIL, SKIP, MANUAL = "ok", "FAIL", "skip", "manual"


def _r(level: str, name: str, status: str, note: str = "") -> dict:
    return {"level": level, "check": name, "status": status, "note": note}


def _bash_path(p: Path) -> str:
    """A path Git Bash can actually open: /f/tools/... not F:/tools/..."""
    s = p.resolve().as_posix()
    if len(s) > 2 and s[1] == ":":
        return f"/{s[0].lower()}{s[2:]}"
    return s


# --- 1. ASSISTANT: no install --------------------------------------------
def check_assistant() -> list:
    out = []
    slugs = [p.name for p in MODELS_DIR.iterdir()
             if p.is_dir() and (p / "MODEL.md").exists()] if MODELS_DIR.exists() else []
    if not slugs:
        return [_r("assistant", "models present", SKIP, "no models to check")]

    missing_use = [s for s in slugs if not (MODELS_DIR / s / "USE.md").exists()]
    out.append(_r("assistant", "USE.md on every model",
                  OK if not missing_use else FAIL,
                  "" if not missing_use else f"missing: {', '.join(missing_use[:4])}"))

    missing_tasks = [s for s in slugs if not (MODELS_DIR / s / "TASKS.md").exists()]
    out.append(_r("assistant", "TASKS.md on every model",
                  OK if not missing_tasks else FAIL,
                  "" if not missing_tasks else f"missing: {', '.join(missing_tasks[:4])}"))

    # The fence is the control that protects a reader's assistant. If a
    # regenerated USE.md ever loses it, the paste-in path silently becomes
    # injectable again — and nothing at the local or docker level would notice.
    unfenced = [s for s in slugs
                if (MODELS_DIR / s / "USE.md").exists()
                and "QUOTED VERBATIM" not in
                (MODELS_DIR / s / "USE.md").read_text(encoding="utf-8", errors="replace")]
    out.append(_r("assistant", "USE.md fences untrusted sections",
                  OK if not unfenced else FAIL,
                  "" if not unfenced else f"unfenced: {', '.join(unfenced[:4])}"))

    out.append(_r("assistant", "pasted prompt behaves in a real assistant", MANUAL,
                  "needs a live session; cannot be checked from here"))
    return out


# --- 2. LOCAL: the suites on the host ------------------------------------
def check_local() -> list:
    out = []
    # The offline spine: everything that must work with no model and no network.
    for mod in ("import_model", "legitimacy_audit", "freeze_check", "make_card",
                "make_use", "make_tasks", "compat_check"):
        p = ROOT / "suites" / f"{mod}.py"
        if not p.exists():
            out.append(_r("local", f"suites.{mod}", FAIL, "missing"))
            continue
        r = subprocess.run([sys.executable, "-m", f"suites.{mod}", "--help"],
                           cwd=ROOT, capture_output=True, text=True, timeout=120)
        out.append(_r("local", f"suites.{mod} runs",
                      OK if r.returncode == 0 else FAIL,
                      "" if r.returncode == 0 else (r.stderr or "")[:120]))
    return out


# --- 3. DOCKER: the sandboxes --------------------------------------------
def check_docker() -> list:
    out = []
    if not shutil.which("docker"):
        return [_r("docker", "docker available", SKIP,
                   "not installed — the import wrapper falls back to the host "
                   "allow-list, which is the documented degradation")]
    for name, dockerfile in (("sandbox", "docker/sandbox.Dockerfile"),
                             ("agent", "docker/agent.Dockerfile")):
        out.append(_r("docker", f"{dockerfile} present",
                      OK if (ROOT / dockerfile).exists() else FAIL))
    for name in ("copilot-sandbox:latest", "copilot-agent:latest"):
        r = subprocess.run(["docker", "image", "inspect", name],
                           capture_output=True, text=True, timeout=120)
        out.append(_r("docker", f"image {name}",
                      OK if r.returncode == 0 else SKIP,
                      "" if r.returncode == 0 else "not built yet (wrapper builds on first run)"))
    for w in ("scripts/sandbox_import.sh", "scripts/sandbox_agent.sh"):
        p = ROOT / w
        ok = p.exists()
        if ok and shutil.which("bash"):
            # Git Bash resolves neither "scripts\x.sh" (backslashes read as
            # escapes) nor "F:/tools/..." (drive letters are not a path it
            # knows). It wants "/f/tools/...". Both wrong forms produced a FAIL
            # on files that were fine — this checker's first two runs were both
            # false alarms about itself, which is a fair demonstration of why
            # the checks have to be exercised rather than written.
            # Run from the script's own directory with a BARE FILENAME. Every
            # absolute form failed for a different reason — backslashes read as
            # escapes, drive letters unknown to Git Bash, and even /f/... not
            # resolving from a spawned shell despite working interactively. A
            # bare name in the right cwd sidesteps all of it, and this checker's
            # first three runs were false alarms about itself, which is a fair
            # argument for exercising checks rather than reasoning about them.
            r = subprocess.run(["bash", "-n", p.name], cwd=str(p.parent),
                               capture_output=True, text=True, timeout=60)
            ok = r.returncode == 0
            if not ok:
                out.append(_r("docker", f"{w} syntax", FAIL,
                              (r.stderr or "").strip().splitlines()[0][:100]
                              if r.stderr else ""))
        out.append(_r("docker", f"{w} valid", OK if ok else FAIL))
    return out


# --- backends -------------------------------------------------------------
def _probe(base: str) -> list:
    try:
        with urllib.request.urlopen(f"{base.rstrip('/')}/models", timeout=5) as r:
            d = json.loads(r.read().decode())
        return [m.get("id") for m in d.get("data", []) if m.get("id")]
    except Exception:
        return []


def check_backends() -> list:
    out = []
    from harness.openrouter import _is_local_base as _is_local

    out.append(_r("backend", "claude-code CLI",
                  OK if shutil.which(os.environ.get("CLAUDE_CODE_BIN", "claude"))
                  else SKIP, "not on PATH — that backend is simply unavailable"))
    out.append(_r("backend", "openrouter key",
                  OK if os.environ.get("OPENROUTER_API_KEY") else SKIP,
                  "OPENROUTER_API_KEY unset"))

    # A local server is the only backend that needs NO credential, so its
    # detection is checked even when no server is running: getting this wrong
    # is what made fully-offline operation impossible before.
    for label, base in (("ollama", "http://localhost:11434/v1"),
                        ("lm studio", "http://localhost:1234/v1")):
        models = _probe(base)
        out.append(_r("backend", f"local: {label}",
                      OK if models else SKIP,
                      f"{len(models)} model(s): {', '.join(models[:3])}"
                      if models else "not running"))
    bad = [b for b in ("http://localhost:11434/v1", "http://127.0.0.1:1234/v1",
                       "http://host.docker.internal:11434/v1") if not _is_local(b)]
    out.append(_r("backend", "local endpoints need no API key",
                  OK if not bad else FAIL,
                  "" if not bad else f"not detected as local: {bad}"))
    return out


def check_model(repo: Path) -> list:
    """Is ONE model usable at every level? Works on a stranger's repo too.

    The instance checks above ask "does this installation work". This asks
    "would this model work for someone who has only level 1" — which is the
    question that matters for a Garden listing, where the reader may have no
    Python at all.

    Deliberately does not open the network or run anything from the repo: it
    reads files. A model being CHECKED is not a model being TRUSTED.
    """
    out, name = [], repo.name
    if not (repo / "MODEL.md").exists():
        return [_r("model", f"{name}: MODEL.md", FAIL, "not a model repo")]

    md = (repo / "MODEL.md").read_text(encoding="utf-8", errors="replace")
    out.append(_r("model", f"{name}: falsifiable consequence",
                  OK if "## Falsifiable consequences" in md else FAIL,
                  "" if "## Falsifiable consequences" in md
                  else "unfalsifiable — not listable"))
    has_del = ("deletion clause" in md.lower() or "retires to notation" in md.lower())
    out.append(_r("model", f"{name}: deletion clause", OK if has_del else FAIL))

    # Level 1 is the whole point of these two files.
    use = repo / "USE.md"
    out.append(_r("model", f"{name}: USE.md (level 1)",
                  OK if use.exists() else FAIL,
                  "" if use.exists() else "cannot be run without tooling"))
    if use.exists():
        fenced = "QUOTED VERBATIM" in use.read_text(encoding="utf-8", errors="replace")
        out.append(_r("model", f"{name}: USE.md fenced", OK if fenced else FAIL,
                      "" if fenced else "author text unfenced — INJECTABLE when "
                                        "pasted into an assistant"))
    out.append(_r("model", f"{name}: TASKS.md (scheduled)",
                  OK if (repo / "TASKS.md").exists() else FAIL))
    out.append(_r("model", f"{name}: model.json (card)",
                  OK if (repo / "model.json").exists() else FAIL))
    lic = any((repo / n).exists() for n in
              ("LICENSE", "LICENSE-CODE", "LICENSE.md", "LICENSE.txt"))
    out.append(_r("model", f"{name}: licence", OK if lic else FAIL))
    return out


def main() -> None:
    # Load .env before any chat() call. Without this the backend
    # setting in .env is invisible and the suite reports 'no key'
    # while .env sits there correctly configured.
    from suites.grade_claims import _load_env
    _load_env()
    ap = argparse.ArgumentParser(
        description="Check this change still works at every installation level.")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--model", metavar="PATH",
                    help="check ONE model repo (works on a stranger's clone)")
    ap.add_argument("--all-models", action="store_true",
                    help="check every model this instance holds")
    a = ap.parse_args()

    if a.model or a.all_models:
        repos = ([Path(a.model)] if a.model else
                 sorted(p for p in MODELS_DIR.iterdir()
                        if p.is_dir() and (p / "MODEL.md").exists()))
        rows = [r for repo in repos for r in check_model(repo)]
        if a.json:
            print(json.dumps(rows, indent=1))
            return
        by_repo: dict = {}
        for r in rows:
            by_repo.setdefault(r["check"].split(":")[0], []).append(r)
        for slug, rs in by_repo.items():
            bad = [x for x in rs if x["status"] == FAIL]
            print(f"  {slug:<26} {'ok' if not bad else str(len(bad)) + ' FAIL'}")
            for x in bad:
                print(f"      {x['check'].split(': ',1)[1]}"
                      + (f" — {x['note']}" if x["note"] else ""))
        n_bad = sum(1 for r in rows if r["status"] == FAIL)
        print(f"\n  {len(by_repo)} model(s), {n_bad} failing check(s)")
        if n_bad:
            sys.exit(1)
        return

    rows = (check_assistant() + check_local() + check_docker() + check_backends())
    if a.json:
        print(json.dumps(rows, indent=1))
        return

    LEVELS = {"assistant": "1. ASSISTANT — paste, no install",
              "local": "2. LOCAL — suites on the host",
              "docker": "3. DOCKER — sandboxes for untrusted content",
              "backend": "   BACKENDS — claude-code / openrouter / local"}
    for lvl, title in LEVELS.items():
        print(f"\n{title}")
        for r in [x for x in rows if x["level"] == lvl]:
            mark = {OK: " ok  ", FAIL: "FAIL ", SKIP: "skip ",
                    MANUAL: "MANUAL"}[r["status"]]
            print(f"  [{mark}] {r['check']}"
                  + (f"  — {r['note']}" if r["note"] else ""))

    fails = [r for r in rows if r["status"] == FAIL]
    manual = [r for r in rows if r["status"] == MANUAL]
    print(f"\n  {len(fails)} failing, {len(manual)} needing a human, "
          f"{sum(1 for r in rows if r['status'] == SKIP)} unavailable here.")
    if manual:
        print("  A 'manual' row is not a pass. The pasted-prompt path can only be")
        print("  checked in a live assistant, and it is the level with the most users.")
    if fails:
        sys.exit(1)


if __name__ == "__main__":
    main()
