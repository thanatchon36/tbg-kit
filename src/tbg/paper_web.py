"""Build the web reader docs/paper/ from the filled paper (same text and numbers as the PDF).

`tbg paper` writes <workspace>/paper/: paper.tex, generated/macros.tex and tables, figures/. This module inlines
the generated tables, prepends the number macros, renders the result with pandoc and paper/reader.html (masthead,
abstract, a results strip whose numbers are the paper's own macros, contents, numbered sections), converts the
PDF figures to PNG, and copies the PDF next to the page. GitHub Pages serves docs/ at
https://thanatchon36.github.io/tbg-kit/. Requires pandoc on PATH.
"""
from __future__ import annotations

import html
import re
import shutil
import subprocess
from pathlib import Path

from .utils import LOG

REPO_URL = "https://github.com/thanatchon36/tbg-kit"
PAPER_URL = "https://thanatchon36.github.io/tbg-kit/paper/"
DATA_URL = "https://huggingface.co/datasets/thanatchon36/tbg-kit"
EXPLORER_URL = "https://thanatchon36.github.io/tbg-kit/explorer.html"
CONCEPT_DOI = ""                    # set once the first release is archived on Zenodo
NIGHT_FIGURES = {"galaxy_paper.png"}  # dark by design: no light plate

# (label, finding, detail) with \Macro names resolved from generated/macros.tex.
RESULTS = [
    ("Network", r"\NEntities{} entities linked by \NHoldings{} ownership ties",
     r"\NGroupsMulti{} groups control two or more firms, \NGroupsTenPlus{} control ten or more"),
    ("Ultimate owners", r"Families control \ShareFamilyTwenty{} of listed firms at the \ThresholdPct{} threshold",
     r"state \ShareStateTwenty{}, foreign parents \ShareForeignTwenty{}, widely held \ShareWidelyTwenty{}, "
     r"unresolved \ShareUnresolvedTwenty{}"),
    ("Pyramids", r"\SharePyramid{} of controlled listed firms sit inside pyramids",
     r"chains up to \MaxDepth{} layers deep, \MeanDepth{} on average"),
    ("Wedge", r"Control exceeds cash-flow rights by \MeanWedge{} pp on average",
     r"median \MedianWedge{} pp; mean cash-flow/control ratio \MeanCFCRRatio{}"),
    ("Finance–business", r"Bank groups share directors with \ShareBigGroupsBankInterlock{} of groups with 10+ firms",
     r"\NBankGroups{} bank groups, \NNexusPairs{} bank–group pairs"),
    ("Concentration", r"The ten largest groups hold \TopTenMcapShare{} of listed market value",
     r"largest group: \TopGroupLabel{} with \TopGroupFirms{} firms"),
]


def _macros(tex: str) -> dict[str, str]:
    """\\newcommand{\\Name}{value} -> {"Name": value} for argument-free macros."""
    out = {}
    for m in re.finditer(r"\\newcommand\{\\(\w+)\}\{", tex):
        i, depth = m.end(), 1
        while depth and i < len(tex):
            depth += {"{": 1, "}": -1}.get(tex[i], 0)
            i += 1
        out[m.group(1)] = tex[m.end():i - 1]
    return out


def _plain(s: str, mac: dict[str, str]) -> str:
    """Resolve \\Macro{} and the bits of LaTeX that appear in macro values into plain text."""
    for _ in range(3):
        s = re.sub(r"\\(\w+)(\{\})?", lambda m: mac.get(m.group(1), m.group(0)), s)
    s = s.replace("{,}", ",").replace("\\%", "%").replace("\\&", "&").replace("~", " ")
    s = re.sub(r"\\textit\{([^}]*)\}|\\emph\{([^}]*)\}", lambda m: m.group(1) or m.group(2), s)
    missing = re.findall(r"\\\w+", s)
    if missing:
        raise RuntimeError(f"results strip has unresolved macros: {missing}")
    return s.replace("{", "").replace("}", "")


