"""The board — which actors have which moves available, and which they played.

WHAT THIS IS NOT. It is not a game engine and must never become one. The failure
mode is inventing a move-space from strategy priors -- "OpenAI could acquire,
could lobby, could open-source" -- which is an analyst's imagination wearing
board vocabulary. Nothing appears on this board that is not already in a ledger
row, enumerated by a named model, before the outcome.

So this is an ASSEMBLY suite, like model_graph and mindmap. It projects what the
fleet has already committed to, into a shape that shows the contest.

  PIECES        actors -- entities that can act. Only actors: an actor can take
                a move, a topic cannot.
  TERRITORY     topic entities. Not pieces; the ground the pieces contest.
                Kept rather than discarded -- "sovereign compute" is not a
                player, it is what players are playing over.
  AVAILABLE     a piece's moves at time T = the union of possible_states across
  MOVES         OPEN predictions about it. Each move carries the model that
                enumerated it, because a move nobody's model foresaw is not on
                the board.
  MOVES PLAYED  graded rows' actual_state. Including UNLISTED -- an actor
                playing a move no model had on its board is the single most
                informative event this apparatus can record, and is rendered
                distinctly.

THE METRIC WORTH READING. Per piece: how many distinct moves were foreseen, by
how many models, and whether the models agree on the option set. A piece with
one watcher and three moves is thinly seen. A piece where two models enumerate
non-overlapping options is contested -- they do not agree on what it can do.

  python -m suites.board --build
  python -m suites.board --report
"""
from __future__ import annotations

import argparse
import collections
import datetime
import json
from pathlib import Path

from harness.fleet import MODELS_DIR, ROOT

OUT = ROOT / "map" / "board"

# An actor can take a move. A topic cannot. The split is stated here rather than
# guessed per run, and anything unlisted is reported as unclassified rather than
# silently placed.
ACTOR_HINTS = ("openai", "anthropic", "google", "deepmind", "meta", "mistral",
               "xai", "deepseek", "nvidia", "microsoft", "amazon", "apple",
               "office", "commission", "regulator", "agency", "enisa",
               "government", "ministry", "parliament", "court")


def is_actor(eid: str, name: str) -> bool:
    blob = f"{eid} {name}".lower()
    return any(h in blob for h in ACTOR_HINTS)


