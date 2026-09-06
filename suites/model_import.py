"""Import an external model — someone else's analysis — as a POV, and open a
ledger on its predictions.

The engine already turns a *topic* into a POV (POV_CREATOR.md). This turns a
*person's reasoning* into one. An external analyst's worldview is an original
theory with no reality pack, which is exactly the case `povs/my-model.md`
already solved: grade it on the THEORY-STATUS ladder, not on evidence tiers.

Two outputs, deliberately separate:

  1. povs/imported/<slug>.md   — their model, in the engine's own POV schema, so
     every downstream task (classifier, parallel-map, gap-finder) accepts it.
  2. imports/<slug>.claims.jsonl — their dated, falsifiable claims, in the
     prediction-ledger's schema, so accuracy accrues over time.

TWO DISCIPLINES, enforced structurally rather than by intention:

  * NO HINDSIGHT. The extractor sees the transcript and the publish date. It does
    not browse, and it is told the publish date is its epistemic cutoff. Grading is
    a SEPARATE pass, run later, by a different call. If extraction could see
    outcomes it would select and phrase claims toward what happened, and the whole
    accuracy measurement would be theatre.
  * CRITERIA BEFORE OUTCOME. Resolution criteria are written at extraction time and
    frozen. This mirrors the prediction-ledger's pre-registration; here the claim
    predates us, so the criteria are what we commit to before checking anything.

Claims are written to a SEPARATE store, never appended into the prediction-ledger's
`ledger_public.json`. That ledger's integrity rests on pre-registration + sealed
reasoning; an imported claim has different evidentiary status (publication-dated,
criteria authored after the fact by us) and must not be silently mixed in.

Usage:
    python -m suites.model_import --url https://youtu.be/aV26V1UvkJw
    python -m suites.model_import --transcript inbox/transcript_X.txt \
        --source inbox/source_X.json --model openai/gpt-5
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.openrouter import chat  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------
# Prompt 1 — the model behind the analysis
# --------------------------------------------------------------------------

POV_PROMPT = """You are extracting the MODEL OF THE WORLD held by a speaker, from a
transcript of them talking. You are not summarizing the conversation. You are
recovering the machinery that generates their views: what they think drives what.

SPEAKER TO EXTRACT: {speaker}
SOURCE: {title} ({channel}), published {published}
EPISTEMIC CUTOFF: {published}. You know nothing after this date. Do not use
hindsight, do not comment on whether they turned out right, and do not import
outside facts. Work only from the transcript.

Produce a POV file body with EXACTLY these sections:

# POV — {slug}

## Provenance
Who, from where, when, and what fraction of the transcript is this speaker.

## POV declaration
- **DOMAIN** — what this person's model is about, scoped precisely.
- **STANCE / ROLE** — their position relative to the domain (what they sell, run,
  or are invested in). State conflicts of interest plainly; they shape the model.
- **WHAT MATTERS** — the values/interests weighting their analysis. Push past topic
  to the real cut.
- **THE FIREHOSE** — the sources they actually draw on (data they cite, access they
  have, what they appear to read).
- **CONFIDENCE LENS** — use the THEORY-STATUS ladder, because this is one person's
  model and no reality pack exists:
  ASSERTED-PREMISE / DERIVED-CONSEQUENCE / PARAMETER-DEPENDENT /
  OPEN-BY-ADMISSION / EXTERNAL-CLAIM.
- **COMPARISON FRAME** — only if they themselves lean on an analogy. Name where it
  breaks. Omit if they don't; a forced analog is worse than none.

## The mechanism
The 3-6 causal claims that do the actual work, each tagged with its theory-status
tier. Show what rests on what: which are premises, which are consequences.

## Load-bearing assumptions
What must be true for the model to hold, that they assert rather than argue.

## What this model cannot answer
Where they say "I don't know", hedge, or the mechanism runs out. Be specific.

## Where it could break
The strongest rival explanation, and the observable that would discriminate.

