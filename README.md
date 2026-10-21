# paper-map

Turns a research paper into a one-page, top-down HTML map:

**Question ↓ [Why it matters | Background] ↓ Method ↓ Results ↓ Conclusion ↓ Answer**

Sections start collapsed, so first you see only the question and the answer; each header shows how many
points it holds and how many are ★ new or ⚠ caveats. Click a header to open it, or use *Open all sections*.

Method lists the shared setup. Results has one card per test: the question it answers, how it was done,
then one row per case with its condition on the left (e.g. `Planck only` vs `Planck + SH0ES`), so the contrast
is visible side by side.

Blocks carry ★ NEW (what this paper adds over prior work), ⚠ CAVEAT (assumptions, missing physics, weak
statistics) and KEY badges, and the *Show* buttons fade out everything else.

Click any block to expand it. Background points link to the cited papers (DOI/arXiv when the
paper prints one, otherwise a Google Scholar search). A jargon glossary and reference list sit below the map.

## Use

```sh
export ANTHROPIC_API_KEY=sk-ant-...        # once
python3 paper_map.py ~/Downloads/paper.pdf --open
python3 paper_map.py 1706.03762 --open     # arXiv ID or URL works too
```

Writes `paper.json` (the extracted structure) and `paper.html` next to the PDF (or into `--out-dir`).
Edit the JSON by hand if you like, then re-render without calling the API:

```sh
python3 paper_map.py --from-json paper.json
```

`--effort low|medium|high|xhigh|max` trades speed/cost against depth (default `high`).

## Without an API key

Ask Claude Code: *"Read paper.pdf and write a JSON map following the SCHEMA in paper_map.py, then run
`--from-json` on it."* `examples/riess1998.json` is a hand-written example.

## Atlas (atlas.py): mind map + paper flow in one page

Opens on a floating mind map: this paper in the centre (its question and answer float in a card beside it),
the big areas it draws on around it, and their concepts further out in five shaded, numbered layers:
frontier, areas, specialist, core, foundations. Clicking a circle opens its details in a panel on the right, with
the map narrowing beside it so it stays in view: areas say why they matter, what they contribute to the paper and the best way in;
concepts give a plain explanation, a reading ladder, and their prerequisites, numbered on the map.

*Read the paper* lays the paper out top to bottom, like the original map: The question → [Why it matters |
Background] → Method → Results → Conclusion → The answer, joined by dotted connectors. Each part is a tinted
block led by its circle; it opens on click, and each point unfolds its details in place (the papers it builds
on and the concepts behind it). A paper with more than one big question (`other_questions`) shows them together
in one "The big questions" box and groups its tests by question; only questions marked `separate` (answered by
clearly distinct work) get their own side-by-side boxes and result lanes. *Key points* shows a short top-to-bottom path through the key points only
Words naming a concept are
dotted-underlined: click for a short explainer and where to read more. Each block keeps its figures and key equations folded behind *View figures* / *View equations* buttons (equations come
from the map's `equations` list and are typeset with KaTeX, loaded only when opened; offline they show as LaTeX). Plots appear as thumbnails
(a figure's or equation's `attach` can list several places: a block such as `setup`, a test `results:2`, or a single
point, `setup#2` for the 2nd Method point or `results:3#1` for the 1st finding of test 3; points then get their own buttons); clicking one opens it full-screen with its
caption, with arrows to step through all figures. The arXiv ID / DOI in the citation line, and an *Open the paper* button, link to the paper. Jargon and reference lists are
left out, since that information is in the explainers and zoom cards.

```sh
python3 atlas.py ~/Downloads/paper.pdf --open        # both extractions, then the atlas
python3 atlas.py --map maps/arxiv-2610.18864.json --roots maps/arxiv-2610.18864.roots.json
```

## Learning map (roots_map.py)

The paper map shows a paper as it is written. The learning map traces it back to its roots, for a reader
new to the field: every concept the introduction, methods, results and discussion rely on, arranged as a
ladder from foundations (level 1) to the frontier this paper extends (level 4), each with a reading ladder:
**Start here** (an intro textbook chapter or readable review), **Go deeper**, **The original** paper, and
**What this paper builds on**. Readings from the paper's own reference list are tagged `cited [N]`; basic
textbooks it doesn't cite are tagged `suggested`.

```sh
python3 roots_map.py ~/Downloads/paper.pdf --open        # or an arXiv ID
python3 roots_map.py --from-json maps/arxiv-2610.18864.roots.json
```

Three views: *Ladder* (click a concept to highlight, in reading order, everything to learn first),
*By paper section*, and *Bookshelf* (a shortlist, a reading order for the whole map, and every reading by type).
Without an API key, ask Claude Code to write `<name>.roots.json` following `SCHEMA` in `roots_map.py`.

## Files

- `paper_map.py`: fetches the PDF, asks Claude (`claude-opus-5-5`, structured JSON output) for the map, renders it
- `template.html`: self-contained mind-map page; the JSON is embedded, so the output works offline
- `roots_map.py`, `roots_template.html`: the learning map (reuses `load_pdf`/`extract` from `paper_map.py`)
- `atlas.py`, `atlas_template.html`: the combined atlas page

A copy of the tool from before the learning map was added is in `../paper-map-backup-2026-10-21/`.
