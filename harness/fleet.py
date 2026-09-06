"""Fleet registry — the ONLY place an instance names its models.

fleet.json (repo root):
{
  "models": ["my-first-model", "another-model"],      // sister repos, siblings of this one
  "classifiers": [],                                   // classifier meta-models, if any
  "decision_repo": "",                                 // optional: repo whose lens decision_trace uses
  "extra_ledgers": []                                  // optional: extra ledger paths for the grading loop
}
"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_cfg = {}
_f = ROOT / "fleet.json"
if _f.exists():
    _cfg = json.load(_f.open(encoding="utf-8"))

# where this instance's model repos live: its own subdirectory if configured,
# otherwise the shared parent (the original, still-default layout). Two
# instances under one parent otherwise share a namespace and can collide.
#
# The MODELS_DIR env override exists for the sandbox container, where the models
# directory is a MOUNT at a fixed path and the instance's fleet.json is not
# present. Explicit environment beats a config file that is not there — without
# it the container resolves to its own /app parent and writes nowhere useful.
_env_dir = os.environ.get("MODELS_DIR")
MODELS_DIR = (Path(_env_dir).resolve() if _env_dir
              else ((ROOT / _cfg["models_dir"]).resolve()
                    if _cfg.get("models_dir") else ROOT.parent))

MODEL_REPOS = _cfg.get("models", [])
CLASSIFIERS = _cfg.get("classifiers", [])
DECISION_REPO = _cfg.get("decision_repo", "")
EXTRA_LEDGERS = _cfg.get("extra_ledgers", [])
INSTRUMENT_LEDGERS = ([(f"{m}/predict/ledger.json", "model_watch", [m], None)
                       for m in MODEL_REPOS]
                      + [(l, "generic", None, None) for l in EXTRA_LEDGERS])
