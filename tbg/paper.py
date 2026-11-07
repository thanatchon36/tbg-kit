"""Write LaTeX macros and tables from results/, copy figures, and compile paper.pdf with XeLaTeX.

The workspace folder <ws>/paper is self-contained: it can be uploaded to Overleaf (compiler: pdfLaTeX, or
XeLaTeX when Thai script is present). After a pdfLaTeX build, paper/arxiv_submission.zip is ready for arXiv.
"""
from __future__ import annotations

import math
import re
import shutil
import subprocess

import pandas as pd

from .analyze import UO_ORDER
from .utils import LOG, ensure_dir, latex_escape
from .viz_layout import GT_LABEL, load

THAI = re.compile(r"[\u0E00-\u0E7F](?:[\u0E00-\u0E7F\s]*[\u0E00-\u0E7F])?")
FIGS = ["galaxy_paper.png", "tree_top.pdf", "fig_uo.pdf", "fig_groups.pdf", "fig_wedge.pdf", "fig_nexus.pdf"]
ROBUST_COLS = {"threshold 10%": "10\\%", "threshold 20%": "20\\%", "threshold 50%": "50\\%",
               "no family aggregation": "No family agg.", "state investors as owners": "State funds as owners"}


def tex(s) -> str:
    """Escape for LaTeX and wrap Thai runs in \\thai{} so they get a Thai font."""
    return THAI.sub(lambda m: "\\thai{" + m.group(0) + "}", latex_escape(s))


def _ok(v) -> bool:
    return isinstance(v, (int, float)) and not (isinstance(v, float) and math.isnan(v))


def num(v) -> str:
    return f"{int(round(v)):,}".replace(",", "{,}") if _ok(v) else "n/a"


def pct(v, nd=1) -> str:
    return f"{v * 100:.{nd}f}\\%" if _ok(v) else "n/a"


def fx(v, nd=1, scale=1.0) -> str:
    return f"{v * scale:.{nd}f}" if _ok(v) else "n/a"


def _listed(U, t):
    return U[(U["threshold"] == t) & U["firm"].astype(str).str.startswith("L:")] if len(U) else U


