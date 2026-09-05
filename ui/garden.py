"""The Model Garden — browse, filter and take models others have published.

Two ways in:

  LOCAL   the cockpit's Garden tab renders whatever index it can reach, so the
          same page works offline against your own models.
  PUBLIC  the same renderer runs on the website against garden/index.json, a
          list of v1 cards submitted by their authors.

Submission is a form, not an upload: an author sends a GitHub repo URL. Their
own profile is the accountability — a throwaway account with no history is
visible as such, and nothing here hosts anyone else's code.

Conventions borrowed from package registries, because people already know them:
  · search across name, mechanism and author
  · facet filters (kind, level, scope, evidence, sensitivity)
  · one obvious "how do I take this" command per card
  · the record shown as counts, never as a score to be gamed
"""
from __future__ import annotations

import json
from pathlib import Path

GARDEN_PAGE = """
<div class="card">
  <h3>Model Garden <span class="muted" style="font-weight:400;font-size:.8rem">
    · browse and take models others published</span></h3>
  <p class="muted" style="font-size:.83rem">Every entry is a git repo following the
  <span class="mono">v1</span> format: a theory with premises, at least one falsifiable
  consequence, and a deletion clause. Records are <b>counts</b>, not scores &mdash; a model
  is judged by its own grading, never by a reviewer's opinion.</p>

  <div style="display:flex;gap:.5rem;flex-wrap:wrap;margin:.8rem 0">
    <input id="g-q" placeholder="search name, mechanism, author…" oninput="gRender()"
      style="flex:1;min-width:14rem;background:var(--bg);border:1px solid var(--line);
             border-radius:999px;color:var(--ink);padding:.5rem .9rem;font:inherit;font-size:.88rem">
  </div>
  <div id="g-facets" style="display:flex;gap:1.2rem;flex-wrap:wrap;margin:.2rem 0 .9rem"></div>
  <div id="g-count" class="muted" style="font-size:.78rem;margin-bottom:.4rem"></div>
  <div id="g-list"></div>
</div>

<div class="card">
  <h3>Publish your own</h3>
  <p class="muted" style="font-size:.83rem">Nothing is uploaded here. You submit a link
  to your own public repo, so authorship and history stay visibly yours.</p>
  <ol class="muted" style="font-size:.85rem;margin-left:1.1rem;line-height:1.9">
    <li>Make your model repo match the <span class="mono">v1</span> format
        (<span class="mono">MODEL.md</span>, <span class="mono">model.json</span>,
        a licence).</li>
    <li>Check it: <span class="mono">python -m suites.validate_card model.json --repo .</span></li>
    <li>Push it to GitHub, public.</li>
    <li>Submit the repo URL on the Garden page. A human confirms it is not about a
        named private individual; nothing else is reviewed.</li>
  </ol>
  <p class="muted" style="font-size:.8rem">Listing is not endorsement. A listed model may
  be wrong, and if it is graded wrong it stays listed with that record showing &mdash;
  that is the point.</p>
</div>

<script>
let GARDEN = [];
const G_FACETS = [
  ["kind", "kind"], ["level", "level"], ["evidence", "evidence"],
  ["scope", "scope"], ["sensitivity", "sensitivity"],
];
const G_SEL = {};

async function loadGarden(){
  try {
    const r = await fetch('/api/garden');
    GARDEN = await r.json();
    if (GARDEN.error){ GARDEN = []; }
  } catch(e){ GARDEN = []; }
  gFacets();
  gRender();
}

function gVal(m, key){
  if (key === "level") return "L" + (m.level ?? 0);
  if (key === "evidence") return (m.derived||{}).evidence || (m.evidence || "untested");
  if (["scope","sensitivity","inputs","effort"].includes(key))
    return (m.declared||{})[key] || "";
  return m[key] || "";
}

function gFacets(){
  const wrap = document.getElementById('g-facets');
  wrap.innerHTML = G_FACETS.map(([key,label]) => {
    const vals = [...new Set(GARDEN.map(m => gVal(m,key)).filter(Boolean))].sort();
    if (!vals.length) return '';
    return `<div><div class="muted" style="font-size:.7rem;letter-spacing:.1em;
      text-transform:uppercase;margin-bottom:.25rem">${label}</div>` +
      vals.map(v =>
        `<span class="badge" style="cursor:pointer;margin:0 .25rem .25rem 0;
          ${G_SEL[key]===v ? 'border-color:var(--acc);color:var(--accd)' : ''}"
          onclick="gPick('${key}','${v}')">${esc(v)}</span>`).join('') + `</div>`;
  }).join('');
}

function gPick(key, val){
  G_SEL[key] = (G_SEL[key] === val) ? null : val;
  gFacets(); gRender();
}

function gRender(){
  const q = (document.getElementById('g-q').value || '').toLowerCase();
  const rows = GARDEN.filter(m => {
    for (const [k] of G_FACETS)
      if (G_SEL[k] && gVal(m,k) !== G_SEL[k]) return false;
    if (!q) return true;
    return [m.model, m.title, m.mechanism, m.author].join(' ').toLowerCase().includes(q);
  });
  document.getElementById('g-count').textContent =
    `${rows.length} of ${GARDEN.length} models`;
  document.getElementById('g-list').innerHTML = rows.length ? rows.map(m => {
    const d = m.derived || {}, dec = m.declared || {};
    const ev = d.evidence || m.evidence || 'untested';
    const evColor = {proven:'var(--accd)', mixed:'var(--base)', failing:'var(--miss)',
                     early:'var(--sub)', untested:'var(--sub)'}[ev] || 'var(--sub)';
    const rec = m.record || {};
    const chips = [
      m.kind, 'L'+(m.level ?? 0), dec.scope, dec.inputs, dec.effort,
      dec.sensitivity && dec.sensitivity !== 'neutral' ? dec.sensitivity : null,
      d.horizon, d.activity,
    ].filter(Boolean);
    return `<div class="claim">
      <div class="chead" style="display:flex;gap:.6rem;flex-wrap:wrap;align-items:baseline">
        <b style="font-size:.98rem">${esc(m.title || m.model)}</b>
        <span class="badge" style="background:transparent;border:1px solid ${evColor};
          color:${evColor}">${esc(ev)}</span>
        <span class="muted mono" style="font-size:.75rem">${esc(m.author || 'unknown')}</span>
        ${m.spec ? `<span class="muted mono" style="font-size:.7rem">${esc(m.spec)}</span>`:''}
      </div>
      <div style="font-size:.88rem;color:var(--sub);margin:.25rem 0">${esc(m.mechanism||'')}</div>
      <div style="margin:.35rem 0">${chips.map(c =>
        `<span class="badge" style="background:transparent;border:1px solid var(--line);
          color:var(--sub);margin-right:.3rem">${esc(c)}</span>`).join('')}</div>
      <div class="muted" style="font-size:.78rem">
        ${rec.open ?? 0} open · ${rec.graded ?? 0} graded
        ${(m.aspects||[]).length ? ' · ' + esc((m.aspects||[]).join(', ')) : ''}
        ${m.e_span ? ` · E${m.e_span[0]}–E${m.e_span[1]}` : ''}
      </div>
      ${m.repo ? `<div class="mono" style="font-size:.76rem;margin-top:.45rem;
        background:var(--bg);border:1px solid var(--line);border-radius:6px;
        padding:.4rem .6rem;overflow:auto">git clone ${esc(m.repo)}<br>
        python -m suites.import_model ./${esc(m.model)}</div>
        <a href="${esc(m.repo)}" target="_blank" rel="noopener"
           style="font-size:.78rem;color:var(--accd)">repo &rarr;</a>` : ''}
    </div>`;
  }).join('') : '<p class="muted">nothing matches those filters.</p>';
}
</script>
"""