Rules: quote sparingly (under 15 words per quote) and cite the locator --
the [HH:MM:SS] block for a transcript, or the section heading for an article.
Never present an asserted premise as an established fact. If they contradict
themselves, say so rather than smoothing it. Return the markdown only.

TRANSCRIPT:
{transcript}
"""


# --------------------------------------------------------------------------
# Prompt 2 — the falsifiable claims
# --------------------------------------------------------------------------

CLAIMS_PROMPT = """From this transcript, extract every FALSIFIABLE, DATED prediction
made by {speaker}.

SOURCE: {title} ({channel}), published {published}
EPISTEMIC CUTOFF: {published}. You do not know what happened after this date.
Do NOT assess whether any claim came true. Do NOT let plausibility-in-hindsight
influence what you extract or how you phrase it. You are opening a ledger, not
grading one.

IF the text contains `===== POST <date> :: <title> =====` banners, it is an archive
of separate dated pieces. Then: `made_on` is THAT POST'S date, not the newest one,
and each claim's epistemic cutoff is its own post's date. Put the post title in
`locator`. Some posts are marked FREE PREVIEW ONLY — the paid analysis is not
included; extract only from what is present and never infer what the hidden part said.

A claim qualifies ONLY if all four hold:
  1. It asserts something about the world, not a preference or a value judgement.
  2. It has a time horizon — stated ("by 2027", "within two years") or clearly
     implied. If implied, say so in `horizon_basis`.
  3. An observer could check it with public information at the resolve date.
  4. It could come out false. "AI will be important" fails; so does anything whose
     truth is already settled at the cutoff.

For each, write RESOLUTION CRITERIA NOW, before anyone knows the outcome: the exact
observable that settles it, sourced from something checkable (a filing, a
published figure, an announcement). If you cannot write criteria that would settle
it cleanly, drop the claim — a vague claim in a ledger is worse than none.

`resolve_by` is the date the claim can FIRST be checked — the end of its stated
horizon plus only the lag for the settling source to publish (a quarter or two,
not a year). A claim about "by end of 2028" resolves 2029-03-31 if it needs an
annual report, not 2029-12-31. Do not pad.

Assign `speaker_p`: the probability THEY appear to hold, from their hedging.
"definitely/certain" ~0.95 · "almost certainly" ~0.9 · "likely/I think" ~0.7 ·
"maybe/could" ~0.5 · "I doubt" ~0.25. Record the hedge words in `hedge`.

BE THOROUGH. A long interview with a forecaster typically contains 10-20 qualifying
claims — numbers with dates attached, market sizes, capacity figures, shares,
timelines, who-will-do-what-by-when. Sweep the WHOLE transcript end to end; do not
stop after the first few. Claims made in passing count if they meet the four tests.

Return a JSON array. No prose, no code fences. Each element:
{{
  "claim": "<one sentence, the prediction as they made it>",
  "criteria": "<the exact observable that resolves it, and where to check>",
  "made_on": "{published}",
  "resolve_by": "<YYYY-MM-DD>",
  "horizon_basis": "stated" | "implied: <why>",
  "speaker_p": <0.0-1.0>,
  "hedge": "<their hedge words verbatim>",
  "topic": "<short topic label>",
  "locator": "<[HH:MM:SS] for a transcript, or the section heading for an article>",
  "quote": "<under 15 words, verbatim>"
}}

This is ONE EXCERPT of a longer interview, so extract everything qualifying
in it -- do not ration against some whole-interview budget. If there are
genuinely none, return [].

