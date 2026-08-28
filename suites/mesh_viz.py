"""Mesh visualizer — an interactive, self-contained HTML view of the observed Mesh.

Renders <repo>/map/map.json into <repo>/map/map.html: a force-directed graph with the
theory's visual grammar (edge types, evidence tiers, node failure-states) and a TIMELINE
that replays the map's growth generation by generation — rounds, then deepen passes — so
the deepening is something you can watch, not just diff.

Self-contained vanilla JS/SVG, no external assets; open the file in any browser. The
generation order comes from map.json's `history` (recorded by mesh_map on every run);
elements are stamped by their provenance labels (`first_seen` / `added`).

Wired into mesh_map: every round-mapping and deepen pass regenerates map.html.

  python -m suites.mesh_viz --repo mesh
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
  :root{--bg:#0d1117;--panel:#161b22;--ink:#e6edf3;--dim:#8b949e;--line:#30363d;
    --stable:#3fb950;--strained:#d29922;--hollow:#a371f7;--tipping:#f85149;
    --found:#e6edf3;--enab:#58a6ff;--legit:#d29922;--sust:#3fb950}
  *{box-sizing:border-box;margin:0}
  body{background:var(--bg);color:var(--ink);font:14px/1.5 "Segoe UI",system-ui,sans-serif;
    height:100vh;display:flex;flex-direction:column;overflow:hidden}
  header{padding:10px 16px;border-bottom:1px solid var(--line);display:flex;
    align-items:baseline;gap:14px;flex-wrap:wrap}
  header h1{font-size:16px;font-weight:600}
  header .sub{color:var(--dim);font-size:12px}
  #stage{flex:1;position:relative;overflow:hidden}
  svg{width:100%;height:100%;display:block;cursor:grab}
  svg.dragging{cursor:grabbing}
  .controls{display:flex;align-items:center;gap:10px;padding:10px 16px;
    border-top:1px solid var(--line);background:var(--panel);flex-wrap:wrap}
  .controls button{background:#21262d;color:var(--ink);border:1px solid var(--line);
    border-radius:6px;padding:5px 14px;font-size:13px;cursor:pointer}
  .controls button:hover{border-color:var(--dim)}
  input[type=range]{flex:1;min-width:140px;accent-color:#58a6ff}
  #genlabel{min-width:150px;font-size:13px;color:var(--ink)}
  #counts{color:var(--dim);font-size:12px;min-width:120px}
  .legend{position:absolute;top:10px;right:10px;background:rgba(22,27,34,.92);
    border:1px solid var(--line);border-radius:8px;padding:10px 12px;font-size:11.5px;
    color:var(--dim);line-height:1.9;max-width:230px}
  .legend b{color:var(--ink);font-weight:600}
  .sw{display:inline-block;width:22px;height:0;border-bottom:2.5px solid;margin:0 6px 3px 0;
    vertical-align:middle}
  .dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin:0 8px 0 0;
    vertical-align:-1px}
  #tip{position:absolute;pointer-events:none;background:#1c2129;border:1px solid var(--line);
    border-radius:8px;padding:8px 11px;font-size:12px;max-width:320px;display:none;
    color:var(--ink);box-shadow:0 6px 24px rgba(0,0,0,.5);z-index:5}
  #tip .t{font-weight:600;margin-bottom:2px}
  #tip .m{color:var(--dim)}
  text{fill:var(--ink);font-size:10.5px;paint-order:stroke;stroke:var(--bg);stroke-width:3px;
    pointer-events:none}
  .pulse{animation:pulse 1.2s ease-out 2}
  @keyframes pulse{0%{stroke-width:10;stroke-opacity:.9}100%{stroke-width:2;stroke-opacity:0}}
</style></head><body>
<header><h1>__TITLE__</h1><span class="sub">__SUB__</span></header>
<div id="stage">
  <svg id="svg"></svg>
  <div class="legend">
    <b>Edges</b><br>
    <span class="sw" style="border-color:var(--found);border-bottom-width:3.5px"></span>foundation<br>
    <span class="sw" style="border-color:var(--enab)"></span>enabling<br>
    <span class="sw" style="border-color:var(--legit);border-bottom-style:dashed"></span>legitimacy<br>
    <span class="sw" style="border-color:var(--sust)"></span>sustaining (loop)<br>
    <span class="sw" style="border-color:var(--dim);border-bottom-style:dotted"></span>conjectural (never load-bearing)<br>
    <b>Nodes</b><br>
    <span class="dot" style="background:var(--stable)"></span>stable<br>
    <span class="dot" style="background:var(--strained)"></span>strained<br>
    <span class="dot" style="background:var(--hollow)"></span>hollowing<br>
    <span class="dot" style="background:var(--tipping)"></span>tipping-window<br>
    <span class="dot" style="background:transparent;border:1.5px dashed var(--dim)"></span>substrate assumption
  </div>
  <div id="tip"></div>
</div>
<div class="controls">
  <button id="play">▶ replay deepening</button>
  <input type="range" id="gen" min="0" value="0">
  <span id="genlabel"></span>
  <span id="counts"></span>
</div>
<script>
const DATA = __DATA__;
const S = document.getElementById('svg'), TIP = document.getElementById('tip');
const stateColor = {stable:'var(--stable)',strained:'var(--strained)',
  hollowing:'var(--hollow)','tipping-window':'var(--tipping)'};
const typeColor = {foundation:'var(--found)',enabling:'var(--enab)',
  legitimacy:'var(--legit)',sustaining:'var(--sust)'};

// generations from history; unknown labels appended (defensive)
const gens = DATA.history.map(h=>h.label);
function genOf(label){ label=(label||'').split(' /')[0].trim();
  let i=gens.indexOf(label); if(i<0){gens.push(label); i=gens.length-1} return i }
const nodes = Object.entries(DATA.nodes).map(([id,n])=>({id,...n,gen:genOf(n.first_seen),
  substrate:(n.note||'').toLowerCase().startsWith('substrate assumption'),
  x:0,y:0,vx:0,vy:0}));
const byId = Object.fromEntries(nodes.map(n=>[n.id,n]));
const edges = DATA.edges.filter(e=>byId[e.from]&&byId[e.to])
  .map(e=>({...e,gen:genOf(e.added),a:byId[e.from],b:byId[e.to]}));

const slider=document.getElementById('gen');
slider.max=gens.length-1; slider.value=gens.length-1;
let G=gens.length-1, W=0, H=0, alpha=0, dragN=null;

function seed(){ W=S.clientWidth; H=S.clientHeight;
  nodes.forEach((n,i)=>{const a=i/nodes.length*2*Math.PI, r=Math.min(W,H)*.30;
    n.x=W/2+r*Math.cos(a)+(i%7-3)*9; n.y=H/2+r*Math.sin(a)+(i%5-2)*9}) }

function visN(){return nodes.filter(n=>n.gen<=G)}
function visE(){return edges.filter(e=>e.gen<=G&&e.a.gen<=G&&e.b.gen<=G)}

function tick(){
  const vn=visN(), ve=visE();
  for(let i=0;i<vn.length;i++)for(let j=i+1;j<vn.length;j++){
    const a=vn[i],b=vn[j]; let dx=b.x-a.x,dy=b.y-a.y,d2=dx*dx+dy*dy||1;
    if(d2<260*260){const f=2600/d2,d=Math.sqrt(d2);dx/=d;dy/=d;
      a.vx-=dx*f;a.vy-=dy*f;b.vx+=dx*f;b.vy+=dy*f}}
  ve.forEach(e=>{let dx=e.b.x-e.a.x,dy=e.b.y-e.a.y,d=Math.sqrt(dx*dx+dy*dy)||1;
    const f=(d-150)*.012;dx/=d;dy/=d;
    e.a.vx+=dx*f*d*.01;e.a.vy+=dy*f*d*.01;e.b.vx-=dx*f*d*.01;e.b.vy-=dy*f*d*.01});
  vn.forEach(n=>{n.vx+=(W/2-n.x)*.0012;n.vy+=(H/2-n.y)*.0012;
    if(n!==dragN){n.x+=n.vx*alpha;n.y+=n.vy*alpha}
    n.vx*=.86;n.vy*=.86;
    n.x=Math.max(30,Math.min(W-30,n.x));n.y=Math.max(30,Math.min(H-30,n.y))});
}
function draw(pulseGen){
  const vn=visN(), ve=visE();
  let s='<defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0L10,5L0,10z" fill="#8b949e"/></marker></defs>';
  ve.forEach(e=>{
    const conj=e.evidence==='conjectural';
    const w=e.type==='foundation'?3.2:1.7;
    const dash=e.type==='legitimacy'?'7,5':(conj?'2,5':'');
    const strain=e.strain==='acute'?'#f85149':(e.strain==='building'?'#d29922':null);
    const mx=(e.a.x+e.b.x)/2, my=(e.a.y+e.b.y)/2;
    const curve=e.type==='sustaining'?` Q ${mx+(e.a.y-e.b.y)*.18} ${my+(e.b.x-e.a.x)*.18}`:' L';
    if(strain) s+=`<path d="M ${e.a.x} ${e.a.y}${curve} ${e.b.x} ${e.b.y}" stroke="${strain}" stroke-width="${w+4}" fill="none" opacity=".28"/>`;
    s+=`<path class="E" data-i="${edges.indexOf(e)}" d="M ${e.a.x} ${e.a.y}${curve} ${e.b.x} ${e.b.y}" stroke="${typeColor[e.type]}" stroke-width="${w}" fill="none" opacity="${conj?.45:.8}" ${dash?`stroke-dasharray="${dash}"`:''} marker-end="url(#arr)"/>`;
  });
  vn.forEach(n=>{
    const r=n.substrate?13:11, c=stateColor[n.state]||'var(--dim)';
    if(n.gen===pulseGen) s+=`<circle class="pulse" cx="${n.x}" cy="${n.y}" r="${r+4}" fill="none" stroke="${c}"/>`;
    if(n.state==='tipping-window') s+=`<circle cx="${n.x}" cy="${n.y}" r="${r+5}" fill="none" stroke="var(--tipping)" stroke-opacity=".5" stroke-width="1.5"/>`;
    s+=`<circle class="N" data-id="${n.id}" cx="${n.x}" cy="${n.y}" r="${r}" fill="${n.state==='hollowing'?'transparent':c}" stroke="${c}" stroke-width="${n.state==='hollowing'?2.5:1.5}" ${n.substrate?'stroke-dasharray="4,3"':''} style="cursor:pointer"/>`;
    s+=`<text x="${n.x}" y="${n.y-r-6}" text-anchor="middle">${n.name.slice(0,34)}</text>`;
  });
  S.innerHTML=s;
  document.getElementById('genlabel').textContent=`${gens[G]} (${G+1}/${gens.length})`;
  document.getElementById('counts').textContent=`${vn.length} nodes · ${ve.length} edges`;
}
let pulseUntil=0, pulseGen=-1;
function loop(){ if(alpha>0.02){tick();draw(performance.now()<pulseUntil?pulseGen:-1);alpha*=.995}
  requestAnimationFrame(loop) }
function setGen(g,pulse){ G=g; slider.value=g; alpha=1;
  if(pulse){pulseGen=g;pulseUntil=performance.now()+2400} draw(pulse?g:-1) }
slider.oninput=()=>setGen(+slider.value,true);
document.getElementById('play').onclick=()=>{ let g=0; setGen(0,true);
  const iv=setInterval(()=>{ g++; if(g>=gens.length){clearInterval(iv);return}
    setGen(g,true) },1600) };
// tooltips + drag
S.addEventListener('mousemove',ev=>{
  const t=ev.target;
  if(dragN){const r=S.getBoundingClientRect();dragN.x=ev.clientX-r.left;dragN.y=ev.clientY-r.top;alpha=Math.max(alpha,.5);return}
  if(t.classList&&t.classList.contains('N')){const n=byId[t.dataset.id];
    TIP.style.display='block';TIP.style.left=(ev.clientX+14)+'px';TIP.style.top=(ev.clientY+8)+'px';
    TIP.innerHTML=`<div class="t">${n.name}</div><div class="m">[${n.state}] · ${n.entity||'cross-domain'} · ${n.first_seen}</div><div>${n.note||''}</div>`}
  else if(t.classList&&t.classList.contains('E')){const e=edges[+t.dataset.i];
    TIP.style.display='block';TIP.style.left=(ev.clientX+14)+'px';TIP.style.top=(ev.clientY+8)+'px';
    TIP.innerHTML=`<div class="t">${e.from} → ${e.to}</div><div class="m">${e.type} / ${e.evidence}${e.strain&&e.strain!=='none'?' · strain: '+e.strain:''} · ${e.added}</div><div>${e.note||''}</div>`}
  else TIP.style.display='none';
});
S.addEventListener('mousedown',ev=>{const t=ev.target;
  if(t.classList&&t.classList.contains('N')){dragN=byId[t.dataset.id];S.classList.add('dragging')}});
addEventListener('mouseup',()=>{dragN=null;S.classList.remove('dragging')});
addEventListener('resize',()=>{W=S.clientWidth;H=S.clientHeight;alpha=Math.max(alpha,.3)});
seed(); alpha=1; draw(-1); loop();
</script></body></html>"""


