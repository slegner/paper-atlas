#!/usr/bin/env python3
"""Turn a research paper into a one-page HTML mind map.

    python3 paper_map.py paper.pdf            # local PDF
    python3 paper_map.py 2401.01234           # arXiv ID (or arxiv.org URL)
    python3 paper_map.py --from-json map.json # re-render a saved map, no API call
    python3 paper_map.py --from-json map.json --pdf paper.pdf  # ...and (re)crop its figures

Writes <name>.json (the extracted structure), <name>.figs/ (cropped figures) and <name>.html
(the mind map, figures embedded) next to the PDF, or into --out-dir.
"""
import argparse
import base64
import json
import re
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "template.html"
MODEL = "claude-opus-5-5"

ITEM = {
    "type": "object",
    "properties": {
        "headline": {"type": "string", "description": "At most 8 words. Plain language."},
        "detail": {"type": "string", "description": "1-3 short sentences expanding the headline."},
        "refs": {
            "type": "array",
            "items": {"type": "integer"},
            "description": "ids from `references` that back this point; empty if none",
        },
        "flag": {
            "type": "string",
            "enum": ["none", "key", "novel", "caveat"],
            "description": "novel = new in this paper; caveat = limitation/assumption a reader must know; "
                           "key = one of the few points to remember; none = everything else. Use sparingly.",
        },
    },
    "required": ["headline", "detail", "refs", "flag"],
    "additionalProperties": False,
}


RESULT = {
    "type": "object",
    "properties": {
        **ITEM["properties"],
        "condition": {
            "type": "string",
            "description": "What this result is conditional on, as a 1-3 word tag - the dataset, model or setting "
                           "(e.g. 'Planck only', 'Planck + SH0ES', 'ΛCDM', 'TorC', 'z > 1'). Reuse the exact same "
                           "wording for the same condition across analyses. Empty if the result is unconditional.",
        },
    },
    "required": ITEM["required"] + ["condition"],
    "additionalProperties": False,
}


def branch(description):
    return {"type": "array", "items": ITEM, "description": description}


SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "authors": {"type": "string", "description": "e.g. 'Smith, Lee & Patel' or 'Smith et al.'"},
        "year": {"type": "string"},
        "venue": {"type": "string", "description": "Journal/conference/arXiv; empty if unknown"},
        "tldr": {"type": "string", "description": "One sentence a non-specialist could follow."},
        "question": {
            "type": "object",
            "properties": {
                "short": {"type": "string", "description": "The core question, phrased as a question, at most 15 words."},
                "detail": {"type": "string", "description": "1-2 sentences of context."},
            },
            "required": ["short", "detail"],
            "additionalProperties": False,
        },
        "answer": {
            "type": "object",
            "properties": {
                "short": {"type": "string", "description": "Direct answer to the question, at most 20 words, with the headline number if there is one."},
                "detail": {"type": "string", "description": "1-2 sentences, including how confident the authors are."},
            },
            "required": ["short", "detail"],
            "additionalProperties": False,
        },
        "other_questions": {
            "type": "array",
            "description": "Only when the paper genuinely sets out to answer more than one big question: the 2nd (and 3rd) "
                           "questions, each with its own answer. Empty for most papers.",
            "items": {
                "type": "object",
                "properties": {
                    "short": {"type": "string", "description": "The question, at most 15 words."},
                    "detail": {"type": "string", "description": "1-2 sentences of context."},
                    "answer": {
                        "type": "object",
                        "properties": {
                            "short": {"type": "string", "description": "Direct answer, at most 20 words."},
                            "detail": {"type": "string", "description": "1-2 sentences."},
                        },
                        "required": ["short", "detail"],
                        "additionalProperties": False,
                    },
                    "separate": {"type": "boolean", "description": "true only if this question is answered by clearly distinct "
                                                                  "methods and results of its own (a paper of two halves); false "
                                                                  "when the questions share the same work."},
                },
                "required": ["short", "detail", "answer", "separate"],
                "additionalProperties": False,
            },
        },
        "why_important": branch("2-4 points: why anyone should care; what gap or tension motivates the work."),
        "background": branch("2-5 points: the prior knowledge a reader needs, citing the key earlier papers via refs."),
        "setup": branch("2-5 points: shared ingredients used by all analyses - model, data, code, sampler, sample."),
        "analyses": {
            "type": "array",
            "description": "2-6 analyses, each one thing the authors did and what came out of it. Together these "
                           "replace a separate methods and results list, so every result is tied to its method.",
            "items": {
                "type": "object",
                "properties": {
                    "method": {**ITEM, "description": "headline: the question this analysis answers, phrased as a question "
                                                     "(e.g. 'Do Planck and SH0ES agree?'). detail: one short line saying "
                                                     "how it was done (statistic, data, code)."},
                    "results": {
                        "type": "array",
                        "items": RESULT,
                        "description": "1-4 findings of this analysis, with numbers and uncertainties. When the "
                                       "outcome differs by dataset, model or setting, give one result per case "
                                       "with its `condition`, so the contrast is visible side by side.",
                    },
                    "question": {"type": "integer", "description": "Which big question this analysis answers: 1 = `question`, "
                                                                 "2 = the first of `other_questions`, and so on."},
                },
                "required": ["method", "results", "question"],
                "additionalProperties": False,
            },
        },
        "conclusion": branch("2-4 points: what it means, plus the main limitations/caveats and open questions."),
        "figures": {
            "type": "array",
            "description": "The 3-8 figures a reader most needs (skip decorative ones), each attached to the part "
                           "of the map it supports.",
            "items": {
                "type": "object",
                "properties": {
                    "number": {"type": "integer", "description": "The figure number as printed in the paper."},
                    "caption": {"type": "string", "description": "1-2 plain sentences: what the figure shows and "
                                                                  "what to look at in it."},
                    "attach": {"type": "string", "description": "Where it belongs: 'why_important', 'background', "
                                                                 "'setup', 'conclusion', or 'results:N' for the Nth "
                                                                 "analysis (1-based)."},
                },
                "required": ["number", "caption", "attach"],
                "additionalProperties": False,
            },
        },
        "equations": {
            "type": "array",
            "description": "The 3-8 equations a reader most needs (definitions, the key result, the statistic used), each "
                           "attached to the part of the map it belongs to.",
            "items": {
                "type": "object",
                "properties": {
                    "latex": {"type": "string", "description": "The equation in LaTeX (KaTeX-compatible, no \\ce)."},
                    "meaning": {"type": "string", "description": "1 plain sentence: what the equation says."},
                    "symbols": {"type": "string", "description": "What the main symbols stand for, briefly; empty if obvious."},
                    "number": {"type": "string", "description": "The equation number as printed, e.g. '14' or '3.1'; empty if unnumbered."},
                    "attach": {"type": "string", "description": "Where it belongs, as for figures; several places may be "
                                                                 "comma-separated, e.g. 'setup,results:2'."},
                },
                "required": ["latex", "meaning", "symbols", "number", "attach"],
                "additionalProperties": False,
            },
        },
        "glossary": {
            "type": "array",
            "description": "3-8 jargon terms used in the map, explained in one plain sentence each.",
            "items": {
                "type": "object",
                "properties": {"term": {"type": "string"}, "meaning": {"type": "string"}},
                "required": ["term", "meaning"],
                "additionalProperties": False,
            },
        },
        "references": {
            "type": "array",
            "description": "Only papers cited in this paper's own reference list that the map refers to.",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "label": {"type": "string", "description": "Short form, e.g. 'Riess et al. 1998'"},
                    "title": {"type": "string", "description": "Full title if printed in the reference list, else empty"},
                    "doi": {"type": "string", "description": "Only if printed in the paper, else empty"},
                    "arxiv": {"type": "string", "description": "arXiv ID only if printed in the paper, else empty"},
                },
                "required": ["id", "label", "title", "doi", "arxiv"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "title", "authors", "year", "venue", "tldr", "question", "answer", "other_questions",
        "why_important", "background", "setup", "analyses", "conclusion",
        "figures", "equations", "glossary", "references",
    ],
    "additionalProperties": False,
}

PROMPT = """Read this paper and turn it into a mind map that lets a busy researcher understand it in under two minutes.

The map reads left to right: the central QUESTION the paper is trying to answer, then why it matters, background, a METHOD panel (the shared setup), a RESULTS panel (one card per analysis: the question it answers, how, and its outcome for each dataset/model), the conclusion, and the ANSWER on the right.

Guidelines:
- Plain, concrete language. Headlines are scannable phrases, not sentences.
- Pick the main question the paper is really about. Only if it truly sets out to answer a second (or third) big
  question - not a sub-step of the first - put it in `other_questions` with its own answer, and tag each analysis
  with the question it answers.
- The answer should directly answer that question.
- Keep numbers that matter (with uncertainties), drop ones that don't.
- For background, point to the specific earlier papers the authors build on, using `refs`. Take references only from the paper's own reference list; copy DOI/arXiv IDs only when they are printed there - never invent them.
- Be honest about limitations in the conclusion branch.
- Pick the figures that carry the argument (key results, the main comparison plot, a schematic that explains the
  idea) and attach each to the card or section it supports, with a caption that says what to look at.
- List the key equations in LaTeX with a plain-language meaning, attached where they are used.
- Highlight what matters with `flag`:
  - `novel`: the paper's own contribution - a new result, model, mechanism, dataset or technique that the cited prior
    work had not produced (cite that work via refs). Established methods, statistics, codes or datasets are not
    novel just because they are applied to a new model; standard analysis steps are `none`. Most papers have 1-2
    novel points. Say "first" only if the paper itself claims it.
  - `caveat`: what a careful referee would worry about - missing physics, strong assumptions, priors or inputs
    driving the result, weak statistics - including weak spots the authors downplay.
  - `key`: the 3-6 central points to remember, including at least one in `conclusion`.
  Most items should be `none`; if everything is highlighted, nothing is.
"""