TRANSCRIPT:
{transcript}
"""


# A reasoning model given a 77-minute transcript and one big budget will spend it
# all on thinking. Bound the input per call instead.
CHUNK_CHARS = 26_000
CLAIM_TOKENS = 14_000

# A mechanism with fewer than CLUSTER_FLOOR claims cannot be calibrated -- a
# Brier score over one or two outcomes is noise, not a track record.
CLUSTER_FLOOR = 3
CLUSTER_LO = 3
CLUSTER_HI = 7


def _excerpts_for(transcript: str, stamps: list[str], window: int = 2) -> str:
    """The transcript blocks around this model's claims, plus a little context.

    Each sub-model POV should be written from ITS OWN evidence, not from the whole
    interview -- otherwise every model reads like the same worldview restated.
    """
    lines = transcript.splitlines()
    want = {re.sub(r"[^\d:]", "", s) for s in stamps if s}
    keep: set[int] = set()
    for i, ln in enumerate(lines):
        m = re.match(r"\[(\d{2}:\d{2}:\d{2})\]", ln)
        if m and m.group(1) in want:
            keep.update(range(max(0, i - window), min(len(lines), i + window + 1)))
    if not keep:
        return transcript[:CHUNK_CHARS]
    out, prev = [], -2
    for i in sorted(keep):
        if i != prev + 1:
            out.append("...")
        out.append(lines[i])
        prev = i
    return "\n".join(out)[:CHUNK_CHARS]


def _chunk(text: str, size: int) -> list[str]:
    """Split on line boundaries so timestamped blocks stay intact."""
    lines = text.splitlines(keepends=True)
    out, cur, n = [], [], 0
    for ln in lines:
        if n + len(ln) > size and cur:
            out.append("".join(cur))
            cur, n = [], 0
        cur.append(ln)
        n += len(ln)
    if cur:
        out.append("".join(cur))
    return out


def _dedupe(claims: list[dict]) -> list[dict]:
    """Chunk boundaries can restate a claim; keep the first of each."""
    seen, out = set(), []
    for c in claims:
        k = re.sub(r"[^a-z0-9]", "", str(c.get("claim", "")).lower())[:70]
        if k and k not in seen:
            seen.add(k)
            out.append(c)
    return out


CLUSTER_PROMPT = """You are splitting one analyst's predictions into SEPARATE MODELS.

A person is not one model. {speaker} may forecast semiconductor supply well and
macroeconomics badly, and a single blended accuracy score would hide exactly that.
Each distinct MECHANISM they rely on becomes its own model, scored on its own.

Group these claims by the mechanism that generates them — the causal story that
must hold for the claim to come true. Two claims belong together only if the SAME
premises make them right or wrong. Claims that share a topic label but rest on
different mechanisms belong apart; claims with different topic labels that rest on
the same mechanism belong together.

Rules:
  - A cluster needs at least {floor} claims. A mechanism with fewer is not
    scoreable — put those claims in "unclustered".
  - You MUST return at least {lo} clusters when the claims support it. One
    cluster covering everything is a FAILED split: a forecaster's compute-supply
    reasoning, their geopolitical reasoning, and their macro reasoning are
    different machines that can be right or wrong independently. Separate them.
  - Aim for {lo}-{hi} clusters.
  - Name each cluster for its MECHANISM, not its topic. "Compute demand outruns
    fab supply" not "semiconductors".

Return JSON only, no fences:
{{
  "clusters": [
    {{
      "name": "<short mechanism name>",
      "slug": "<kebab-case, max 32 chars>",
      "mechanism": "<2-3 sentences: the causal story, and what must hold>",
      "premises": ["<the load-bearing assumptions THIS cluster rests on>"],
      "breaks_if": "<the observable that would falsify the mechanism itself>",
      "claim_ids": ["<id>", "<id>", ...]
    }}
  ],
  "unclustered": ["<id>", ...]
}}

Every id appears exactly once, in a cluster or in unclustered.

CLAIMS:
{claims}
"""


def _slug(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s.lower()).strip("-")
    return re.sub(r"-+", "-", s)[:48]


def _parse_json_array(text: str) -> list[dict]:
    """Models wrap JSON in fences or prose more often than not."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.MULTILINE).strip()
    try:
        v = json.loads(t)
        return v if isinstance(v, list) else [v]
    except json.JSONDecodeError:
        pass
    start = t.find("[")
    end = t.rfind("]")
    if start != -1 and end > start:
        try:
            return json.loads(t[start:end + 1])
        except json.JSONDecodeError:
            pass
    return []


