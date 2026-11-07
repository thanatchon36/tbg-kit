"""`init`: create the workspace and blank input templates.  `status`: coverage and review report."""
from __future__ import annotations

import pandas as pd

from .utils import SCHEMAS, ensure_dir, read_json, write_csv

TEMPLATES = {
    ("raw", "universe/listed_companies.csv"): "universe",
    ("raw", "shareholders/top10_manual.csv"): "top10",
    ("raw", "subsidiaries/manual.csv"): "subsidiaries",
    ("raw", "dbd/boj5_manual.csv"): "boj5",
    ("raw", "fi/fi_licenses.csv"): "fi_licenses",
    ("raw", "fi/pillar3_manual.csv"): "pillar3",
    ("raw", "directors/directors_manual.csv"): "directors",
    ("manual", "entity_overrides.csv"): "overrides",
    ("manual", "family_map.csv"): "family_map",
    ("manual", "document_urls.csv"): "document_urls",
}
DOC_DIRS = ["one_report", "pillar3", "boj5"]


def init_workspace(cfg) -> None:
    P = cfg["_paths"]
    for k in ("raw", "manual", "interim", "processed", "review", "results", "figures", "paper", "explorer"):
        ensure_dir(P[k])
    for d in DOC_DIRS:
        ensure_dir(P["raw"] / "documents" / d)
    ensure_dir(P["raw"] / "gleif")
    made = []
    for (base, rel), kind in TEMPLATES.items():
        p = P[base] / rel
        if not p.exists():
            write_csv(pd.DataFrame(columns=SCHEMAS[kind]), p)
            made.append(str(p.relative_to(P["ws"])))
    print(f"workspace: {P['ws']}")
    print("created templates:" if made else "templates already exist", *made, sep="\n  ")


def _rows(p) -> int:
    try:
        with open(p, encoding="utf-8-sig") as fh:
            return max(sum(1 for _ in fh) - 1, 0)
    except OSError:
        return 0


def report(cfg) -> None:
    P = cfg["_paths"]
    print(f"\n== workspace {P['ws']}\n-- raw inputs (rows)")
    for p in sorted(P["raw"].rglob("*.csv")):
        print(f"  {p.relative_to(P['raw'])}: {_rows(p):,}")
    print("-- documents")
    for d in DOC_DIRS:
        print(f"  {d}: {len(list((P['raw'] / 'documents' / d).glob('*.pdf')))} PDFs")
    llm = P["interim"] / "llm"
    if llm.exists():
        for k in sorted(x for x in llm.iterdir() if x.is_dir()):
            done = [f for f in k.glob("*.json") if not f.name.startswith("batch_")]
            print(f"  extracted ({k.name}): {len(done)} responses, {len(list(k.glob('batch_*.json')))} batches")
    S = read_json(P["results"] / "summary.json", {})
    if S:
        print("-- coverage")
        for k in ("n_listed", "n_listed_top10", "n_listed_subs", "n_entities", "n_holdings", "n_groups_multi",
                  "share_uo_unresolved_20", "gleif_agreement"):
            v = S.get(k)
            print(f"  {k}: {v:.3f}" if isinstance(v, float) else f"  {k}: {v}")
    print("-- review queues (rows)")
    for p in sorted(P["review"].glob("*.csv")):
        print(f"  {p.name}: {_rows(p):,}")
    q = P["review"] / "dbd_priority_queue.csv"
    if q.exists() and _rows(q):
        print("-- next BOJ.5 requests (private holding companies controlling the most)")
        print(pd.read_csv(q, encoding="utf-8-sig").head(10).to_string(index=False))