def write_html(m: dict, mdir: Path, repo: str) -> Path:
    if not m.get("history"):
        # legacy maps: synthesize history from provenance labels (rounds then passes)
        labels = []
        for n in m["nodes"].values():
            lb = (n.get("first_seen") or "").strip()
            if lb and lb not in labels:
                labels.append(lb)
        labels.sort(key=lambda s: (0 if s.startswith("round") else 1, s))
        m = {**m, "history": [{"label": lb, "date": m.get("updated", "")} for lb in labels]}
    sub = (f"updated {m.get('updated','')} · {len(m['nodes'])} nodes · "
           f"{len(m['edges'])} edges · {len(m['history'])} generations — drag nodes, "
           f"hover for notes, replay to watch the deepening")
    html = (TEMPLATE.replace("__TITLE__", f"Observed Mesh — {repo}")
            .replace("__SUB__", sub)
            .replace("__DATA__", json.dumps(m, ensure_ascii=False)))
    out = mdir / "map.html"
    out.write_text(html, encoding="utf-8")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Render map.json as an interactive HTML visualizer.")
    ap.add_argument("--repo", default="mesh")
    a = ap.parse_args()
    mdir = TOOLS / a.repo / "map"
    m = json.load((mdir / "map.json").open(encoding="utf-8"))
    out = write_html(m, mdir, a.repo)
    print(f"-> {out}")


if __name__ == "__main__":
    main()
