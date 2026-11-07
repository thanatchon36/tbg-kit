"""Interactive explorer: one self-contained HTML file (no internet needed) built from the galaxy layout."""
from __future__ import annotations

import html
import json
import math

import pandas as pd

from .names import short_company_name
from .utils import LOG, ensure_dir
from .viz_layout import GT_LABEL, GT_ORDER, IND, IND_LABEL, THEMES, compute_layout, load, node_category, node_weights

ROLE_CODE = {"apex": 0, "listed": 1, "holding": 2, "private": 3, "foreign": 4}


def _num(v, nd=5):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else round(v, nd)


def export(cfg, synthetic=False):
    P = cfg["_paths"]
    D = load(cfg)
    if D["G"].empty:
        LOG.error("no results yet: run `python -m tbg analyze` first")
        return None
    ln, lg = P["results"] / "layout_nodes.csv", P["results"] / "layout_groups.csv"
    if ln.exists() and lg.exists():
        rd = lambda p: pd.read_csv(p, encoding="utf-8-sig", keep_default_na=False, na_values=[""], low_memory=False)  # noqa: E731
        N, Gl = rd(ln), rd(lg)
    else:
        N, Gl = compute_layout(D, cfg)
    gi = {g: i for i, g in enumerate(Gl["group_id"])}
    t = cfg["ownership"]["group_threshold"]
    U = D["U"]
    U = U[U["threshold"] == t].set_index("firm") if len(U) else pd.DataFrame(columns=["cr", "cf", "depth"])
    cat, w = node_category(N), node_weights(N, Gl)
    ids = N["id"].astype(str).tolist()
    nodes = {
        "id": ids,
        "name": [short_company_name(s, 70) for s in N["name"].fillna("").astype(str)],
        "x": [_num(v) for v in N["x"]], "y": [_num(v) for v in N["y"]],
        "cx": [_num(v) for v in N["cx"]], "cy": [_num(v) for v in N["cy"]],
        "g": [gi[g] for g in N["group_id"]],
        "ind": [IND.index(i) if i in IND else IND.index("OTHER") for i in N["industry"]],
        "role": [ROLE_CODE[c] for c in cat],
        "parent": N["parent"].fillna("").astype(str).tolist(),
        "ticker": N["ticker"].fillna("").astype(str).tolist(),
        "rad": [round(0.0011 * math.sqrt(x), 6) for x in w],
        "cr": [_num(U["cr"].get(i), 4) if i in U.index else None for i in ids],
        "cf": [_num(U["cf"].get(i), 4) if i in U.index else None for i in ids],
        "depth": [(int(d) if d is not None else None) for d in (_num(U["depth"].get(i), 0) if i in U.index else None for i in ids)],
        "pin": [_num(v, 2) for v in N["pct"]],
    }
    groups = {"label": Gl["label"].astype(str).tolist(), "x": [_num(v) for v in Gl["x"]], "y": [_num(v) for v in Gl["y"]],
              "r": [_num(v) for v in Gl["r"]], "gtype": Gl["group_type"].astype(str).tolist(),
              "n_firms": [int(v) for v in Gl["n_firms"]], "n_listed": [int(v) for v in Gl["n_listed"]],
              "rank": [int(v) for v in Gl["rank"]]}
    ties = []
    T = D["T"]
    if len(T):
        tt = T[T["g1"].isin(gi) & T["g2"].isin(gi)].sort_values("weight", ascending=False).head(400)
        wmax = float(tt["weight"].max() or 1) if len(tt) else 1.0
        ties = [[gi[a], gi[b], int(o), round((float(wt) / wmax) ** 0.5, 3)]
                for a, b, o, wt in tt[["g1", "g2", "ownership", "weight"]].itertuples(index=False)]
    x0, x1 = float((Gl["x"] - Gl["r"]).min()), float((Gl["x"] + Gl["r"]).max())
    y0, y1 = float((Gl["y"] - Gl["r"]).min()), float((Gl["y"] + Gl["r"]).max())
    title = cfg["project"].get("short_title") or "Thai business groups"
    foot = (f"Ownership as of {cfg['project'].get('as_of') or 'n/a'}; control threshold {round(t * 100)}%. "
            "Scroll to zoom, drag to move, click a firm to see its chain of control.")
    if synthetic:
        foot = "Synthetic demonstration data: every company and person is fictional. " + foot
    data = {
        "meta": {"title": title, "synthetic": bool(synthetic), "footer": foot, "cx": (x0 + x1) / 2, "cy": (y0 + y1) / 2,
                 "extent": max(x1 - x0, y1 - y0) / 2,
                 "subtitle": "Each circle is a business group: its ultimate owner in the centre, controlled firms on "
                             "rings by ownership distance. Click any firm to trace its chain of control."},
        "industries": [[c, IND_LABEL[c], THEMES["dark"]["ind"][c], THEMES["light"]["ind"][c]] for c in IND],
        "gtypes": {k: [GT_LABEL[k], THEMES["dark"]["gt"].get(k, "#A3ABC8"), THEMES["light"]["gt"].get(k, "#8C94A8")]
                   for k in GT_LABEL},
        "gtype_order": [g for g in GT_ORDER if g in set(Gl["group_type"])],
        "nodes": nodes, "groups": groups, "ties": ties,
    }
    tpl = (P["templates"] / "explorer.html").read_text(encoding="utf-8")
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    out = ensure_dir(P["explorer"]) / "index.html"
    out.write_text(tpl.replace("__TBG_DATA__", blob).replace("__TITLE__", html.escape(title)), encoding="utf-8")
    LOG.info("explorer: %s (%.1f MB, %d nodes)", out, out.stat().st_size / 1e6, len(ids))
    return out
