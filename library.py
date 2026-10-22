#!/usr/bin/env python3
"""Join every paper you have mapped into one reading map (the "library").

    python3 library.py                         # rebuild maps/library.html from all saved maps
    python3 library.py --suggest arxiv-2607.25672   # ask Claude how a new paper connects (needs ANTHROPIC_API_KEY)

Each paper with a saved map (<stem>.json) and learning map (<stem>.roots.json) in maps/ becomes a circle.
Papers sit in the research areas they belong to, and lines join papers that connect:

  * found automatically: one paper cites the other, both draw on the same reading, or both use a
    concept with the same name or term;
  * written in maps/library.json: areas, a note on how two papers connect (with the concepts that
    bridge them), and "threads" that run through several papers.

library.json looks like
    {"areas": [{"key": "cosmo", "name": "Cosmology & gravity", "blurb": "..."}],
     "papers": {"arxiv-2507.09228": {"short": "TorC", "areas": ["cosmo"], "added": "2026-10-21"}},
     "links": [{"a": "<stem>", "b": "<stem>", "kind": "builds_on|same_method|same_topic|contrast",
                "title": "...", "note": "...", "ideas": [["<concept id in a>", "<concept id in b>"]]}],
     "threads": [{"name": "...", "note": "...", "papers": ["<stem>", ...]}]}
Papers missing from it land in an "Unsorted" area until they are given one (by hand or with --suggest).
Entries for papers you keep to yourself can go in maps/library.local.json (same format, gitignored), which is
merged in when the page is built.
"""
import argparse
import itertools
import json
import re
import sys
from pathlib import Path

import paper_map

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "library_template.html"
KINDS = ["builds_on", "same_method", "same_topic", "contrast"]

SUGGEST_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["short", "areas", "new_areas", "links", "threads"],
    "properties": {
        "short": {"type": "string", "description": "2-4 word name for the paper's circle"},
        "areas": {"type": "array", "items": {"type": "string"}, "description": "area keys, home area first"},
        "new_areas": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["key", "name", "blurb"],
            "properties": {"key": {"type": "string"}, "name": {"type": "string"}, "blurb": {"type": "string"}}}},
        "links": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["other", "kind", "title", "note", "ideas"],
            "properties": {
                "other": {"type": "string", "description": "stem of the earlier paper"},
                "kind": {"type": "string", "enum": KINDS},
                "title": {"type": "string", "description": "the connection in under 8 words"},
                "note": {"type": "string", "description": "1-3 plain sentences on how the two papers connect"},
                "ideas": {"type": "array", "items": {"type": "array", "items": {"type": "string"}},
                          "description": "pairs [concept id in the new paper, concept id in the other paper]"}}}},
        "threads": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["name", "note", "papers"],
            "properties": {"name": {"type": "string"}, "note": {"type": "string"},
                           "papers": {"type": "array", "items": {"type": "string"}}}}},
    },
}

SUGGEST_PROMPT = """You keep a researcher's reading map. Below are the papers already on it (with their areas,
key concepts and the existing connections), followed by a NEW paper. Place the new paper:

- areas: pick existing area keys where it belongs (home area first); add a new area only if none fits.
- links: connect it to earlier papers only where a reader would genuinely gain from the connection: it builds
  on the other (builds_on), uses the same approach or kind of analysis (same_method), studies the same thing
  (same_topic), or reaches a different conclusion on a shared question (contrast). Skip weak or generic links
  ("both use statistics"). Give 0-3 concept id pairs that bridge them, using ids from the lists below.
- threads: name a thread only if the new paper joins an existing one or starts one with at least one other paper.
Write for someone who has read the papers but not recently: plain, specific, short.

EXISTING MAP
{existing}

NEW PAPER
{new}
"""


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()


def load_papers(maps_dir):
    """{stem: {"paper": ..., "roots": ...}} for every stem with both maps."""
    out = {}
    for f in sorted(maps_dir.glob("*.roots.json")):
        stem = f.name[: -len(".roots.json")]
        p = maps_dir / f"{stem}.json"
        if p.exists():
            out[stem] = {"paper": json.loads(p.read_text()), "roots": json.loads(f.read_text())}
    return out


def arxiv_of(stem, paper):
    m = re.search(r"(\d{4}\.\d{4,5})", stem + " " + paper.get("venue", ""))
    return m.group(1) if m else ""