def local_index(models_dir: Path, fleet: dict) -> list:
    """Build a Garden index from this instance's own models, so the page works
    offline and an author can see their entry exactly as others would."""
    import sys
    sys.path.insert(0, str(models_dir.parent))
    out = []
    slugs = list(fleet.get("models", [])) + list(fleet.get("classifiers", []))
    for slug in slugs:
        repo = models_dir / slug
        if not (repo / "MODEL.md").exists():
            continue
        card = {}
        cf = repo / "model.json"
        if cf.exists():
            try:
                card = json.load(cf.open(encoding="utf-8"))
            except (OSError, ValueError):
                card = {}
        try:
            from suites.tags import derive, declared
            card.setdefault("derived", derive(repo))
            card.setdefault("declared", declared(repo))
        except Exception:
            pass
        card.setdefault("model", slug)
        card.setdefault("title", slug.replace("-", " ").title())
        card.setdefault("author", "this instance")
        card.setdefault("spec", "v1" if cf.exists() else "unpublished")
        if "record" not in card:
            rec = {"open": 0, "graded": 0}
            for rel in ("predict/ledger.json", "predict/live_ledger.json",
                        "signals/signal_ledger.json"):
                f = repo / rel
                if not f.exists():
                    continue
                try:
                    d = json.load(f.open(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                for r in (d.get("predictions", d) if isinstance(d, dict) else d):
                    rec["open" if r.get("status", "open") == "open" else "graded"] += 1
            card["record"] = rec
        out.append(card)
    return out
