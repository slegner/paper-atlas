#!/usr/bin/env python3
"""Join a paper map and its learning map into one interactive page (the "atlas").

    python3 atlas.py paper.pdf                       # run both extractions, then build the atlas
    python3 atlas.py 2401.01234                      # arXiv ID (or arxiv.org URL)
    python3 atlas.py --map maps/X.json --roots maps/X.roots.json [--pdf X.pdf]   # from saved maps

The atlas opens on a floating mind map: this paper in the centre (with its question and answer), the big
areas it draws on around it, and their concepts further out in shaded layers, the more basic the further.
Every circle zooms open into its details when clicked. The paper view lays the paper out as a flow of
circles from question to answer that open and close, with a "key points" mode that walks from the
question to the answer through the key points only. Words naming a concept open a short explainer.

Writes <name>.atlas.html (plus the two .json maps when extracting) next to the PDF, or into --out-dir.
"""
import argparse
import json
from pathlib import Path

import paper_map
import roots_map

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "atlas_template.html"


def render(paper, roots, out_html, fig_dir=None):
    paper = paper_map.with_figures(paper, fig_dir)
    as_json = lambda d: json.dumps(d, ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.read_text()
    for key, value in [("__PAPER_DATA__", as_json(paper)), ("__ROOTS_DATA__", as_json(roots)),
                       ("__PAGE_TITLE__", paper_map.escape(paper.get("title", "Paper atlas")))]:
        html = html.replace(key, value)
    out_html.write_text(html)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", nargs="?", help="PDF path or arXiv ID/URL (omit when using --map/--roots)")
    ap.add_argument("--map", type=Path, help="saved paper map (.json)")
    ap.add_argument("--roots", type=Path, help="saved learning map (.roots.json)")
    ap.add_argument("--pdf", help="with --map: the paper's PDF (or arXiv ID) to crop figures from")
    ap.add_argument("--out-dir", type=Path, help="where to write the output")
    ap.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    ap.add_argument("--open", action="store_true", help="open the result in your browser")
    args = ap.parse_args()

    pdf_bytes = None
    if args.map and args.roots:
        paper, roots = json.loads(args.map.read_text()), json.loads(args.roots.read_text())
        stem, default_dir = args.map.stem, args.map.parent
        if args.pdf:
            pdf_bytes, _ = paper_map.load_pdf(args.pdf)
    elif args.source:
        pdf_bytes, stem = paper_map.load_pdf(args.source)
        p = Path(args.source).expanduser()
        default_dir = p.parent if p.exists() else Path.cwd()
        paper = paper_map.extract(pdf_bytes, args.effort)
        roots = paper_map.extract(pdf_bytes, args.effort, roots_map.SCHEMA, roots_map.PROMPT)
    else:
        ap.error("give a PDF/arXiv ID, or both --map and --roots")

    out_dir = args.out_dir or default_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    if not (args.map and args.roots):
        (out_dir / f"{stem}.json").write_text(json.dumps(paper, indent=2, ensure_ascii=False))
        (out_dir / f"{stem}.roots.json").write_text(json.dumps(roots, indent=2, ensure_ascii=False))
    roots_map.check(roots)
    fig_dir = out_dir / f"{stem}.figs"
    if pdf_bytes:
        paper_map.crop_figures(paper, pdf_bytes, fig_dir)
    out_html = out_dir / f"{stem}.atlas.html"
    render(paper, roots, out_html, fig_dir)
    print(f"Wrote {out_html}")
    if args.open:
        import webbrowser
        webbrowser.open(out_html.resolve().as_uri())


if __name__ == "__main__":
    main()