def validation_statement(cfg) -> str:
    p = cfg["_paths"]["review"] / "validation_sample.csv"
    if p.exists():
        v = pd.read_csv(p, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        yes = {"1": 1, "yes": 1, "y": 1, "true": 1, "0": 0, "no": 0, "n": 0, "false": 0}
        ok = v.get("is_correct", pd.Series(dtype=str)).str.strip().str.lower().map(yes).dropna()
        if len(ok):
            return (f"A random sample of {len(ok)} listed firms was checked by hand against filings; the ultimate "
                    f"owner was identified correctly in {ok.mean() * 100:.1f}\\% of cases.")
    return ("A random sample of listed firms (\\texttt{review/validation\\_sample.csv}) awaits manual checking; its "
            "accuracy will be reported here.")


def author_list(pr) -> list[dict]:
    a = pr.get("authors") or []
    if isinstance(a, str):
        return [{"name": n.strip(), "affiliation": pr.get("affiliation") or "", "email": pr.get("email") or ""}
                for n in a.split(",") if n.strip()]
    return [x if isinstance(x, dict) else {"name": str(x)} for x in a]


def author_block(authors) -> str:
    cells = []
    for x in authors:
        lines = [f"\\textbf{{{tex(x.get('name', ''))}}}"]
        lines += [tex(x["affiliation"])] if x.get("affiliation") else []
        lines += [f"\\texttt{{{tex(x['email'])}}}"] if x.get("email") else []
        cells.append("\\begin{tabular}[t]{c}" + " \\\\ ".join(lines) + "\\end{tabular}")
    return " \\qquad ".join(cells) or "\\textbf{[Author]}"


def macros(cfg, D, synthetic) -> str:
    S, pr, t = D["S"], cfg["project"], cfg["ownership"]["group_threshold"]
    u = _listed(D["U"], t)
    dom = GT_LABEL.get(u["uo_type"].value_counts().idxmax(), "other").lower() if len(u) else "n/a"
    g = S.get
    authors = author_list(pr)
    kws = [str(k) for k in (pr.get("keywords") or [])]
    m = {
        "PaperTitle": tex(pr.get("title")), "PaperShortTitle": tex(pr.get("short_title") or pr.get("title")),
        "PaperAuthors": tex(" and ".join(a.get("name", "") for a in authors) or "[Author]"),
        "PaperAuthorBlock": author_block(authors), "PaperAffiliation": tex(pr.get("affiliation") or ""),
        "PaperKeywordsPlain": tex(", ".join(kws)),
        "PaperKeywordsLine": ("\\keywords{" + " \\,$\\cdot$\\, ".join(tex(k) for k in kws) + "}") if kws else "",
        "AsOfDate": tex(pr.get("as_of") or "n/a"),
        "DataYear": tex(pr.get("data_year") or "n/a"), "ThresholdPct": f"{round(t * 100)}\\%",
        "NEntities": num(g("n_entities")), "NHoldings": num(g("n_holdings")), "NGroupsMulti": num(g("n_groups_multi")),
        "NGroupsTenPlus": num(g("n_groups_10plus")), "NGroupsMultiListed": num(g("n_groups_multi_listed")),
        "ShareFamilyTwenty": pct(g("share_uo_family_20")), "ShareStateTwenty": pct(g("share_uo_state_20")),
        "ShareForeignTwenty": pct(g("share_uo_foreign_20")), "ShareCrownTwenty": pct(g("share_uo_crown_20")),
        "ShareWidelyTwenty": pct(g("share_uo_wh_20")), "ShareUnresolvedTwenty": pct(g("share_uo_unresolved_20")),
        "ShareFamilyTen": pct(g("share_uo_family_10")), "SharePyramid": pct(g("share_pyramid_listed")),
        "MeanWedge": fx(g("mean_wedge_listed"), 1, 100), "MedianWedge": fx(g("median_wedge_listed"), 1, 100),
        "MeanCFCRRatio": fx(g("mean_ratio_cf_cr"), 2), "MaxDepth": num(g("max_depth")),
        "MeanDepth": fx(g("mean_depth_all")), "NCycles": num(g("n_cycles")), "NFirmsInCycles": num(g("n_firms_in_cycles")),
        "TopGroupLabel": tex(g("top_group_label", "n/a")), "TopGroupFirms": num(g("top_group_firms")),
        "TopGroupIndustries": num(g("top_group_industries")), "MaxIndustries": num(g("max_industries")),
        "ShareAffiliated": pct(g("share_listed_group_affiliated")), "LargestWCCShare": pct(g("largest_wcc_share")),
        "TopTenMcapShare": pct(g("top10_groups_mcap_share")), "HHIGroups": num(g("hhi_groups_mcap")),
        "NFIEntities": num(g("n_fi_entities")), "NBanks": num(g("n_banks")), "NBankGroups": num(g("n_bank_groups")),
        "NNexusPairs": num(g("n_nexus_pairs")), "NDirectorLinks": num(g("n_director_links")),
        "NOwnershipLinks": num(g("n_ownership_links")), "NFundLinks": num(g("n_fund_links")),
        "ShareBigGroupsBankInterlock": pct(g("share_big_groups_bank_interlock")),
        "GLEIFPairs": num(g("gleif_pairs")), "GLEIFAgreement": pct(g("gleif_agreement")),
        "DominantUOType": tex(dom), "ValidationStatement": validation_statement(cfg),
    }
    out = ["% generated by tbg.paper -- do not edit"] + [f"\\newcommand{{\\{k}}}{{{v}}}" for k, v in m.items()]
    if synthetic:
        out.append("\\synthetictrue")
    return "\n".join(out) + "\n"


def _tab(colspec, header, rows, x=False) -> str:
    env = "tabularx" if x else "tabular"
    open_ = f"\\begin{{tabularx}}{{\\textwidth}}{{{colspec}}}" if x else f"\\begin{{tabular}}{{{colspec}}}"
    body = [" & ".join(str(c) for c in r) + " \\\\" for r in rows] or \
        [f"\\multicolumn{{{len(header)}}}{{l}}{{No data yet}} \\\\"]
    return "\n".join([open_, "\\toprule", " & ".join(header) + " \\\\", "\\midrule", *body, "\\bottomrule",
                      f"\\end{{{env}}}"]) + "\n"


def tables(cfg, D) -> dict[str, str]:
    S, U, E, G = D["S"], D["U"], D["E"], D["G"]
    th, t = cfg["ownership"]["thresholds"], cfg["ownership"]["group_threshold"]
    cov = [("Listed companies in the universe", num(S.get("n_listed"))),
           ("\\quad with top-10 shareholder data", num(S.get("n_listed_top10"))),
           ("\\quad with extracted subsidiary disclosures", num(S.get("n_listed_subs"))),
           ("Entities in the network", num(S.get("n_entities"))),
           ("\\quad companies registered in Thailand", num(S.get("n_companies"))),
           ("\\quad companies registered abroad", num(S.get("n_foreign"))),
           ("\\quad persons (before family aggregation)", num(S.get("n_persons"))),
           ("Families after aggregation", num(S.get("n_families"))),
           ("Ownership links", num(S.get("n_holdings"))),
           ("Board seats / distinct directors", f"{num(S.get('n_board_seats'))} / {num(S.get('n_directors'))}"),
           ("GLEIF parent relationships", num(S.get("gleif_pairs")))]
    cols = [_listed(U, x)["uo_type"].value_counts(normalize=True) for x in th]
    if len(U) and len(E):
        mc = pd.to_numeric(E.set_index("id")["market_cap"], errors="coerce")
        u = _listed(U, t)
        wv = u.assign(m=u["firm"].map(mc).fillna(0)).groupby("uo_type")["m"].sum()
        cols.append(wv / wv.sum() if wv.sum() > 0 else wv * 0)
    else:
        cols.append(pd.Series(dtype=float))
    types = [x for x in UO_ORDER if any(x in c.index for c in cols)]
    uo = [(tex(GT_LABEL.get(x, x)), *[pct(float(c.get(x, 0.0))) for c in cols]) for x in types]
    top = G.sort_values(["n_firms", "n_listed"], ascending=False).head(15)
    grp = [(int(r.rank), tex(r.label), tex(GT_LABEL.get(r.group_type, r.group_type)), num(r.n_firms), num(r.n_listed),
            num(r.n_foreign), num(r.n_industries), num(r.max_depth)) for r in top.itertuples()]
    N = D["N"].fillna({"bank_label": "?", "group_label": "?"}) if len(D["N"]) else D["N"]
    nex = [(tex(r.bank_label), tex(r.group_label), num(r.ownership), num(r.directors), num(r.funds))
           for r in N.head(10).itertuples()] if len(N) else []
    RB = D["RB"]
    rob, rcols = [], []
    if len(RB):
        piv = RB.pivot_table(index="uo_type", columns="spec", values="share", aggfunc="sum").fillna(0)
        rcols = [c for c in ROBUST_COLS if c in piv.columns]
        rtypes = [x for x in UO_ORDER if x in piv.index] + [x for x in piv.index if x not in UO_ORDER]
        rob = [(tex(GT_LABEL.get(x, x)), *[pct(piv.at[x, c]) for c in rcols]) for x in rtypes]
    return {
        "tab_coverage": _tab("lr", ["", "Count"], cov),
        "tab_uo": _tab("lrrrr", ["Ultimate owner", *[f"{round(x * 100)}\\%" for x in th], "By value"], uo),
        "tab_groups": _tab("rXlrrrrr", ["\\#", "Group", "Ultimate owner", "Firms", "Listed", "Abroad", "Ind.", "Depth"],
                           grp, x=True),
        "tab_nexus": _tab("XXrrr", ["Bank group", "Business group", "Own.", "Dir.", "Funds"], nex, x=True),
        "tab_robust": _tab("l" + "r" * len(rcols), ["Ultimate owner", *[ROBUST_COLS[c] for c in rcols]], rob),
    }


def _placeholder(path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(6, 2))
    ax.axis("off")
    ax.text(0.5, 0.5, "Figure not generated yet: run python -m tbg figures", ha="center", va="center")
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _clean(folder) -> None:
    for ext in ("aux", "bbl", "blg", "fdb_latexmk", "fls", "log", "out", "xdv", "toc"):
        (folder / f"paper.{ext}").unlink(missing_ok=True)


def compile_tex(folder, engine="pdflatex"):
    lmk, exe, bib = shutil.which("latexmk"), shutil.which(engine), shutil.which("bibtex")
    if lmk:
        cmds = [[lmk, "-pdf" if engine == "pdflatex" else "-xelatex", "-interaction=nonstopmode", "-halt-on-error",
                 "-file-line-error", "paper.tex"]]
    elif exe:
        x = [exe, "-interaction=nonstopmode", "-halt-on-error", "paper.tex"]
        cmds = [x] + ([[bib, "paper"]] if bib else []) + [x, x]
    else:
        LOG.error("%s not found. Install TeX Live or MiKTeX, or upload %s to Overleaf (compiler: %s).", engine, folder,
                  "pdfLaTeX" if engine == "pdflatex" else "XeLaTeX")
        return None
    _clean(folder)
    for c in cmds:
        r = subprocess.run(c, cwd=folder, capture_output=True, text=True, timeout=900)
        if r.returncode != 0 and "bibtex" not in c[0]:
            log = (folder / "paper.log").read_text(errors="ignore") if (folder / "paper.log").exists() else r.stdout
            errs = [ln for ln in log.splitlines() if ln.startswith("!") or ".tex:" in ln][:15]
            LOG.error("LaTeX failed:\n%s", "\n".join(errs) or log[-2500:])
            return None
    pdf = folder / "paper.pdf"
    LOG.info("paper (%s): %s", engine, pdf)
    return pdf if pdf.exists() else None


def arxiv_bundle(folder):
    """paper.tex + paper.bbl + generated tables + figures: the files arXiv needs (it does not run BibTeX)."""
    import zipfile
    bbl = folder / "paper.bbl"
    if not bbl.exists():
        LOG.warning("no paper.bbl, arXiv bundle skipped")
        return None
    files = [folder / "paper.tex", bbl, *sorted((folder / "generated").glob("*.tex")),
             *[folder / "figures" / f for f in FIGS]]
    z = folder / "arxiv_submission.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in files:
            if p.exists():
                zf.write(p, p.relative_to(folder).as_posix())
    LOG.info("arXiv bundle: %s (%.1f MB)", z, z.stat().st_size / 1e6)
    return z


def build_paper(cfg, synthetic=False):
    P, pc = cfg["_paths"], cfg["paper"]
    D = load(cfg)
    if D["G"].empty:
        LOG.error("no results yet: run `python -m tbg analyze` first")
        return None
    out = ensure_dir(P["paper"])
    gen, figs = ensure_dir(out / "generated"), ensure_dir(out / "figures")
    (gen / "macros.tex").write_text(macros(cfg, D, synthetic), encoding="utf-8")
    for name, content in tables(cfg, D).items():
        (gen / f"{name}.tex").write_text(content, encoding="utf-8")
    thai = any(THAI.search(p.read_text(encoding="utf-8")) for p in gen.glob("*.tex"))
    engine = pc.get("engine", "auto")
    if engine == "auto":
        engine = "xelatex" if thai else "pdflatex"
    elif engine == "pdflatex" and thai:
        LOG.warning("Thai script in names cannot be set by pdfLaTeX: using XeLaTeX. Romanise those names for arXiv.")
        engine = "xelatex"
    src = (P["paper_src"] / "paper.tex").read_text(encoding="utf-8")
    (out / "paper.tex").write_text(("\\pdfoutput=1\n" if engine == "pdflatex" else "") + src, encoding="utf-8")
    shutil.copy(P["paper_src"] / "references.bib", out / "references.bib")
    for f in FIGS:
        src_f = P["figures"] / f
        if src_f.exists():
            shutil.copy(src_f, figs / f)
        else:
            _placeholder(figs / f)
    if not pc.get("compile", True):
        return out / "paper.tex"
    pdf = compile_tex(out, engine)
    if pdf and engine == "pdflatex" and pc.get("arxiv_bundle", True):
        arxiv_bundle(out)
    return pdf
