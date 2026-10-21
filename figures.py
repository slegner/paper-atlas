#!/usr/bin/env python3
"""Crop numbered figures out of a paper PDF as PNGs.

    python3 figures.py paper.pdf 3 6 8 --out figs/

A figure is found by its caption ("Figure 4." / "Fig. 4:" / "FIG. 4:") and taken to be the
graphics (vector drawings and embedded images) directly above that caption, plus any axis labels
around them. Needs PyMuPDF (`pip install pymupdf`).
"""
import argparse
import re
from pathlib import Path

CAPTION = re.compile(r"^\s*(?:FIG\.|Fig\.|Figure|FIGURE)\s*(\d+)\s*[.:|]")


def find_captions(doc):
    """Map figure number -> (page, caption rect), keeping the first caption-like block per number."""
    import fitz

    found = {}
    for page in doc:
        for x0, y0, x1, y1, text, *_ in page.get_text("blocks"):
            m = CAPTION.match(text)
            if m and int(m.group(1)) not in found:
                found[int(m.group(1))] = (page, fitz.Rect(x0, y0, x1, y1))
    return found


def figure_rect(page, cap):
    """Union of the graphics sitting just above `cap` that overlap it horizontally."""
    import fitz

    graphics = [r for r in page.cluster_drawings() if r.width > 30 and r.height > 30]
    graphics += [fitz.Rect(i["bbox"]) for i in page.get_image_info()]
    graphics = [r for r in graphics if r.width > 30 and r.height > 30]
    above = [r for r in graphics
             if r.y1 <= cap.y0 + 4 and min(r.x1, cap.x1) - max(r.x0, cap.x0) > 0.2 * min(r.width, cap.width)]
    if not above:
        return None
    nearest = min(above, key=lambda r: cap.y0 - r.y1)
    # Panels side by side (or stacked with no caption between) belong to the same figure.
    rect = fitz.Rect(nearest)
    for r in sorted(above, key=lambda r: -r.y1):
        if r.y1 >= rect.y0 - 25 and r.y0 < cap.y0:
            rect |= r
    # Pull in axis labels and legends just outside the drawn area, but never the caption.
    grow = fitz.Rect(rect.x0 - 18, rect.y0 - 14, rect.x1 + 18, min(rect.y1 + 22, cap.y0 - 1))
    for x0, y0, x1, y1, text, *_ in page.get_text("blocks"):
        b = fitz.Rect(x0, y0, x1, y1)
        if b.intersects(grow) and b.y1 <= cap.y0 and b.width < 0.6 * page.rect.width and len(text) < 120:
            rect |= b & grow
    return (rect + (-4, -4, 4, 4)) & page.rect


def extract(pdf_path, numbers, out_dir, zoom=2.5):
    """Write fig<N>.png for each requested figure; return {N: path} for the ones found."""
    import fitz

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf_path)
    captions = find_captions(doc)
    written = {}
    for n in numbers:
        if n not in captions:
            print(f"  figure {n}: caption not found, skipped")
            continue
        page, cap = captions[n]
        rect = figure_rect(page, cap)
        if rect is None:
            print(f"  figure {n}: no graphics above caption on page {page.number + 1}, skipped")
            continue
        path = out_dir / f"fig{n}.png"
        page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=rect).save(path)
        written[n] = path
    return written


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf")
    ap.add_argument("numbers", type=int, nargs="+")
    ap.add_argument("--out", default="figs")
    a = ap.parse_args()
    for n, p in extract(a.pdf, a.numbers, a.out).items():
        print(f"figure {n} -> {p}")