def auto_links(papers):
    """Citations, shared readings and same-named concepts between every pair of papers."""
    ids = {s: arxiv_of(s, d["paper"]) for s, d in papers.items()}
    reading_key = lambda r: r.get("arxiv") or norm(r.get("title", ""))[:60]
    links = []
    for a, b in itertools.combinations(papers, 2):
        link = {"a": a, "b": b, "cites": [], "readings": [], "concepts": []}
        for x, y in ((a, b), (b, a)):
            cited = {r.get("arxiv") for r in papers[x]["roots"].get("readings", [])}
            cited |= {r.get("arxiv") for r in papers[x]["paper"].get("references", [])}
            if ids[y] and ids[y] in cited:
                link["cites"].append([x, y])
        rb = {reading_key(r): r for r in papers[b]["roots"].get("readings", [])}
        for r in papers[a]["roots"].get("readings", []):
            if reading_key(r) and reading_key(r) in rb:
                link["readings"].append(r["label"])
        for ca in papers[a]["roots"].get("concepts", []):
            ta = {norm(t) for t in ca.get("terms", []) + [ca["name"]]} - {""}
            for cb in papers[b]["roots"].get("concepts", []):
                if ta & ({norm(t) for t in cb.get("terms", []) + [cb["name"]]}):
                    link["concepts"].append([ca["id"], cb["id"]])
        if link["cites"] or link["readings"] or link["concepts"]:
            links.append(link)
    return links


def summary(stem, d, lib):
    """A compact description of one paper for the --suggest prompt."""
    p, r = d["paper"], d["roots"]
    info = lib.get("papers", {}).get(stem, {})
    concepts = "; ".join(f"{c['id']}={c['name']}" for c in r.get("concepts", []))
    return (f"[{stem}] {p.get('title', '')} ({p.get('year', '')})\n  areas: {', '.join(info.get('areas', [])) or '-'}\n"
            f"  TL;DR: {p.get('tldr', '')}\n  question: {p.get('question', {}).get('short', '')}\n"
            f"  answer: {p.get('answer', {}).get('short', '')}\n  concepts: {concepts}")