def _validate(claims: list[dict], published: str) -> tuple[list[dict], list[str]]:
    """Structural gate. A claim that cannot be scored later does not enter the store."""
    ok, rejected = [], []
    required = ("claim", "criteria", "resolve_by", "speaker_p")
    for i, c in enumerate(claims):
        missing = [f for f in required if not c.get(f)]
        if missing:
            rejected.append(f"[{i}] missing {','.join(missing)}")
            continue
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(c.get("resolve_by", ""))):
            rejected.append(f"[{i}] bad resolve_by: {c.get('resolve_by')!r}")
            continue
        # In archive mode each claim carries its OWN post date, so validate against
        # that -- a 2024 post's claim resolving in 2025 is perfectly valid even
        # though the newest post in the archive is 2026.
        made = str(c.get("made_on") or "")
        cutoff = made if re.match(r"^\d{4}-\d{2}-\d{2}$", made) else published
        if str(c["resolve_by"]) <= cutoff:
            rejected.append(f"[{i}] resolve_by {c['resolve_by']} not after made_on {cutoff}")
            continue
        try:
            p = float(c["speaker_p"])
        except (TypeError, ValueError):
            rejected.append(f"[{i}] speaker_p not a number")
            continue
        if not 0.0 <= p <= 1.0:
            rejected.append(f"[{i}] speaker_p out of range: {p}")
            continue
        c["speaker_p"] = p
        # Soft check: a resolve date far past the horizon named in the claim text
        # means the claim sits "open" long after it was checkable. Flag, don't drop
        # -- the horizon is sometimes genuinely distant.
        yrs = re.findall(r"\b(20\d{2})\b", c["claim"])
        if yrs:
            horizon = max(int(y) for y in yrs)
            if int(c["resolve_by"][:4]) > horizon + 1:
                c["resolve_lag_flag"] = (
                    f"resolve_by {c['resolve_by']} is >1y after claim horizon {horizon}"
                )
        ok.append(c)
    return ok, rejected


SUBMODEL_PROMPT = """Write the POV file body for ONE model held by {speaker} — not
their whole worldview, only the mechanism below and the claims it generates.

SOURCE: {title} ({channel}), published {published}
EPISTEMIC CUTOFF: {published}. No hindsight, no outside facts, no assessment of
whether they turned out right. Work only from the transcript excerpts given.

MECHANISM: {name}
{mechanism}

PREMISES THEY RELY ON: {premises}
WHAT WOULD BREAK IT: {breaks_if}

THIS MODEL'S CLAIMS:
{claims}

RELEVANT TRANSCRIPT:
{excerpts}

Produce exactly:

# POV — {slug}

## Provenance
Who, from where, when. State that this is ONE of several models extracted from this
speaker, and name the mechanism it covers.

## POV declaration
- **DOMAIN** — what THIS mechanism is about, scoped tightly. Not their whole field.
- **STANCE / ROLE** — their position, and any conflict of interest that bears on
  THIS mechanism specifically.
- **WHAT MATTERS** — what this mechanism is for; what it is trying to predict.
- **THE FIREHOSE** — the data THIS mechanism runs on.
- **CONFIDENCE LENS** — theory-status ladder: ASSERTED-PREMISE /
  DERIVED-CONSEQUENCE / PARAMETER-DEPENDENT / OPEN-BY-ADMISSION / EXTERNAL-CLAIM.
- **COMPARISON FRAME** — only if they lean on one for THIS mechanism; name where it
  breaks. Omit otherwise.

## The mechanism
The causal chain, step by step, each step tagged with its theory-status tier. Show
what rests on what.

## Load-bearing assumptions
What must hold for THIS model, that they assert rather than argue.

## What this model cannot answer
Where it runs out, in their own words where possible.

## Where it could break
The strongest rival explanation for the same predictions, and the observable that
would discriminate between them.

## Predictions this model makes
The claims above as a list, each with their stated confidence and resolve date.

Quote under 15 words, cite the locator (timestamp or section). Return markdown only.
"""


