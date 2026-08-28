"""Sensing-map visualizer — the abstraction cycle as a phase board.

Renders <repo>/map/sensing_map.json into <repo>/map/sensing_map.html: five phase columns
(absorption -> anomaly -> patching -> naming-contest -> reorganized) with framework cards
that carry their patches, anomalies (amplitude/resolution), cracking layers, and successor
vocabulary — plus a generation timeline that replays the exploration (rounds, then deepen
passes over aspects), so the deepening of the domain is watchable. A framework whose phase
advanced shows its trajectory on the card.

Self-contained vanilla JS/HTML, no external assets. Wired into sensing_map: regenerated on
every round-mapping and deepen pass.

  python -m suites.sensing_viz --repo my-model
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

TOOLS = Path(__file__).resolve().parents[2]

TEMPLATE = r"""<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root{--bg:#0d1117;--panel:#161b22;--card:#1c2129;--ink:#e6edf3;--dim:#8b949e;
    --line:#30363d;--abs:#3fb950;--ano:#d4a72c;--pat:#f0883e;--nam:#f85149;--reo:#58a6ff}
  *{box-sizing:border-box;margin:0}
  body{background:var(--bg);color:var(--ink);font:14px/1.45 "Segoe UI",system-ui,sans-serif;
    height:100vh;display:flex;flex-direction:column;overflow:hidden}
  header{padding:10px 16px;border-bottom:1px solid var(--line)}
  header h1{font-size:16px;font-weight:600;display:inline}
  header .sub{color:var(--dim);font-size:12px;margin-left:12px}
  #board{flex:1;display:flex;gap:10px;padding:12px;overflow-x:auto;overflow-y:hidden}
  .col{flex:1;min-width:215px;display:flex;flex-direction:column;background:var(--panel);
    border:1px solid var(--line);border-radius:10px;overflow:hidden}
  .col h2{font-size:12.5px;font-weight:600;padding:8px 12px;border-bottom:1px solid var(--line);
    display:flex;justify-content:space-between;align-items:center;position:sticky;top:0}
  .col h2 .n{color:var(--dim);font-weight:400}
  .cards{flex:1;overflow-y:auto;padding:8px;display:flex;flex-direction:column;gap:8px}
  .card{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--dim);
    border-radius:8px;padding:9px 11px;font-size:12.5px;cursor:default;
    transition:transform .15s}
  .card:hover{transform:translateY(-1px);border-color:var(--dim)}
  .card.new{animation:arrive .8s ease-out}
  @keyframes arrive{0%{opacity:0;transform:translateY(10px) scale(.96)}100%{opacity:1}}
  .card .name{font-weight:600;margin-bottom:3px}
  .card .ent{font-size:10.5px;color:var(--dim);text-transform:uppercase;letter-spacing:.4px}
  .card .meta{color:var(--dim);font-size:11.5px;margin-top:5px;display:flex;gap:10px;flex-wrap:wrap}
  .card .crack{color:var(--pat);font-size:11px;margin-top:4px}
  .card .names{color:var(--reo);font-size:11px;margin-top:3px}
  .card .traj{color:var(--dim);font-size:10.5px;margin-top:4px;font-style:italic}
  .card details{margin-top:6px;font-size:11.5px}
  .card summary{color:var(--dim);cursor:pointer;font-size:11px}
  .card li{margin-left:14px;color:var(--dim)}
  .card li b{color:var(--ink);font-weight:500}
  .controls{display:flex;align-items:center;gap:10px;padding:10px 16px;
    border-top:1px solid var(--line);background:var(--panel);flex-wrap:wrap}
  .controls button{background:#21262d;color:var(--ink);border:1px solid var(--line);
    border-radius:6px;padding:5px 14px;font-size:13px;cursor:pointer}
  input[type=range]{flex:1;min-width:140px;accent-color:#58a6ff}
  #genlabel{min-width:200px;font-size:12.5px}
  #bias{border-top:1px solid var(--line);background:var(--panel);padding:8px 16px;
    font-size:11.5px;color:var(--dim);max-height:86px;overflow-y:auto}
  #bias b{color:var(--ink)}
</style></head><body>
<header><h1>__TITLE__</h1><span class="sub">__SUB__</span></header>
<div id="board"></div>
<div id="bias"></div>
<div class="controls">
  <button id="play">▶ replay exploration</button>
  <input type="range" id="gen" min="0" value="0">
  <span id="genlabel"></span>
</div>
<script>
const DATA = __DATA__;
const PHASES=[["absorption","🟢 absorption","--abs"],["anomaly","🟡 anomaly","--ano"],
  ["patching","🟠 patching","--pat"],["naming-contest","🔴 naming-contest","--nam"],
  ["reorganized","🔵 reorganized","--reo"]];