def gather() -> dict:
    """Read every model's watch list and ledger. One pass, no inference."""
    pieces = collections.defaultdict(lambda: {
        "moves": collections.defaultdict(set),   # move -> {models}
        "played": [], "watchers": set(), "name": ""})
    territory = collections.defaultdict(lambda: {"watchers": set(), "name": ""})
    unclassified = {}

    for wf in sorted(MODELS_DIR.glob("*/watch.json")):
        model = wf.parent.name
        try:
            cfg = json.loads(wf.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        for e in cfg.get("entities", []):
            eid, nm = e.get("id"), e.get("name", "")
            if not eid or eid == "example":
                continue
            if is_actor(eid, nm):
                pieces[eid]["watchers"].add(model)
                pieces[eid]["name"] = nm or eid
            else:
                territory[eid]["watchers"].add(model)
                territory[eid]["name"] = nm or eid
                unclassified[eid] = nm

    for lf in sorted(MODELS_DIR.glob("*/predict/ledger.json")):
        model = lf.parent.parent.name
        try:
            d = json.loads(lf.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        for r in d.get("predictions", d if isinstance(d, list) else []):
            eid = r.get("entity")
            if eid not in pieces:
                continue
            if r.get("status") == "open":
                for s in (r.get("possible_states") or []):
                    pieces[eid]["moves"][s].add(model)
            else:
                pieces[eid]["played"].append({
                    "model": model, "date": r.get("assessed_on") or r.get("resolve_by"),
                    "state": r.get("actual_state") or "(state not recorded)",
                    "unlisted": bool(r.get("unlisted_state")),
                    "claim": str(r.get("claim", ""))[:120]})

    return {"pieces": pieces, "territory": territory, "unclassified": unclassified}


def build() -> dict:
    g = gather()
    today = datetime.date.today().isoformat()
    snap = {"spec": "board-v1", "at": today, "pieces": [], "territory": []}

    for eid, p in sorted(g["pieces"].items()):
        moves = [{"move": m, "foreseen_by": sorted(ms)}
                 for m, ms in sorted(p["moves"].items())]
        # Do the watchers agree on what this piece can do? Non-overlapping
        # option sets mean two models disagree about the actor's choices.
        per_model = collections.defaultdict(set)
        for m, ms in p["moves"].items():
            for mm in ms:
                per_model[mm].add(m)
        contested = False
        mods = list(per_model)
        for i in range(len(mods)):
            for j in range(i + 1, len(mods)):
                a, b = per_model[mods[i]], per_model[mods[j]]
                if a and b and not (a & b):
                    contested = True
        snap["pieces"].append({
            "id": eid, "name": p["name"],
            "watchers": sorted(p["watchers"]),
            "moves_available": len(moves), "moves": moves,
            "moves_played": p["played"],
            "contested_option_set": contested})

    for eid, t in sorted(g["territory"].items()):
        snap["territory"].append({"id": eid, "name": t["name"],
                                  "watchers": sorted(t["watchers"])})

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"board-{today}.json").write_text(
        json.dumps(snap, indent=1, ensure_ascii=False), encoding="utf-8")
    (OUT / "latest.json").write_text(
        json.dumps(snap, indent=1, ensure_ascii=False), encoding="utf-8")
    return snap


def report(snap: dict) -> None:
    ps, terr = snap["pieces"], snap["territory"]
    print(f"\n  BOARD at {snap['at']} — {len(ps)} pieces, {len(terr)} territory\n")

    if not ps:
        print("  No pieces. Every watched entity is a topic, so nothing on this")
        print("  board can take a move. Add actors to a model's watch list.")
        return

    print("  piece                     moves  seen by  played")
    for p in ps:
        flag = "  <- models disagree on its options" if p["contested_option_set"] else ""
        print(f"  {p['id']:<24} {p['moves_available']:>5}  {len(p['watchers']):>7}  "
              f"{len(p['moves_played']):>6}{flag}")

    # A move whose SUBJECT is another piece is on the wrong square. The board
    # makes this visible where a ledger does not: a regulator cannot "refuse to
    # respond" to its own request. Detected by looking for another piece's name
    # at the start of the move text, which is where the subject sits.
    names = {p["id"]: {p["id"].split("-")[0].lower(), p["name"].split()[0].lower()}
             for p in ps}
    wrong = []
    for p in ps:
        for m in p["moves"]:
            head = m["move"].lower()[:28]
            for other in ps:
                if other["id"] == p["id"]:
                    continue
                if any(n and n in head for n in names[other["id"]]):
                    wrong.append((p["id"], other["id"], m["move"]))
                    break
        # generic actor words that are plainly not this piece
        for m in p["moves"]:
            if m["move"].lower().startswith(("lab(", "labs ", "lab ", "provider"))                and "office" in p["id"]:
                wrong.append((p["id"], "(the labs)", m["move"]))
    if wrong:
        seen = set()
        uniq = [w for w in wrong if not (w[2] in seen or seen.add(w[2]))]
        print()
        print(f"  MOVES ON THE WRONG SQUARE ({len(uniq)}):")
        for owner, actual, mv in uniq[:8]:
            print(f"    {owner} lists a move belonging to {actual}")
            print(f"      {mv[:72]}")
        print("    An actor cannot play another actor's move. These inflate the")
        print("    owner's option count and will mis-attribute a played move.")

    thin = [p for p in ps if len(p["watchers"]) == 1]
    if thin:
        print(f"\n  thinly seen ({len(thin)}) — one model is the only source of")
        print("  this piece's option set, so its blind spots are the board's:")
        for p in thin:
            print(f"    {p['id']} (only {p['watchers'][0]})")

    played = [(p, m) for p in ps for m in p["moves_played"]]
    unlisted = [(p, m) for p, m in played if m["unlisted"]]
    print(f"\n  moves played: {len(played)}"
          + (f", {len(unlisted)} UNLISTED" if unlisted else ""))
    for p, m in unlisted:
        print(f"    !! {p['id']} played a move no model had on the board")
        print(f"       {m['claim']}")
    if not played:
        print("    Nothing graded yet, so this board is entirely declared")
        print("    option-space. Move history begins at the first resolution.")

    if terr:
        print(f"\n  territory ({len(terr)}) — contested ground, not players:")
        for t in terr[:10]:
            print(f"    {t['id']:<28} watched by {', '.join(t['watchers'])}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    if a.build or not (OUT / "latest.json").exists():
        snap = build()
        print(f"  wrote {OUT/'latest.json'}")
    else:
        snap = json.loads((OUT / "latest.json").read_text(encoding="utf-8"))
    report(snap)


if __name__ == "__main__":
    main()