def _cluster_claims(claims: list[dict], speaker: str, model: str,
                    floor: int, lo: int, hi: int) -> dict:
    """Split one speaker's claims into per-mechanism models."""
    brief = "\n".join(
        f"{c['id']}: [{c.get('topic','')}] {c['claim']}" for c in claims
    )
    p = CLUSTER_PROMPT.format(speaker=speaker, claims=brief, floor=floor, lo=lo, hi=hi)
    r = chat(model, [{"role": "user", "content": p}], temperature=0.1, max_tokens=14000)
    if r.error:
        raise SystemExit(f"clustering failed: {r.error}")
    if not r.text.strip():
        fr = ((r.raw.get("choices") or [{}])[0]).get("finish_reason")
        raise SystemExit(f"clustering returned no text (finish_reason={fr})")

    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", r.text.strip(), flags=re.MULTILINE).strip()
    s, e = t.find("{"), t.rfind("}")
    try:
        out = json.loads(t if s == -1 else t[s:e + 1])
    except json.JSONDecodeError as exc:
        raise SystemExit(f"clustering returned unparseable JSON: {exc}")

    by_id = {c["id"]: c for c in claims}
    seen: set[str] = set()
    clusters = []
    for cl in out.get("clusters", []):
        ids = [i for i in cl.get("claim_ids", []) if i in by_id and i not in seen]
        if len(ids) < floor:
            continue                      # not scoreable; its claims fall through
        seen.update(ids)
        cl["claim_ids"] = ids
        clusters.append(cl)
    unclustered = [c["id"] for c in claims if c["id"] not in seen]
    return {"clusters": clusters, "unclustered": unclustered}