const gens = DATA.history.map(h=>h.label);
function genOf(l){l=(l||'').trim();let i=gens.indexOf(l);if(i<0){gens.push(l);i=gens.length-1}return i}
const fws = Object.entries(DATA.frameworks).map(([id,f])=>({id,...f,gen:genOf(f.first_seen)}));
const slider=document.getElementById('gen');
slider.max=gens.length-1; slider.value=gens.length-1;
let G=gens.length-1;

function draw(pulse){
  const board=document.getElementById('board'); board.innerHTML='';
  PHASES.forEach(([key,label,cvar])=>{
    const col=document.createElement('div');col.className='col';
    const items=fws.filter(f=>f.gen<=G&&f.phase===key);
    col.innerHTML=`<h2 style="color:var(${cvar})">${label}<span class="n">${items.length}</span></h2>`;
    const cards=document.createElement('div');cards.className='cards';
    items.forEach(f=>{
      const c=document.createElement('div');
      c.className='card'+(pulse&&f.gen===G?' new':'');
      c.style.borderLeftColor=`var(${cvar})`;
      let inner=`<div class="ent">${f.entity||''}</div><div class="name">${f.name}</div>`;
      if(f.note)inner+=`<div style="color:var(--dim);font-size:11.5px">${f.note}</div>`;
      inner+=`<div class="meta"><span>🩹 ${ (f.patches||[]).length} patches</span><span>⚡ ${(f.anomalies||[]).length} anomalies</span></div>`;
      if((f.cracking||[]).length)inner+=`<div class="crack">cracking: ${f.cracking.join(', ')}</div>`;
      if((f.name_candidates||[]).length)inner+=`<div class="names">names: ${f.name_candidates.join(' · ')}</div>`;
      (f.phase_history||[]).forEach(h=>{inner+=`<div class="traj">${h.from} → ${h.to} (${h.on})</div>`});
      const ev=[...(f.patches||[]).map(p=>`<li><b>patch</b> ${p.what} <i>(${p.when||''})</i></li>`),
                ...(f.anomalies||[]).map(a=>`<li><b>anomaly/${a.channel||'?'}</b> ${a.what} <i>(${a.when||''})</i></li>`)];
      if(ev.length)inner+=`<details><summary>evidence (${ev.length})</summary><ul>${ev.join('')}</ul></details>`;
      inner+=`<div class="traj">${f.first_seen}</div>`;
      c.innerHTML=inner;cards.appendChild(c);
    });
    col.appendChild(cards);board.appendChild(col);
  });
  const h=DATA.history[G]||{};
  document.getElementById('genlabel').textContent=
    `${gens[G]} (${G+1}/${gens.length})`+(h.aspects?` — ${h.aspects.split('(')[0].trim()}…`:'');
  const bias=(DATA.sensing_bias||[]);
  document.getElementById('bias').innerHTML='<b>What the domain’s instruments cannot see:</b> '+
    bias.map(b=>`<b>${b.blind_spot}</b> — ${b.why_structural||''}`).join(' · ');
}
slider.oninput=()=>{G=+slider.value;draw(true)};
document.getElementById('play').onclick=()=>{let g=0;G=0;draw(true);
  const iv=setInterval(()=>{g++;if(g>=gens.length){clearInterval(iv);return}
    G=g;slider.value=g;draw(true)},1700)};
draw(false);
</script></body></html>"""


def write_html(m: dict, mdir: Path, repo: str) -> Path:
    if not m.get("history"):
        labels = []
        for f in m["frameworks"].values():
            lb = (f.get("first_seen") or "").strip()
            if lb and lb not in labels:
                labels.append(lb)
        labels.sort(key=lambda s: (0 if s.startswith("round") else 1, s))
        m = {**m, "history": [{"label": lb, "date": m.get("updated", "")} for lb in labels]}
    sub = (f"updated {m.get('updated','')} · {len(m['frameworks'])} frameworks · "
           f"{len(m['history'])} generations — abstraction-cycle phase board; "
           f"replay to watch the exploration")
    html = (TEMPLATE.replace("__TITLE__", f"Sensing map — {repo}")
            .replace("__SUB__", sub)
            .replace("__DATA__", json.dumps(m, ensure_ascii=False)))
    out = mdir / "sensing_map.html"
    out.write_text(html, encoding="utf-8")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Render sensing_map.json as a phase-board HTML.")
    ap.add_argument("--repo", default="my-model")
    a = ap.parse_args()
    mdir = TOOLS / a.repo / "map"
    m = json.load((mdir / "sensing_map.json").open(encoding="utf-8"))
    out = write_html(m, mdir, a.repo)
    print(f"-> {out}")


if __name__ == "__main__":
    main()
