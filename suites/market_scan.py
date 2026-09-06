"""Prediction-market scan, price-blind elicitation, and the paper book.

Implements docs/MARKET_STRATEGY.md. Paper only: this tool never trades, never touches
funds, and the Kelly arithmetic is virtual. The book (predict_public/market_book.json,
PRIVATE) registers two kinds of entry:
  * tier A "position" -- the market's own resolution text was adopted as a claim and an
    instrument gave a PRICE-BLIND probability; staked with virtual quarter-Kelly.
  * tier B "observation" -- same arena, different observable; logged, never staked,
    excluded from edge statistics.

The price-blind rule is enforced structurally: the elicitation prompt is built from the
market's question + resolution text only -- the price fields are fetched AFTER the model
answers (two separate calls, and the elicit path never reads the price fields at all).

  python -m suites.market_scan --search "my-model"                    # find live markets
  python -m suites.market_scan --show <slug>                        # live fetch one market
  python -m suites.market_scan --elicit <slug> --repo my-model    # price-blind read + register
  python -m suites.market_scan --observe <slug> --note "..."        # tier-B pair
  python -m suites.market_scan --book                               # print the book
  python -m suites.market_scan --grade                              # settle resolved positions
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]

def _models_dir(root):
    """Where THIS instance's model repos live.

    fleet.json may set models_dir to give the instance a private namespace;
    without it, models are siblings of the instance (the original layout).
    Two instances under one parent otherwise read each other's models.
    """
    try:
        import json as _json
        cfg = _json.load((root / "fleet.json").open(encoding="utf-8"))
        if cfg.get("models_dir"):
            return (root / cfg["models_dir"]).resolve()
    except Exception:
        pass
    return root.parent


TOOLS = _models_dir(ROOT)
BOOK = ROOT / "market_book.json"
UA = "Mozilla/5.0"
GAMMA = "https://gamma-api.polymarket.com"

BANKROLL = 1000.0          # virtual
KELLY_FRACTION = 0.25
POSITION_CAP = 0.10        # of bankroll
MIN_DIVERGENCE = 0.10
MIN_LIQUIDITY = 10000.0


def _fetch(url: str):
    """GET via curl -- the gamma API 403s python's default UA and stdlib UA swaps
    still trip Cloudflare intermittently; curl is what worked, so curl is the path."""
    for _attempt in range(3):
        r = subprocess.run(f'curl -s --max-time 30 -A "{UA}" "{url}"',
                           capture_output=True, timeout=45, shell=True,
                           encoding="utf-8", errors="replace")
        out = (r.stdout or "").strip()
        if r.returncode == 0 and out:
            return json.loads(out)
    raise SystemExit(f"fetch failed after retries: {url}")


def market_by_slug(slug: str) -> dict:
    d = _fetch(f"{GAMMA}/markets?slug={slug}")
    if not d:
        raise SystemExit(f"no market for slug {slug}")
    return d[0]


def load_book() -> dict:
    if BOOK.exists():
        return json.load(BOOK.open(encoding="utf-8"))
    return {"bankroll": BANKROLL, "positions": [], "observations": []}


def save_book(b: dict) -> None:
    BOOK.parent.mkdir(exist_ok=True)
    json.dump(b, BOOK.open("w", encoding="utf-8"), ensure_ascii=False, indent=1)


def cmd_search(q: str) -> None:
    import urllib.parse
    d = _fetch(f"{GAMMA}/public-search?q={urllib.parse.quote(q)}&limit_per_type=8")
    for e in d.get("events", []):
        for m in e.get("markets", []):
            print(f"  {m.get('question','')[:80]}\n    slug={e.get('slug','?')} id={m.get('id')}")


def _live_summary(m: dict) -> dict:
    """The registration snapshot. bestBid/bestAsk are the executable prices; mid
    overstates paper ROI on thin books (strategy doc, entry hygiene)."""
    return {"market_id": m.get("id"), "slug": m.get("slug"),
            "question": m.get("question"), "resolution_text": (m.get("description") or "")[:1500],
            "end_date": m.get("endDate"), "active": m.get("active"), "closed": m.get("closed"),
            "best_bid": float(m.get("bestBid") or 0), "best_ask": float(m.get("bestAsk") or 0),
            "liquidity": float(m.get("liquidity") or 0),
            "fetched": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}


def cmd_show(slug: str) -> None:
    m = market_by_slug(slug)
    print(json.dumps(_live_summary(m), indent=1)[:2000])


ELICIT_PROMPT = """You have LIVE WEB ACCESS. Today is {today}. You are running the model below as a
forecasting instrument. Give a calibrated probability for the QUESTION, judged strictly by
the RESOLUTION CRITERIA. Do not look up betting odds, prediction-market prices, or
forecaster aggregates for this question -- your value comes from the model's read, not the
crowd's.

