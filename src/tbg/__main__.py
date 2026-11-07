"""Command line:  python -m tbg <command>   (run `python -m tbg -h` for help)."""
from __future__ import annotations

import argparse
import sys

from .config import load_config
from .utils import LOG, setup_logging


def _demo_cfg(cfg, info):
    cfg["_paths"]["seeds"] = cfg["_paths"]["manual"] / "seeds.yaml"
    cfg["fi"]["amc_brand_map"] = info.get("brand_map", {})
    cfg["project"].update({"data_year": 2025, "as_of": "2026-03-31"})
    return cfg


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="tbg", description="Thai business-group ownership network toolkit")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--workspace", help="override workspace folder (default from config)")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("demo", help="synthetic end-to-end run into ./demo (figures, explorer, paper.pdf)")
    sub.add_parser("synth", help="write synthetic raw data only")
    c = sub.add_parser("collect", help="download public data")
    c.add_argument("what", choices=["gleif", "set-universe", "set-shareholders", "documents"])
    c.add_argument("--tickers", help="comma-separated tickers (default: universe)")
    c.add_argument("--lang", default="en")
    c.add_argument("--limit", type=int)
    e = sub.add_parser("extract", help="find pages in PDFs and extract tables with Claude")
    e.add_argument("action", choices=["pages", "run", "collect-batch"])
    e.add_argument("--kind", default="subsidiaries",
                   choices=["subsidiaries", "shareholders", "directors", "pillar3", "boj5"])
    e.add_argument("--batch", action="store_true", help="use the Message Batches API (cheaper, async)")
    e.add_argument("--limit", type=int)
    e.add_argument("--dry-run", action="store_true")
    for name, hlp in [("build", "raw -> processed tables"), ("analyze", "ownership, groups, metrics"),
                      ("figures", "all static figures"), ("explorer", "interactive HTML network"),
                      ("paper", "LaTeX tables/macros + compile paper.pdf"), ("all", "build..paper"),
                      ("web", "web reader of the paper -> docs/paper/ (needs pandoc; run paper first)"),
                      ("status", "coverage report and review queues"),
                      ("init", "create workspace folders and blank input files")]:
        sub.add_parser(name, help=hlp)
    args = ap.parse_args(argv)
    setup_logging(args.verbose)
    ws = args.workspace or ("demo" if args.cmd in ("demo", "synth") else None)
    cfg = load_config(args.config, ws)
    synthetic = cfg["workspace"].rstrip("/").endswith("demo")

    if args.cmd in ("demo", "synth"):
        from .synthetic import generate
        info = generate(cfg["_paths"])
        LOG.info("synthetic world: %s", {k: v for k, v in info.items() if k != "brand_map"})
        from .utils import write_json
        write_json(info, cfg["_paths"]["manual"] / "synthetic_info.json")
        if args.cmd == "synth":
            return 0
        _demo_cfg(cfg, info)
        return run_steps(cfg, ["build", "analyze", "figures", "explorer", "paper"], synthetic=True)
    if synthetic:
        from .utils import read_json
        _demo_cfg(cfg, read_json(cfg["_paths"]["manual"] / "synthetic_info.json", {}))
    if args.cmd == "collect":
        from . import collect
        tickers = args.tickers.split(",") if args.tickers else None
        {"gleif": lambda: collect.gleif(cfg, limit=args.limit),
         "set-universe": lambda: collect.set_universe(cfg),
         "set-shareholders": lambda: collect.set_shareholders(cfg, tickers, args.lang, args.limit),
         "documents": lambda: collect.documents(cfg, args.limit)}[args.what]()
        return 0
    if args.cmd == "extract":
        from . import extract
        if args.action == "pages":
            extract.find_pages(cfg, args.kind)
        elif args.action == "run":
            extract.run(cfg, args.kind, batch=args.batch, limit=args.limit, dry_run=args.dry_run)
        else:
            extract.collect_batch(cfg, args.kind)
        return 0
    if args.cmd == "all":
        return run_steps(cfg, ["build", "analyze", "figures", "explorer", "paper"], synthetic)
    return run_steps(cfg, [args.cmd], synthetic)


def run_steps(cfg, steps, synthetic=False) -> int:
    for s in steps:
        LOG.info("==== %s ====", s)
        if s == "build":
            from .build import build
            build(cfg)
        elif s == "analyze":
            from .analyze import run
            run(cfg)
        elif s == "figures":
            from .viz import all_figures
            all_figures(cfg, synthetic)
        elif s == "explorer":
            from .explorer import export
            export(cfg, synthetic)
        elif s == "paper":
            from .paper import build_paper
            build_paper(cfg, synthetic)
        elif s == "web":
            from .paper_web import build_web
            P = cfg["_paths"]
            pdf = P["paper"] / "paper.pdf"
            if not pdf.exists() and synthetic:
                pdf = P["root"] / "docs" / "paper_demo.pdf"
            build_web(P["paper"], P["root"] / "docs" / "paper", pdf=pdf, synthetic=synthetic,
                      template=P["paper_src"] / "reader.html")
        elif s == "init":
            from .status import init_workspace
            init_workspace(cfg)
        elif s == "status":
            from .status import report
            report(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