def run(source: dict, transcript: str, speaker: str, model: str,
        outdir: Path, max_chars: int, reason_model: str | None = None) -> dict:
    reason_model = reason_model or model
    published = source.get("published", "")
    slug = _slug(f"{speaker}-{source.get('video_id','')}")
    body = transcript[:max_chars]
    truncated = len(transcript) > max_chars

    ctx = dict(speaker=speaker, title=source.get("title", ""),
               channel=source.get("channel", ""), published=published,
               slug=slug, transcript=body)

    print(f"  [1/4] extracting worldview  ({reason_model}) ...", flush=True)
    r1 = chat(reason_model, [{"role": "user", "content": POV_PROMPT.format(**ctx)}],
              temperature=0.2, max_tokens=16000)
    if r1.error:
        raise SystemExit(f"POV extraction failed: {r1.error}")
    if not r1.text.strip():
        fr = ((r1.raw.get("choices") or [{}])[0]).get("finish_reason")
        raise SystemExit(
            f"POV extraction returned no text (finish_reason={fr}). A reasoning "
            f"model can spend the whole completion budget thinking -- raise "
            f"max_tokens or shorten the transcript."
        )

    # Claims are extracted in transcript CHUNKS. One pass over a 77-minute
    # transcript makes a reasoning model spend its whole completion budget
    # thinking and emit nothing (finish_reason=length, 0 chars). Chunking bounds
    # each call and, as a side effect, forces a sweep of the whole transcript
    # instead of a front-loaded skim.
    chunks = _chunk(body, CHUNK_CHARS)
    claims: list[dict] = []
    for i, ch in enumerate(chunks, 1):
        print(f"  [2/4] extracting claims ({model}) chunk {i}/{len(chunks)} ...", flush=True)
        cctx = dict(ctx, transcript=ch)
        r2 = chat(model, [{"role": "user", "content": CLAIMS_PROMPT.format(**cctx)}],
                  temperature=0.1, max_tokens=CLAIM_TOKENS)
        if r2.error:
            print(f"        chunk {i} failed: {r2.error}")
            continue
        got = _parse_json_array(r2.text)
        if not got and not r2.text.strip():
            fr = ((r2.raw.get("choices") or [{}])[0]).get("finish_reason")
            print(f"        chunk {i} returned no text (finish_reason={fr})")
        claims.extend(got)
    claims = _dedupe(claims)
    claims, rejected = _validate(claims, published)

    for i, c in enumerate(claims, 1):
        c["id"] = f"{slug}.{i:02d}"

    # A person is not one model. Split their claims by MECHANISM so each is
    # scored on its own -- someone can forecast supply chains well and
    # macroeconomics badly, and one blended number would hide that.
    print(f"  [3/4] clustering into parallel models ({reason_model}) ...", flush=True)
    grouped = _cluster_claims(claims, speaker, reason_model, CLUSTER_FLOOR,
                              CLUSTER_LO, CLUSTER_HI)
    by_id = {c["id"]: c for c in claims}

    pov_dir = ROOT / "povs" / "imported"
    pov_dir.mkdir(parents=True, exist_ok=True)
    outdir.mkdir(parents=True, exist_ok=True)

    def _rec(c: dict, mslug: str, mname: str) -> dict:
        rec = {
            "id": c["id"],
            "model": mslug,            # which parallel model this scores
            "mechanism": mname,
            "analyst": speaker,
            "source_url": source.get("url", ""),
            "source_title": source.get("title", ""),
            "made_on": c.get("made_on") or published,
            "resolve_by": c["resolve_by"],
            "claim": c["claim"],
            "criteria": c["criteria"],
            "speaker_p": c["speaker_p"],
            "hedge": c.get("hedge", ""),
            "horizon_basis": c.get("horizon_basis", ""),
            "topic": c.get("topic", ""),
            "locator": c.get("locator") or c.get("timestamp", ""),
            "quote": c.get("quote", ""),
            "status": "open",          # open | hit | partial | miss | unresolvable
            "graded_on": None,
            "what_happened": None,
            "extracted_by": model,
            "criteria_frozen": True,   # written before any outcome check
        }
        if c.get("resolve_lag_flag"):
            rec["resolve_lag_flag"] = c["resolve_lag_flag"]
        return rec

    models = []
    for n, cl in enumerate(grouped["clusters"], 1):
        mslug = f"{slug}-{_slug(cl.get('slug') or cl.get('name','model'))}"[:80]
        mine = [by_id[i] for i in cl["claim_ids"]]

        # Only the transcript around THIS model's claims, so each POV is written
        # from its own evidence rather than the whole interview.
        stamps = [c.get("locator", "") for c in mine if c.get("locator")]
        excerpts = _excerpts_for(body, stamps)

        print(f"  [4/4] writing model {n}/{len(grouped['clusters'])}: {cl.get('name','')}", flush=True)
        sctx = dict(
            speaker=speaker, title=source.get("title", ""),
            channel=source.get("channel", ""), published=published,
            slug=mslug, name=cl.get("name", ""), mechanism=cl.get("mechanism", ""),
            premises="; ".join(cl.get("premises", []) or []),
            breaks_if=cl.get("breaks_if", ""),
            claims="\n".join(
                f"- {c['claim']}  (their confidence {c['speaker_p']}, resolves {c['resolve_by']})"
                for c in mine),
            excerpts=excerpts,
        )
        rs = chat(reason_model, [{"role": "user", "content": SUBMODEL_PROMPT.format(**sctx)}],
                  temperature=0.2, max_tokens=12000)
        if rs.error or not rs.text.strip():
            print(f"        model {n} POV failed ({rs.error or 'empty'}); claims still written")
            pov_text = f"# POV — {mslug}\n\n_POV generation failed; claims recorded._\n"
        else:
            pov_text = rs.text.strip() + "\n"

        header = (
            f"<!-- IMPORTED PARALLEL MODEL {n} of {len(grouped['clusters'])} from "
            f"{source.get('url','')}\n"
            f"     analyst={speaker} · mechanism={cl.get('name','')}\n"
            f"     transcript only · epistemic cutoff {published} · extractor={model}\n"
            f"     One person's model, not a verified account. Theory-status lens applies. -->\n\n"
        )
        ppath = pov_dir / f"{mslug}.md"
        ppath.write_text(header + pov_text, encoding="utf-8")

        cpath = outdir / f"{mslug}.claims.jsonl"
        with cpath.open("w", encoding="utf-8") as f:
            for c in mine:
                f.write(json.dumps(_rec(c, mslug, cl.get("name", "")),
                                   ensure_ascii=False) + "\n")

        models.append({
            "slug": mslug, "name": cl.get("name", ""),
            "mechanism": cl.get("mechanism", ""),
            "premises": cl.get("premises", []), "breaks_if": cl.get("breaks_if", ""),
            "n_claims": len(mine), "pov": str(ppath), "claims": str(cpath),
            "claim_ids": cl["claim_ids"],
        })

    # Claims that belong to no scoreable mechanism are kept, but parked: they
    # never get a headline score, because 1-2 claims cannot calibrate anything.
    unc = [by_id[i] for i in grouped["unclustered"] if i in by_id]
    unc_path = None
    if unc:
        unc_path = outdir / f"{slug}-unclustered.claims.jsonl"
        with unc_path.open("w", encoding="utf-8") as f:
            for c in unc:
                f.write(json.dumps(_rec(c, f"{slug}-unclustered", "(no scoreable mechanism)"),
                                   ensure_ascii=False) + "\n")

    # The whole-worldview POV is kept as an INDEX over the parallel models,
    # not as the product.
    idx_path = pov_dir / f"{slug}-index.md"
    idx = [
        f"<!-- INDEX. {len(models)} parallel models extracted from {source.get('url','')} -->\n",
        f"# Imported analyst — {speaker}\n",
        f"Source: {source.get('title','')} ({source.get('channel','')}), "
        f"published {published}. Extracted {len(claims)} claims into "
        f"{len(models)} scoreable models.\n",
        "## Parallel models\n",
    ]
    for m in models:
        idx.append(f"- **{m['name']}** — `{m['slug']}` — {m['n_claims']} claims  \n"
                   f"  {m['mechanism']}  \n"
                   f"  _Breaks if:_ {m['breaks_if']}\n")
    if unc:
        idx.append(f"\n## Unclustered ({len(unc)} claims)\n\nBelow the "
                   f"{CLUSTER_FLOOR}-claim floor for scoring; recorded, never "
                   f"given a headline score.\n")
    idx.append("\n## The speaker's whole worldview\n\n" + r1.text.strip() + "\n")
    idx_path.write_text("\n".join(idx), encoding="utf-8")

    meta = {
        "slug": slug, "analyst": speaker, "source": source,
        "extractor_model": model, "claims_extracted": len(claims),
        "claims_rejected": rejected, "transcript_truncated": truncated,
        "models": models, "n_models": len(models),
        "unclustered": [c["id"] for c in unc],
        "unclustered_path": str(unc_path) if unc_path else None,
        "index": str(idx_path),
    }
    (outdir / f"{slug}.import.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return meta


def main() -> None:
    # Load .env before any chat() call. Without this the backend
    # setting in .env is invisible and the suite reports 'no key'
    # while .env sits there correctly configured.
    from suites.grade_claims import _load_env
    _load_env()
    ap = argparse.ArgumentParser(description="Import an external analyst's model as a POV + claims ledger.")
    ap.add_argument("--url", help="YouTube URL (ingests first)")
    ap.add_argument("--transcript", help="path to an already-ingested transcript .txt")
    ap.add_argument("--source", help="path to the matching source_*.json")
    ap.add_argument("--posts", help="path to an ingest_substack index_*.json -- imports "
                                    "MANY posts as ONE analyst, so mechanisms merge across "
                                    "pieces and legitimacy accumulates over a real archive")
    ap.add_argument("--speaker", help="whose model to extract (default: infer from title)")
    # Two roles, two models. Claim extraction is high-volume STRUCTURED work: a
    # reasoning model burns its completion budget thinking and emits little or
    # nothing (measured on the pilot: gpt-5 yielded 4-17 claims run to run, with
    # empty finish_reason=length responses; sonnet-4 yielded 35 consistently, in
    # a fifth of the tokens). Clustering IS reasoning, so it keeps the stronger model.
    ap.add_argument("--model", default=os.environ.get("IMPORT_MODEL", "anthropic/claude-sonnet-4"),
                    help="extraction model (structured, high-volume)")
    ap.add_argument("--reason-model", default=os.environ.get("IMPORT_REASON_MODEL", "openai/gpt-5"),
                    help="clustering/POV model (reasoning)")
    ap.add_argument("--outdir", default=str(ROOT / "imports"))
    ap.add_argument("--inbox", default=str(ROOT / "inbox"))
    ap.add_argument("--max-chars", type=int, default=120_000)
    a = ap.parse_args()

    if a.posts:
        # Many posts, one analyst. Each is separated by a dated banner so the
        # extractor can attribute every claim to the piece that made it -- the
        # publish date is that claim's epistemic cutoff, not the newest post's.
        idx = json.loads(Path(a.posts).read_text(encoding="utf-8"))
        idx.sort(key=lambda p: p.get("published", ""))
        parts, paywalled = [], 0
        for p in idx:
            t = Path(p["text_path"])
            if not t.exists():
                continue
            if p.get("paywalled"):
                paywalled += 1
            banner = (
                f"\n\n===== POST {p['published']} :: {p['title']} "
                f"({'FREE PREVIEW ONLY' if p.get('paywalled') else 'FULL'}) =====\n"
            )
            parts.append(banner + t.read_text(encoding="utf-8"))
        transcript = "".join(parts)
        pub = idx[0].get("publication", "")
        src = {
            "video_id": re.sub(r"[^a-z0-9]+", "-", pub.lower()).strip("-")[:32],
            "url": f"https://{pub}/archive",
            "title": f"{pub} archive ({idx[0]['published']} .. {idx[-1]['published']})",
            "channel": pub,
            "published": idx[-1].get("published", ""),   # newest; per-claim dates come from banners
            "n_posts": len(idx), "paywalled_posts": paywalled,
        }
        print(f"  {len(idx)} posts, {paywalled} preview-only, "
              f"{idx[0]['published']} .. {idx[-1]['published']}")
    elif a.url:
        from harness.ingest_youtube import ingest
        from dataclasses import asdict
        src = asdict(ingest(a.url, Path(a.inbox)))
        transcript = Path(src["transcript_path"]).read_text(encoding="utf-8")
    elif a.transcript and a.source:
        src = json.loads(Path(a.source).read_text(encoding="utf-8"))
        transcript = Path(a.transcript).read_text(encoding="utf-8")
    else:
        raise SystemExit("need --url, --posts, or both --transcript and --source")

    speaker = a.speaker
    if not speaker:
        t = src.get("title", "")
        m = re.match(r"\s*([^—\-–|]{3,40}?)\s*[—\-–|]", t)
        speaker = (m.group(1).strip() if m else src.get("channel", "the speaker"))
        print(f"  speaker inferred: {speaker!r}  (override with --speaker)")

    print(f"importing: {src.get('title','')!r}")
    print(f"  published {src.get('published')} · cutoff enforced · {len(transcript):,} chars")
    meta = run(src, transcript, speaker, a.model, Path(a.outdir), a.max_chars,
               reason_model=a.reason_model)
    print(f"\n  {meta['claims_extracted']} claims -> {meta['n_models']} parallel models\n")
    for m in meta["models"]:
        print(f"    {m['slug']}")
        print(f"      {m['name']}  ({m['n_claims']} claims)")
        print(f"      POV    {m['pov']}")
        print(f"      claims {m['claims']}")
    if meta["unclustered"]:
        print(f"\n  unclustered ({len(meta['unclustered'])}): {meta['unclustered_path']}")
    print(f"\n  index  -> {meta['index']}")
    if meta["claims_rejected"]:
        print(f"  rejected {len(meta['claims_rejected'])}: {meta['claims_rejected'][:5]}")


if __name__ == "__main__":
    main()
