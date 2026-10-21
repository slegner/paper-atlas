#!/usr/bin/env python3
"""Turn a research paper into a learning map: the concepts a newcomer needs, and where to learn each one.

    python3 roots_map.py paper.pdf            # local PDF
    python3 roots_map.py 2401.01234           # arXiv ID (or arxiv.org URL)
    python3 roots_map.py --from-json map.roots.json  # re-render a saved map, no API call

Where paper_map.py shows the paper as it is written, this traces it back to its roots: every concept
the introduction, methods and results lean on, ordered from the most basic up to this paper, each with
a "start here" textbook/review and the classic or direct-predecessor papers behind it.

Writes <name>.roots.json and <name>.roots.html next to the PDF, or into --out-dir.
"""
import argparse
import json
from pathlib import Path

from paper_map import escape, extract, load_pdf

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "roots_template.html"

READ_ROLES = ["start", "deeper", "origin", "builds_on"]

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "authors": {"type": "string", "description": "e.g. 'Smith, Lee & Patel' or 'Smith et al.'"},
        "year": {"type": "string"},
        "venue": {"type": "string", "description": "Journal/conference/arXiv; empty if unknown"},
        "tldr": {"type": "string", "description": "One sentence a non-specialist could follow."},
        "newcomer": {"type": "string", "description": "2-3 sentences: what field(s) this sits in and what a reader "
                                                       "from outside them is missing, in plain words."},
        "sections": {
            "type": "array",
            "description": "4-7 groups of concepts, following the paper's own parts (introduction/motivation, "
                           "background, each distinct part of the method, results, discussion). The first group "
                           "may be 'Basics used throughout' for general foundations.",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "short lowercase id, e.g. 'intro'"},
                    "name": {"type": "string", "description": "2-5 words, e.g. 'Earth's oxygen history'"},
                    "where": {"type": "string", "description": "Paper sections it covers, e.g. '§1' or '§3b–d'"},
                    "summary": {"type": "string", "description": "1 plain sentence: what this area is and why it matters."},
                    "role": {"type": "string", "description": "1 sentence: what this area contributes to this paper."},
                    "key_reads": {"type": "array", "items": {"type": "string"},
                                  "description": "1-3 ids from `readings`: the best way into this area as a whole."},
                },
                "required": ["key", "name", "where", "summary", "role", "key_reads"],
                "additionalProperties": False,
            },
        },
        "concepts": {
            "type": "array",
            "description": "15-40 concepts a reader with no background in the field must learn to follow the paper. "
                           "Cover the introduction, methods, results and discussion - each brings its own concepts. "
                           "Include general foundations (e.g. 'chemical kinetics', 'radiative transfer') as well as "
                           "the specialised ideas the paper builds on directly.",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "short kebab-case id"},
                    "name": {"type": "string", "description": "At most 6 words."},
                    "section": {"type": "string", "description": "`key` of the section where the paper uses it most"},
                    "level": {"type": "integer", "enum": [1, 2, 3, 4],
                              "description": "1 = foundation (intro undergrad), 2 = core of the field (advanced "
                                             "undergrad), 3 = specialist (graduate), 4 = the research frontier this "
                                             "paper directly extends."},
                    "plain": {"type": "string", "description": "1-2 sentences explaining it to an outsider."},
                    "why_here": {"type": "string", "description": "1 sentence: what the paper uses it for."},
                    "terms": {"type": "array", "items": {"type": "string"},
                              "description": "1-6 words or short phrases, exactly as they appear in the paper's text "
                                             "(e.g. 'Schumann–Runge', 'HOₓ', 'zenith angle'), used to link mentions to "
                                             "this concept. Avoid generic words."},
                    "prereqs": {"type": "array", "items": {"type": "string"},
                                "description": "ids of other concepts to learn first (lower level), may be empty"},
                    "reads": {
                        "type": "array",
                        "description": "1-5 readings, ordered from easiest. Always include one `start` reading.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "reading": {"type": "string", "description": "id from `readings`"},
                                "role": {"type": "string", "enum": READ_ROLES,
                                         "description": "start = the most basic way in (textbook chapter, review, "
                                                        "lecture notes); deeper = the standard advanced text/review; "
                                                        "origin = the classic paper that introduced it; builds_on = the "
                                                        "recent paper(s) this work directly extends."},
                                "where": {"type": "string", "description": "Chapter/section if confidently known, else empty"},
                            },
                            "required": ["reading", "role", "where"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["id", "name", "section", "level", "plain", "why_here", "terms", "prereqs", "reads"],
                "additionalProperties": False,
            },
        },
        "readings": {
            "type": "array",
            "description": "Every book or paper named in `concepts`. Prefer works in the paper's own reference "
                           "list. Add uncited textbooks/reviews only when the reference list has nothing basic "
                           "enough, and only canonical works you are certain exist.",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "label": {"type": "string", "description": "e.g. 'Jacob 1999' or 'Chapman 1930'"},
                    "title": {"type": "string"},
                    "kind": {"type": "string", "enum": ["textbook", "review", "classic", "paper", "popular", "notes"]},
                    "cited": {"type": "integer", "description": "Its number in this paper's reference list, or 0 if "
                                                                 "it is not cited there (a suggestion)."},
                    "doi": {"type": "string", "description": "Only if printed in the paper, else empty"},
                    "arxiv": {"type": "string", "description": "Only if printed in the paper, else empty"},
                    "url": {"type": "string", "description": "Only for a well-known free online edition, else empty"},
                    "note": {"type": "string", "description": "Optional few words, e.g. 'free online', 'very readable'"},
                },
                "required": ["id", "label", "title", "kind", "cited", "doi", "arxiv", "url", "note"],
                "additionalProperties": False,
            },
        },
        "shortlist": {"type": "array", "items": {"type": "string"},
                      "description": "ids of the 3-5 readings that together cover the most ground for a newcomer"},
    },
    "required": ["title", "authors", "year", "venue", "tldr", "newcomer", "sections", "concepts",
                 "readings", "shortlist"],
    "additionalProperties": False,
}