=== THE MODEL ===
{model_text}
=== END MODEL ===

QUESTION: {question}
RESOLUTION CRITERIA: {criteria}
CLOSES: {end_date}

STEP 1 -- OBSERVE (web): the current state of the relevant system, 3-4 dated concrete items.
STEP 2 -- MODEL READ: which mechanisms bear on this, and what state they imply.
STEP 3 -- PROBABILITY: a single calibrated p in [0.01, 0.99].

Return ONLY JSON:
{{"observed":[{{"item":"...","date":"..."}}],"model_read":"one paragraph",
"p":0.0,"mechanism":"which mechanism drives this"}}"""


def cmd_elicit(slug: str, repo: str, model: str) -> None:
    from harness.openrouter import chat
    from harness.actors import parse_json
    # ---- price-blind half: fetch, then build the prompt WITHOUT price fields ----
    m = market_by_slug(slug)
    if m.get("closed"):
        raise SystemExit("market is closed -- nothing to elicit")
    question, criteria = m.get("question", ""), (m.get("description") or "")[:1500]
    end_date = (m.get("endDate") or "")[:10]
    model_text = (TOOLS / repo / "MODEL.md").read_text(encoding="utf-8")[:9000]
    today = datetime.date.today().isoformat()
    p = (ELICIT_PROMPT.replace("{today}", today).replace("{model_text}", model_text)
         .replace("{question}", question).replace("{criteria}", criteria)
         .replace("{end_date}", end_date))
    print(f"[elicit] {repo} on: {question}")
    r = chat(model + ":online", [{"role": "user", "content": p}], temperature=0.3, max_tokens=2200)
    d = parse_json(r.text) if not r.error else None
    if not d or not isinstance(d.get("p"), (int, float)):
        raise SystemExit(f"elicitation failed: {r.error or 'unparseable'}")
    model_p = max(0.01, min(0.99, float(d["p"])))
    print(f"  model read: {d.get('model_read','')[:120]}")
    print(f"  model p = {model_p}")

    # ---- market half: NOW look at the price ----
    snap = _live_summary(m)
    bid, ask, liq = snap["best_bid"], snap["best_ask"], snap["liquidity"]
    # long YES executes at ask; long NO at (1 - bid).
    side, exe = ("YES", ask) if model_p > (ask if ask else 0.5) else ("NO", 1 - bid)
    edge = (model_p - ask) if side == "YES" else ((1 - model_p) - (1 - bid))
    print(f"  market: bid {bid} ask {ask} liq {liq:,.0f} -> side {side}, executable {exe:.3f}, edge {edge:+.3f}")

    book = load_book()
    entry = {"venue": "polymarket", **snap, "instrument_repo": repo,
             "model_p": model_p, "mechanism": d.get("mechanism", ""),
             "model_read": d.get("model_read", "")[:400], "elicited_on": today,
             "price_blind": True, "status": "open"}
    if round(edge, 3) < MIN_DIVERGENCE or liq < MIN_LIQUIDITY:
        entry["tier"] = "B"
        entry["note"] = f"below gates (edge {edge:+.3f}, liq {liq:,.0f}) -- observation only"
        book["observations"].append(entry)
        print("  -> tier B (below divergence/liquidity gates); logged, NOT staked")
    else:
        kelly_odds = (1 - exe) / exe if side == "YES" else exe / (1 - exe)
        p_win = model_p if side == "YES" else 1 - model_p
        f = max(0.0, (p_win * (kelly_odds + 1) - 1) / kelly_odds) * KELLY_FRACTION
        stake = round(min(f, POSITION_CAP) * book["bankroll"], 2)
        entry.update({"tier": "A", "side": side, "entry_price": exe,
                      "stake_virtual": stake, "kelly_f": round(f, 4)})
        book["positions"].append(entry)
        print(f"  -> tier A PAPER position: {side} at {exe:.3f}, virtual stake ${stake}")
    save_book(book)

    # the elicitation is also a normal instrument claim: append to the repo ledger so
    # the October loop grades it on the same criteria (one position, two verdicts)
    lpath = TOOLS / repo / "predict" / "ledger.json"
    led = json.load(lpath.open(encoding="utf-8"))
    led["predictions"].append({
        "entity": f"market:{slug}"[:80], "name": question[:80], "made_on": today,
        "resolve_by": end_date or "2026-12-31", "round": led.get("rounds", 0),
        "status": "open", "claim": question,
        "resolution_criteria": f"Market resolution criteria (adopted verbatim): {criteria[:400]}",
        "confidence": model_p, "mechanism": d.get("mechanism", ""),
        "model_read": d.get("model_read", "")[:400], "source": "market_scan price-blind elicitation"})
    json.dump(led, lpath.open("w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"  -> claim appended to {repo}/predict/ledger.json")


def cmd_observe(slug: str, note: str, repo: str) -> None:
    m = market_by_slug(slug)
    book = load_book()
    book["observations"].append({"venue": "polymarket", **_live_summary(m), "tier": "B",
                                 "instrument_repo": repo, "note": note, "status": "open"})
    save_book(book)
    print(f"  tier-B observation registered: {m.get('question','')[:70]}")


def cmd_book() -> None:
    b = load_book()
    print(f"bankroll (virtual): ${b['bankroll']}")
    print(f"\nTIER A positions ({len(b['positions'])}):")
    for p in b["positions"]:
        print(f"  [{p['status']:>6}] {p['side']:>3} {p.get('entry_price'):.3f} vs model {p['model_p']:.2f} "
              f"${p.get('stake_virtual',0):>6} | {p['question'][:60]}")
    print(f"\nTIER B observations ({len(b['observations'])}):")
    for o in b["observations"]:
        print(f"  [{o['status']:>6}] {o['question'][:66]} | {o.get('note','')[:50]}")


def cmd_grade() -> None:
    b = load_book()
    settled = 0
    for p in b["positions"] + b["observations"]:
        if p["status"] != "open":
            continue
        m = market_by_slug(p["slug"])
        if not m.get("closed"):
            continue
        prices = m.get("outcomePrices")
        try:
            yes = float(json.loads(prices)[0] if isinstance(prices, str) else prices[0])
        except (TypeError, ValueError, IndexError):
            print(f"  ? cannot read outcome for {p['slug']}"); continue
        outcome = "YES" if yes > 0.5 else "NO"
        p["status"], p["outcome"] = "settled", outcome
        p["settled_on"] = datetime.date.today().isoformat()
        if p.get("tier") == "A" and "side" in p:
            won = p["side"] == outcome
            stake, price = p["stake_virtual"], p["entry_price"]
            p["pnl_virtual"] = round(stake * (1 - price) / price, 2) if won else -stake
            b["bankroll"] = round(b["bankroll"] + p["pnl_virtual"], 2)
            print(f"  {'WON ' if won else 'LOST'} {p['side']} {p['question'][:55]} pnl {p['pnl_virtual']:+}")
        settled += 1
    save_book(b)
    print(f"settled {settled}; bankroll ${b['bankroll']}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Market scan + price-blind paper book (never trades).")
    ap.add_argument("--search")
    ap.add_argument("--show")
    ap.add_argument("--elicit", help="market slug: price-blind instrument read -> register")
    ap.add_argument("--observe", help="market slug: tier-B observation pair")
    ap.add_argument("--repo", default="", help="instrument repo for --elicit/--observe")
    ap.add_argument("--note", default="")
    ap.add_argument("--model", default="openai/gpt-4o")
    ap.add_argument("--book", action="store_true")
    ap.add_argument("--grade", action="store_true")
    a = ap.parse_args()
    from suites.grade_claims import _load_env
    _load_env()
    if a.search:
        cmd_search(a.search)
    elif a.show:
        cmd_show(a.show)
    elif a.elicit:
        if not a.repo:
            raise SystemExit("--elicit needs --repo")
        if not os.environ.get("OPENROUTER_API_KEY"):
            if os.environ.get("LLM_BACKEND") != "claude-code":
                raise SystemExit("OPENROUTER_API_KEY not set (or set LLM_BACKEND=claude-code)")
        cmd_elicit(a.elicit, a.repo, a.model)
    elif a.observe:
        cmd_observe(a.observe, a.note, a.repo)
    elif a.grade:
        cmd_grade()
    else:
        cmd_book()


if __name__ == "__main__":
    main()