def load_pdf(source):
    """Return (pdf_bytes, stem) for a local path, arXiv ID or arXiv URL."""
    path = Path(source).expanduser()
    if path.exists():
        return path.read_bytes(), path.stem
    m = re.search(r"(\d{4}\.\d{4,5}(v\d+)?|[a-z\-]+(\.[A-Z]{2})?/\d{7}(v\d+)?)$",
                  source.strip().rstrip("/").replace(".pdf", ""))
    if not m:
        sys.exit(f"Not a file or arXiv ID: {source}")
    arxiv_id = m.group(1)
    url = f"https://arxiv.org/pdf/{arxiv_id}"
    print(f"Downloading {url} ...")
    req = urllib.request.Request(url, headers={"User-Agent": "paper-map/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read(), "arxiv-" + arxiv_id.replace("/", "_")


def extract(pdf_bytes, effort, schema=SCHEMA, prompt=PROMPT):
    import anthropic

    client = anthropic.Anthropic()
    print(f"Asking {MODEL} to map the paper (this takes a minute or two) ...")
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=64000,
        thinking={"type": "adaptive"},
        output_config={
            "effort": effort,
            "format": {"type": "json_schema", "schema": schema},
        },
        # If a safety classifier declines, the API retries on a fallback model.
        betas=["server-side-fallback-2026-07-01"],
        extra_body={"fallbacks": "default"},
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": base64.standard_b64encode(pdf_bytes).decode(),
                    },
                },
                {"type": "text", "text": prompt},
            ],
        }],
    ) as stream:
        response = stream.get_final_message()

    if response.stop_reason == "refusal":
        sys.exit("The model declined to process this paper.")
    if response.stop_reason == "max_tokens":
        sys.exit("Output was cut off (max_tokens). Try --effort medium.")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


def crop_figures(data, pdf_bytes, fig_dir):
    """Crop the figures the map names out of the PDF into fig_dir (needs PyMuPDF)."""
    numbers = sorted({f["number"] for f in data.get("figures", [])})
    if not numbers:
        return
    try:
        import figures
    except ImportError:
        sys.path.insert(0, str(HERE))
        import figures
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
        tmp.write(pdf_bytes)
        tmp.flush()
        try:
            got = figures.extract(tmp.name, numbers, fig_dir)
        except ImportError:
            print("Figures skipped: install PyMuPDF (pip install pymupdf) to crop them.")
            return
    print(f"Cropped {len(got)}/{len(numbers)} figures into {fig_dir}")


def render(data, out_html, fig_dir=None):
    data = with_figures(data, fig_dir)
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.read_text().replace("__PAPER_DATA__", payload)
    html = html.replace("__PAGE_TITLE__", escape(data.get("title", "Paper map")))
    out_html.write_text(html)


def with_figures(data, fig_dir=None):
    # Embed cropped figures as data URIs so the HTML stays a single self-contained file.
    data = dict(data)
    figs = []
    for f in data.get("figures", []):
        png = fig_dir / f"fig{f['number']}.png" if fig_dir else None
        if png and png.exists():
            figs.append({**f, "src": "data:image/png;base64," + base64.b64encode(png.read_bytes()).decode()})
        else:
            print(f"  figure {f['number']}: no image in {fig_dir} (pass --pdf to crop it), left out")
    data["figures"] = figs
    return data


def escape(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", help="PDF path, arXiv ID/URL, or a .json map with --from-json")
    ap.add_argument("--from-json", action="store_true", help="re-render an existing map without calling the API")
    ap.add_argument("--out-dir", type=Path, help="where to write the .json and .html")
    ap.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    ap.add_argument("--pdf", help="with --from-json: the paper's PDF (or arXiv ID) to crop figures from")
    ap.add_argument("--open", action="store_true", help="open the result in your browser")
    args = ap.parse_args()

    pdf_bytes = None
    if args.from_json:
        src = Path(args.source).expanduser()
        data, stem, default_dir = json.loads(src.read_text()), src.stem, src.parent
        if args.pdf:
            pdf_bytes, _ = load_pdf(args.pdf)
    else:
        pdf_bytes, stem = load_pdf(args.source)
        p = Path(args.source).expanduser()
        default_dir = p.parent if p.exists() else Path.cwd()
        data = extract(pdf_bytes, args.effort)

    out_dir = args.out_dir or default_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    out_html = out_dir / f"{stem}.html"
    if not args.from_json:
        (out_dir / f"{stem}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))
    fig_dir = out_dir / f"{stem}.figs"
    if pdf_bytes:
        crop_figures(data, pdf_bytes, fig_dir)
    render(data, out_html, fig_dir)
    print(f"Wrote {out_html}")
    if args.open:
        import webbrowser
        webbrowser.open(out_html.resolve().as_uri())


if __name__ == "__main__":
    main()