def suggest(stem, papers, lib, effort):
    import anthropic

    others = [s for s in papers if s != stem]
    existing = "\n\n".join(summary(s, papers[s], lib) for s in others)
    existing += "\n\nAREAS: " + "; ".join(f"{a['key']}={a['name']}" for a in lib.get("areas", []))
    existing += "\nLINKS: " + "; ".join(f"{l['a']}–{l['b']}: {l['title']}" for l in lib.get("links", []))
    existing += "\nTHREADS: " + "; ".join(f"{t['name']} ({', '.join(t['papers'])})" for t in lib.get("threads", []))
    prompt = SUGGEST_PROMPT.replace("{existing}", existing).replace("{new}", summary(stem, papers[stem], lib))
    client = anthropic.Anthropic()
    print(f"Asking {paper_map.MODEL} how {stem} connects to {len(others)} earlier papers ...")
    # Same call as paper_map.extract, with text in place of the PDF.
    with client.beta.messages.stream(
        model=paper_map.MODEL, max_tokens=16000, thinking={"type": "adaptive"},
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": SUGGEST_SCHEMA}},
        betas=["server-side-fallback-2026-07-01"], extra_body={"fallbacks": "default"},
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        response = stream.get_final_message()
    if response.stop_reason == "refusal":
        sys.exit("The model declined.")
    s = json.loads(next(b.text for b in response.content if b.type == "text"))

    lib.setdefault("areas", []).extend(a for a in s["new_areas"] if a["key"] not in {x["key"] for x in lib["areas"]})
    from datetime import date
    lib.setdefault("papers", {})[stem] = {"short": s["short"], "areas": s["areas"], "added": date.today().isoformat()}
    lib["links"] = [l for l in lib.get("links", []) if stem not in (l["a"], l["b"])]
    lib["links"] += [{"a": stem, "b": l["other"], "kind": l["kind"], "title": l["title"], "note": l["note"], "ideas": l["ideas"]}
                     for l in s["links"] if l["other"] in papers]
    threads = {t["name"]: t for t in lib.setdefault("threads", [])}
    for t in s["threads"]:
        if t["name"] in threads:
            threads[t["name"]]["papers"] = sorted(set(threads[t["name"]]["papers"]) | set(t["papers"]))
        else:
            lib["threads"].append(t)
    for l in s["links"]:
        print(f"  {l['kind']:12s} {l['other']}: {l['title']}")


def check(papers, lib):
    """Warn about ids in library.json that point nowhere, so a hand-written entry renders without gaps."""
    areas = {a["key"] for a in lib.get("areas", [])}
    for stem, info in lib.get("papers", {}).items():
        if stem not in papers:
            print(f"  library.json: no saved maps for {stem!r}, skipped")
        for a in info.get("areas", []):
            if a not in areas:
                print(f"  {stem}: unknown area {a!r}")
    for l in lib.get("links", []):
        if l["a"] in papers and l["b"] in papers:
            ca = {c["id"] for c in papers[l["a"]]["roots"]["concepts"]}
            cb = {c["id"] for c in papers[l["b"]]["roots"]["concepts"]}
            for x, y in l.get("ideas", []):
                if x not in ca or y not in cb:
                    print(f"  link {l['a']}–{l['b']}: unknown concept pair {x!r}/{y!r}")
    for stem in papers:
        if stem not in lib.get("papers", {}):
            print(f"  {stem}: not in library.json yet, shown as Unsorted")


def load_library(maps_dir):
    """library.json, plus library.local.json (gitignored) for papers kept off the shared copy."""
    lib_path, local_path = maps_dir / "library.json", maps_dir / "library.local.json"
    lib = json.loads(lib_path.read_text()) if lib_path.exists() else {}
    if local_path.exists():
        local = json.loads(local_path.read_text())
        lib.setdefault("areas", []).extend(a for a in local.get("areas", []) if a["key"] not in {x["key"] for x in lib["areas"]})
        lib.setdefault("papers", {}).update(local.get("papers", {}))
        lib.setdefault("links", []).extend(local.get("links", []))
        threads = {t["name"]: t for t in lib.setdefault("threads", [])}
        for t in local.get("threads", []):
            if t["name"] in threads:
                threads[t["name"]]["papers"] = threads[t["name"]]["papers"] + [p for p in t["papers"] if p not in threads[t["name"]]["papers"]]
                threads[t["name"]]["note"] = t.get("note") or threads[t["name"]]["note"]
            else:
                lib["threads"].append(t)
    return lib


def build(maps_dir, out_html=None, quiet=False):
    papers = load_papers(maps_dir)
    lib = load_library(maps_dir)
    if not quiet:
        check(papers, lib)
    # Only what the page shows: the paper card and the concepts, not the full maps.
    slim = {}
    for stem, d in papers.items():
        p, r = d["paper"], d["roots"]
        slim[stem] = {
            "title": p.get("title", ""), "authors": p.get("authors", ""), "year": p.get("year", ""),
            "venue": p.get("venue", ""), "arxiv": arxiv_of(stem, p), "tldr": p.get("tldr", ""),
            "questions": [{"q": p.get("question", {}).get("short", ""), "a": p.get("answer", {}).get("short", "")}] +
                         [{"q": o.get("short", ""), "a": o.get("answer", {}).get("short", "")} for o in p.get("other_questions", [])],
            "concepts": {c["id"]: {"name": c["name"], "plain": c.get("plain", ""), "why_here": c.get("why_here", "")}
                         for c in r.get("concepts", [])},
            "atlas": f"{stem}.atlas.html" if (maps_dir / f"{stem}.atlas.html").exists() else "",
        }
    data = {"papers": slim, "library": lib, "auto": auto_links(papers)}
    out_html = out_html or maps_dir / "library.html"
    html = TEMPLATE.read_text().replace("__LIBRARY_DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    out_html.write_text(html)
    print(f"Wrote {out_html} ({len(papers)} papers)")
    return out_html


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--maps", type=Path, default=HERE / "maps", help="folder of saved maps (default: maps/)")
    ap.add_argument("--out", type=Path, help="output HTML (default: <maps>/library.html)")
    ap.add_argument("--suggest", metavar="STEM", help="ask Claude to place this paper and write its connections")
    ap.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    ap.add_argument("--open", action="store_true", help="open the result in your browser")
    args = ap.parse_args()

    if args.suggest:
        papers = load_papers(args.maps)
        if args.suggest not in papers:
            sys.exit(f"No saved maps for {args.suggest} in {args.maps}")
        lib_path = args.maps / "library.json"
        lib = json.loads(lib_path.read_text()) if lib_path.exists() else {}
        suggest(args.suggest, papers, lib, args.effort)
        lib_path.write_text(json.dumps(lib, indent=2, ensure_ascii=False) + "\n")
        print(f"Updated {lib_path}")
    out = build(args.maps, args.out)
    if args.open:
        import webbrowser
        webbrowser.open(out.resolve().as_uri())


if __name__ == "__main__":
    main()
