# Model Cockpit v3 — design handoff

Drop this folder into your main instance's `ui/design/`. `model-cockpit-v3.html` opens offline (fonts + runtime inlined). `source/` is the editable design component.

## Shell
- Sidebar nav (216px, sticky), 5 groups: Today / Fleet / Feed / Atlas / Reference. Collapses to a wrapping top bar < 860px.
- Top bar: page group + title, search (`/`), primary **+ Register a claim** (`c`) → capture modal → toast on register.
- Palette: bg `#08080A`, panel `rgba(13,13,16,.85)`, ink `#ECEAE3`, accent `#EDEBE4`, alert `#e08050` (one per screen). Type: Newsreader (body), JetBrains Mono (labels/data), Goldman (brand).

## Tabs → server.py
| Tab | Endpoint / source | Notes |
|---|---|---|
| Home | `/api/home` | Past-due alert + Grade CTA; progress cards (cohort countdown, weekly passes, your tasks); coming due; recent commits; run-a-pass buttons → `/api/run` + `/api/runlog/<act>` |
| Verdict | `/api/verdict` | honest card when `graded_live == 0`; earned/lucky bar; `miss_why`; `attribution`; `per_model` Brier vs baseline |
| Models | `/api/models` | table stacks mechanism under name < 1180px; scaffold form |
| Events | `/api/events` | queue form + assessments |
| Brainstorm | `/api/brainstorms` | lens chips, devil's-advocate always on |
| Entities | `/api/entities`, `/api/entity/<slug>`, `/api/mindmap` | **mesh**: 2D force layout, node r = fragments, edge width = weight, dashed = `part_of`, slider = weight threshold, hover traces neighbours, click loads dossier; thin-dossier fallback when no synthesis |
| Map | `/api/map` | stat tiles from `coverage`; floor gridlines (E0–E14, 8.5 marker); empty aspects rendered as invitations; bar title = model · span · tier · mechanism |
| Tasks | `/api/tasks` | due + manual |
| Assessments | `/api/assess` | |
| Glossary | `/api/glossary` | |
| Connect | `ui/inbox.jsonl` | |

Mesh nodes/edges in the mock are illustrative — bind to `entity-atlas/mindmap.json` (`nodes[].{id,name,kind,fragments,part_of}`, `edges[].{a,b,weight,why}`).

## UX-law decisions
- Hick/Miller/Jakob: grouped sidebar instead of 11 flat pills.
- Fitts: 40–46px targets; primary action fixed in top bar; Grade CTA sits on the alert.
- Von Restorff: orange only for the single past-due item (+ nav badge).
- Zeigarnik: progress cards + nav counts.
- Serial position / Pareto: Home first, Connect last; passes at Home's end.
- Peak-end / Doherty: instant close + sealed toast on register.
- Parkinson / Postel: defaults (30d, .6); search accepts query, URL, or claim.
- Similarity / Prägnanz: one card radius (16), one chip anatomy (38–40px, r10), one badge style.
- Keyboard: `g`+key jump, `/`, `c`, `?` — mirrors server.py GOTO map.