def _flatten(paper_dir: Path, synthetic: bool) -> tuple[str, str, list[str]]:
    """paper.tex -> (LaTeX body pandoc can read, abstract, appendix section titles); tables inlined."""
    tex = (paper_dir / "paper.tex").read_text(encoding="utf-8")
    macros = (paper_dir / "generated" / "macros.tex").read_text(encoding="utf-8")
    body = tex.split(r"\begin{document}", 1)[1].split(r"\end{document}", 1)[0]
    body = re.sub(r"\\input\{(generated/[\w.-]+)\}",
                  lambda m: (paper_dir / (m.group(1) if m.group(1).endswith(".tex") else m.group(1) + ".tex"))
                  .read_text(encoding="utf-8"), body)
    body = re.sub(r"\\ifsynthetic(.*?)\\fi", lambda m: m.group(1) if synthetic else "", body, flags=re.DOTALL)
    appendix = re.findall(r"\\section\{([^}]*)\}", body.split(r"\appendix", 1)[1]) if r"\appendix" in body else []
    for cmd in (r"\maketitle", r"\PaperKeywordsLine", r"\appendix", r"\noindent"):
        body = body.replace(cmd, "")
    body = re.sub(r"\\bibliographystyle\{[^}]*\}|\\bibliography\{[^}]*\}", "", body)
    body = re.sub(r"\\(begin|end)\{small\}", "", body)
    abstract = re.search(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", body, re.DOTALL)
    body = body.replace(abstract.group(0), "") if abstract else body
    head = macros + "\n\\newcommand{\\thai}[1]{#1}\n"
    return head + body, head + (abstract.group(1) if abstract else ""), appendix


def _pandoc(args: list[str], text: str, cwd: Path) -> str:
    return subprocess.run(["pandoc", *args], input=text, capture_output=True, text=True, check=True,
                          cwd=str(cwd)).stdout


def _figures(page: str, paper_dir: Path, out_dir: Path) -> str:
    """Copy each figure next to the page; PDF figures are rendered to PNG (pypdfium2) for the browser."""
    (out_dir / "figures").mkdir(parents=True, exist_ok=True)

    def one(m: re.Match) -> str:
        name = m.group(1)
        src = paper_dir / "figures" / name
        if name.endswith(".pdf"):
            import pypdfium2 as pdfium
            png = name[:-4] + ".png"
            pdf = pdfium.PdfDocument(str(src))
            pdf[0].render(scale=200 / 72).to_pil().save(out_dir / "figures" / png, optimize=True)
            pdf.close()
            name = png
        else:
            shutil.copyfile(src, out_dir / "figures" / name)
        return f'src="figures/{name}"'

    return re.sub(r'src="figures/([\w.-]+)"', one, page)


def _number_captions(page: str) -> str:
    """Table and figure numbers in captions, in document order (the PDF numbers them the same way)."""
    count = {"caption": 0, "figcaption": 0}

    def caption(m: re.Match) -> str:
        tag, attrs, para = m.group(1), m.group(2), m.group(3) or ""
        count[tag] += 1
        word = "Table" if tag == "caption" else "Figure"
        return f"<{tag}{attrs}>{para}<b>{word} {count[tag]}.</b> "

    return re.sub(r"<(caption|figcaption)(\b[^>]*)>(\s*<p>)?", caption, page)


def _web_images(page: str) -> str:
    """Drop the PDF sizing, load lazily, and mark the dark galaxy map."""
    def img(m: re.Match) -> str:
        tag = re.sub(r'\s(?:style|width|height)="[^"]*"', "", m.group(0))
        name = re.search(r'src="figures/([^"]+)"', tag)
        extra = ' loading="lazy"'
        if name and name.group(1) in NIGHT_FIGURES:
            extra += ' class="night"'
        return tag.replace("<img ", f"<img{extra} ", 1)

    return re.sub(r"<img\b[^>]*>", img, page)


def build_web(paper_dir: Path, out_dir: Path, pdf: Path | None = None, synthetic: bool = True,
              template: Path | None = None) -> Path:
    """<workspace>/paper -> out_dir/index.html (+ figures/, paper.pdf)."""
    if shutil.which("pandoc") is None:
        raise RuntimeError("pandoc not found; install pandoc to build the web reader")
    template = template or paper_dir.parent.parent / "paper" / "reader.html"
    mac = _macros((paper_dir / "generated" / "macros.tex").read_text(encoding="utf-8"))
    body, abstract, appendix = _flatten(paper_dir, synthetic)
    abstract_html = _pandoc(["--from=latex", "--to=html5", "--mathml", "--wrap=none"], abstract, paper_dir)
    keywords = [k.strip() for k in _plain(r"\PaperKeywordsPlain", mac).split(",") if k.strip()]
    meta = ["--metadata=title:" + _plain(r"\PaperTitle", mac),
            "--metadata=author:" + _plain(r"\PaperAuthors", mac),
            "--metadata=date:" + ("Synthetic demonstration · data as of " if synthetic else "Data as of ")
            + _plain(r"\AsOfDate", mac),
            "--metadata=pagetitle:" + _plain(r"\PaperShortTitle", mac) + " · tbg-kit",
            "--metadata=description:Working paper: ownership, control and the finance-business nexus of "
            "Thailand's business groups.",
            "--metadata=link-citations:true"]
    meta += [f"--metadata=keywords:{k}" for k in keywords]
    page = _pandoc(["--from=latex", "--to=html5", "--mathml", "--wrap=none", "--standalone",
                    f"--template={template}", "--number-sections", "--toc", "--toc-depth=1",
                    "--citeproc", "--bibliography=references.bib", "--variable=abstract:" + abstract_html, *meta],
                   body, paper_dir)

    for letter, name in zip("ABCDEFGH", appendix):      # appendices are lettered, as in the PDF
        page = re.sub(r'(<span class="(?:header-section-number|toc-section-number)">)\d+(</span>\s*'
                      + re.escape(html.escape(name, quote=False)) + ")", rf"\g<1>{letter}\2", page)
    page = _number_captions(page)
    page = _web_images(page)
    page = _figures(page, paper_dir, out_dir)
    page = re.sub(r"<table\b[^>]*>\s*<caption>(.*?)</caption>(.*?)</table>",
                  r'<div class="tbl"><p class="tcap">\1</p><div class="tscroll"><table>\2</table></div></div>',
                  page, flags=re.DOTALL)
    page = re.sub(r"<colgroup>.*?</colgroup>\s*", "", page, flags=re.DOTALL)

    items = "\n".join(
        f'<li class="r r-ref"><span class="r-id">{html.escape(label)}</span>'
        f'<span class="r-text">{html.escape(_plain(finding, mac))}<small>{html.escape(_plain(detail, mac))}'
        f'</small></span></li>' for label, finding, detail in RESULTS)
    if synthetic:
        items += ('\n<li class="r r-null"><span class="r-id">Thai data</span><span class="r-text">Real-data results '
                  'pending<small>every number here comes from a synthetic world; make all on the real data replaces '
                  'them</small></span></li>')
    actions = ('<li><a href="paper.pdf">Download PDF</a></li>'
               f'<li><a href="{EXPLORER_URL}">Interactive explorer</a></li>'
               f'<li><a href="{REPO_URL}">Code and replication</a></li>'
               f'<li><a href="{DATA_URL}">Data (Hugging Face)</a></li>')
    if CONCEPT_DOI:
        actions += f'<li><a href="https://doi.org/{CONCEPT_DOI}">Zenodo archive</a></li>'
    title = _plain(r"\PaperTitle", mac)
    bib = ("@techreport{chongmankhong2026tbg,\n"
           "  author      = {Chongmankhong, Thanatchon},\n"
           f"  title       = {{{title}}},\n"
           "  year        = {2026},\n"
           "  type        = {Working paper},\n"
           + (f"  doi         = {{{CONCEPT_DOI}}},\n" if CONCEPT_DOI else "")
           + f"  url         = {{{PAPER_URL}}}\n}}")
    note = ("Headline numbers, taken from the same macros as the PDF. "
            + ("All of them come from the synthetic world and validate the pipeline, not the Thai economy. "
               "Amber: pipeline results; grey: pending." if synthetic else ""))
    colophon = ("<p>Rendered from <code>paper/paper.tex</code> by <code>tbg.paper_web</code> (<code>make web</code>). "
                "Every number is a macro filled from the results, exactly as in the PDF, which is authoritative."
                + (" This version uses synthetic data throughout: every company, person and number is fictional."
                   if synthetic else "") + "</p>")
    for marker, value in (("<!--ACTIONS-->", actions), ("<!--RESULTS-NOTE-->", note), ("<!--RESULTS-->", items),
                          ("<!--CITE-->", f"<h2>How to cite</h2><pre><code>{html.escape(bib)}</code></pre>"),
                          ("<!--COLOPHON-->", colophon)):
        if marker not in page:
            raise RuntimeError(f"reader.html lacks {marker}")
        page = page.replace(marker, value)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(page, encoding="utf-8")
    pdf = pdf or paper_dir / "paper.pdf"
    if pdf.exists():
        shutil.copyfile(pdf, out_dir / "paper.pdf")
    else:
        LOG.warning("no PDF at %s: the reader's Download PDF link will be broken", pdf)
    LOG.info("web reader: %s", out_dir / "index.html")
    return out_dir / "index.html"