PROMPT = """Read this paper and build a learning map for someone who has never worked in its field.

The question to answer is: if I read this paper cold, what do I need to learn first, and what is the most
basic book or paper for each piece? Go through the whole paper - the introduction's motivation, the
background, every ingredient of the method (physics, chemistry, statistics, numerics, data, instruments),
the results and the discussion - and list each concept it relies on. A typical paper needs 20-35.

For each concept:
- explain it plainly, say what the paper uses it for, and link it to the more basic concepts it rests on
  (prereqs), so the concepts form a ladder from foundations (level 1) to this paper's frontier (level 4);
- give readings from easiest to hardest: a `start` (the most basic way in: an introductory textbook chapter,
  a readable review, free lecture notes), then optionally `deeper`, the `origin` paper, and the recent work
  the paper `builds_on`.

Honesty rules:
- Take readings from the paper's reference list whenever it has a suitable one, and set `cited` to its number.
- The reference list rarely has the true basics. You may add uncited textbooks and reviews (`cited` = 0), but
  only canonical, widely used works you are certain exist, with their real titles and authors. Never invent a
  work, a DOI or a chapter number; leave `where` empty unless you are sure.
- Do not stretch: if a concept is only mentioned in passing, leave it out.

Group the concepts into the paper's big areas (`sections`), and for each area say in one line why it matters
and what it contributes to this paper.
"""


def render(data, out_html):
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.read_text().replace("__PAPER_DATA__", payload)
    html = html.replace("__PAGE_TITLE__", escape("Learning map: " + data.get("title", "paper")))
    out_html.write_text(html)


def check(data):
    """Warn about dangling ids, so a hand-written map renders without silent gaps."""
    ids = {c["id"] for c in data["concepts"]}
    reads = {r["id"] for r in data["readings"]}
    secs = {s["key"] for s in data["sections"]}
    for s in data["sections"]:
        for r in s.get("key_reads", []):
            if r not in reads:
                print(f"  section {s['key']}: unknown reading {r!r}")
    for c in data["concepts"]:
        for p in c["prereqs"]:
            if p not in ids:
                print(f"  {c['id']}: unknown prereq {p!r}")
        for r in c["reads"]:
            if r["reading"] not in reads:
                print(f"  {c['id']}: unknown reading {r['reading']!r}")
        if c["section"] not in secs:
            print(f"  {c['id']}: unknown section {c['section']!r}")
        if not any(r["role"] == "start" for r in c["reads"]):
            print(f"  {c['id']}: no 'start' reading")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", help="PDF path, arXiv ID/URL, or a .roots.json map with --from-json")
    ap.add_argument("--from-json", action="store_true", help="re-render an existing map without calling the API")
    ap.add_argument("--out-dir", type=Path, help="where to write the .json and .html")
    ap.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    ap.add_argument("--open", action="store_true", help="open the result in your browser")
    args = ap.parse_args()

    if args.from_json:
        src = Path(args.source).expanduser()
        data, default_dir = json.loads(src.read_text()), src.parent
        stem = src.name.removesuffix(".json").removesuffix(".roots")
    else:
        pdf_bytes, stem = load_pdf(args.source)
        p = Path(args.source).expanduser()
        default_dir = p.parent if p.exists() else Path.cwd()
        data = extract(pdf_bytes, args.effort, SCHEMA, PROMPT)

    out_dir = args.out_dir or default_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    if not args.from_json:
        (out_dir / f"{stem}.roots.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))
    check(data)
    out_html = out_dir / f"{stem}.roots.html"
    render(data, out_html)
    print(f"Wrote {out_html}")
    if args.open:
        import webbrowser
        webbrowser.open(out_html.resolve().as_uri())


if __name__ == "__main__":
    main()
