"""Shared visual vocabulary and the galaxy layout.

Groups are packed as circles (area proportional to the number of firms). Inside each circle the
group's control tree is drawn radially: ultimate owner at the centre, one ring per ownership link.
"""
from __future__ import annotations

import math
import zlib
from collections import deque

import circlify
import numpy as np
import pandas as pd

from .groups import SET_INDUSTRY_OF_SECTOR
from .utils import read_json

IND = ["AGRO", "CONSUMP", "FINCIAL", "INDUS", "PROPCON", "RESOURC", "SERVICE", "TECH", "OTHER"]
IND_LABEL = {"AGRO": "Agro & food", "CONSUMP": "Consumer products", "FINCIAL": "Financials",
             "INDUS": "Industrials", "PROPCON": "Property & construction", "RESOURC": "Resources & energy",
             "SERVICE": "Services", "TECH": "Technology", "OTHER": "Not classified"}
GT_LABEL = {"family": "Family", "state": "State", "crown": "Crown property", "foreign": "Foreign parent",
            "widely_held_corporation": "Widely held (corporate)", "widely_held_financial": "Widely held (financial)",
            "private_unresolved": "Unresolved private holding", "listed_no_data": "No shareholder data",
            "state_investor": "State investor", "widely_held": "Widely held", "unknown": "Other"}
GT_ORDER = ["family", "state", "crown", "foreign", "widely_held_corporation", "widely_held_financial",
            "private_unresolved", "listed_no_data"]

THEMES = {
    "dark": dict(
        bg="#0D1224", bg2="#1C2450", fg="#ECEFF8", muted="#929BC0",
        ind={"AGRO": "#9BD15D", "CONSUMP": "#F7A95B", "FINCIAL": "#F5D547", "INDUS": "#5D9BFF",
             "PROPCON": "#C58BFF", "RESOURC": "#FF6B6B", "SERVICE": "#3ED1C8", "TECH": "#FF7EC8", "OTHER": "#8A93AD"},
        gt={"family": "#FFD27A", "state": "#FF8A5B", "crown": "#C9A7FF", "foreign": "#62D2FF",
            "widely_held_corporation": "#9FE0C9", "widely_held_financial": "#B6E36A", "private_unresolved": "#A3ABC8",
            "listed_no_data": "#6F7894", "state_investor": "#FFB3A1", "widely_held": "#9FE0C9", "unknown": "#A3ABC8"},
        tie_dir="#8EA2FF", tie_own="#FFC27A", edge_alpha=0.34, node_alpha=0.92),
    "light": dict(
        bg="#FFFFFF", bg2="#F3F5FA", fg="#1B2133", muted="#5E6780",
        ind={"AGRO": "#4E9A2A", "CONSUMP": "#E07B1F", "FINCIAL": "#C99A06", "INDUS": "#2563D9",
             "PROPCON": "#8B4FD1", "RESOURC": "#D63F3F", "SERVICE": "#139C93", "TECH": "#D43F8D", "OTHER": "#98A1B5"},
        gt={"family": "#C98A00", "state": "#D9532B", "crown": "#7E57C2", "foreign": "#1C8FD1",
            "widely_held_corporation": "#2E9E7E", "widely_held_financial": "#5C9E1F", "private_unresolved": "#8C94A8",
            "listed_no_data": "#B0B6C4", "state_investor": "#E58F7A", "widely_held": "#2E9E7E", "unknown": "#8C94A8"},
        tie_dir="#5A6FD6", tie_own="#E08A1E", edge_alpha=0.45, node_alpha=0.95),
}


def load(cfg) -> dict:
    R = cfg["_paths"]["results"]

    def rd(name):
        p = R / name
        if not p.exists():
            return pd.DataFrame()
        return pd.read_csv(p, encoding="utf-8-sig", keep_default_na=False, na_values=[""], low_memory=False)

    D = {k: rd(f) for k, f in [("E", "entities_agg.csv"), ("H", "holdings_agg.csv"), ("M", "group_members.csv"),
                                ("G", "groups.csv"), ("T", "group_ties.csv"), ("U", "ultimate_owners.csv"),
                                ("N", "fi_nexus.csv"), ("RB", "robustness.csv")]}
    E = D["E"]
    if len(E):
        for c in ("sector", "industry", "fi_type", "country", "name", "etype"):
            E[c] = E[c].fillna("").astype(str) if c in E else ""
        E["market_cap"] = pd.to_numeric(E["market_cap"], errors="coerce") if "market_cap" in E else np.nan
    D["S"] = read_json(R / "summary.json", {})
    return D


def industry_of(E: pd.DataFrame) -> dict:
    out = {}
    for i, ind, sec, fi in zip(E["id"], E["industry"], E["sector"], E["fi_type"]):
        a, b = ind.upper(), sec.upper()
        if a in IND:
            v = a
        elif b in IND:
            v = b
        else:
            v = SET_INDUSTRY_OF_SECTOR.get(b) or SET_INDUSTRY_OF_SECTOR.get(a) or ("FINCIAL" if fi else "OTHER")
        out[i] = v
    return out


def _angles(root, children) -> dict:
    order, stack = [], [root]
    while stack:
        u = stack.pop()
        order.append(u)
        stack.extend(children.get(u, ()))
    leaves = {}
    for u in reversed(order):
        ch = children.get(u)
        leaves[u] = sum(leaves[c] for c in ch) if ch else 1
    span, ang = {root: (0.0, 2 * math.pi)}, {root: 0.0}
    for u in order:
        a0, a1 = span[u]
        ch = sorted(children.get(u, ()), key=lambda c: (-leaves[c], str(c)))
        tot = sum(leaves[c] for c in ch) or 1
        cur = a0
        for c in ch:
            w = (a1 - a0) * leaves[c] / tot
            span[c], ang[c] = (cur, cur + w), cur + w / 2
            cur += w
    return ang


def compute_layout(D: dict, cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    E, H, M, G = D["E"], D["H"], D["M"], D["G"]
    Gs = G[G["n_firms"] >= cfg["viz"]["min_group_size"]].sort_values(["n_firms", "group_id"], ascending=[False, True])
    if Gs.empty:
        Gs = G.sort_values("n_firms", ascending=False)
    Gs = Gs.head(3000)
    circles = circlify.circlify([{"id": g, "datum": float(max(n, 1))} for g, n in zip(Gs["group_id"], Gs["n_firms"])],
                                show_enclosure=False)
    pos_g = {c.ex["id"]: (c.x, c.y, c.r) for c in circles}
    ind = industry_of(E)
    etype, names = dict(zip(E["id"], E["etype"])), dict(zip(E["id"], E["name"]))
    mcap, country = dict(zip(E["id"], E["market_cap"])), dict(zip(E["id"], E["country"]))
    role = dict(zip(M["entity"], M["role"]))
    adj = {}
    for o, d in H.sort_values("pct", ascending=False)[["owner", "owned"]].itertuples(index=False):
        adj.setdefault(o, []).append(d)
    pct = {(o, d): p for o, d, p in H[["owner", "owned", "pct"]].itertuples(index=False)}
    mem = M[M["group_id"].isin(pos_g)].groupby("group_id")["entity"].apply(list).to_dict()
    rows = []
    for g, (x0, y0, R) in pos_g.items():
        S = set(mem.get(g, [])) | {g}
        parent, depth, q = {g: None}, {g: 0}, deque([g])
        while q:  # breadth-first: each firm hangs under its largest in-group owner on a shortest chain
            u = q.popleft()
            for v in adj.get(u, ()):
                if v in S and v not in parent:
                    parent[v], depth[v] = u, depth[u] + 1
                    q.append(v)
        for v in S:
            if v not in parent:
                parent[v], depth[v] = g, 1
        children = {}
        for v, p in parent.items():
            if p is not None:
                children.setdefault(p, []).append(v)
        ang = _angles(g, children)
        maxd = max(depth.values()) or 1
        rot = (zlib.crc32(str(g).encode()) % 3600) / 3600 * 2 * math.pi
        rad = {v: 0.0 if depth[v] == 0 else R * 0.9 * (depth[v] / maxd) ** 0.8 for v in S}
        for v in S:
            a, p = ang[v] + rot, parent[v]
            x, y = x0 + rad[v] * math.cos(a), y0 + rad[v] * math.sin(a)
            cx, cy = (x, y) if p is None else (x0 + rad[p] * math.cos(a), y0 + rad[p] * math.sin(a))
            rows.append(dict(id=v, group_id=g, x=x, y=y, cx=cx, cy=cy, depth=depth[v], parent=p or "",
                             role="apex" if v == g else role.get(v, "subsidiary"), etype=etype.get(v, ""),
                             industry=ind.get(v, "OTHER"), name=names.get(v, v), mcap=mcap.get(v),
                             ticker=v[2:] if str(v).startswith("L:") else "", country=country.get(v, ""),
                             pct=pct.get((p, v)) if p else None))
    N = pd.DataFrame(rows)
    Gl = Gs.copy()
    Gl["x"], Gl["y"], Gl["r"] = (Gl["group_id"].map(lambda g, i=i: pos_g[g][i]) for i in range(3))
    return N, Gl


def node_category(N: pd.DataFrame) -> np.ndarray:
    role, et = N["role"].astype(str).to_numpy(), N["etype"].astype(str).to_numpy()
    ctry = N["country"].fillna("TH").astype(str).replace({"": "TH", "nan": "TH"}).to_numpy()
    cat = np.full(len(N), "private", dtype=object)
    cat[(et == "foreign") | (ctry != "TH")] = "foreign"
    cat[role == "holding"] = "holding"
    cat[(role == "listed") | (et == "listed")] = "listed"
    cat[role == "apex"] = "apex"
    return cat


def node_weights(N: pd.DataFrame, Gl: pd.DataFrame) -> np.ndarray:
    """Relative marker area per node (unit-free; listed firms scale with market value)."""
    cat = node_category(N)
    mc = pd.to_numeric(N["mcap"], errors="coerce")
    lst = mc[cat == "listed"].dropna()
    med = float(lst.median()) if len(lst) and lst.median() > 0 else 1.0
    w = np.ones(len(N))
    w[cat == "foreign"] = 1.2
    w[cat == "holding"] = 2.6
    w = np.where(cat == "listed", 6.0 * np.clip(np.sqrt((mc / med).fillna(1.0).to_numpy()), 0.6, 4.5), w)
    nf = N["group_id"].map(dict(zip(Gl["group_id"], Gl["n_firms"]))).fillna(1).to_numpy(dtype=float)
    return np.where(cat == "apex", 14.0 + 3.5 * np.sqrt(nf), w)


def text_overlaps(fig, pad=0.5) -> list[tuple[str, str]]:
    """Pairs of drawn text elements whose rendered boxes intersect (publication QA).

    Records exactly the texts that are drawn (tick labels, titles, legends, annotations, badges), so
    pooled or clipped matplotlib text objects cannot cause false alarms."""
    from matplotlib.text import Text
    drawn, orig = [], Text.draw

    def rec(self, renderer):
        orig(self, renderer)
        if self.get_visible() and self.get_text().strip():
            try:
                patch = self.get_bbox_patch()
                bb = patch.get_window_extent(renderer) if patch is not None else self.get_window_extent(renderer)
                drawn.append((self.get_text().replace("\n", " ")[:28], bb))
            except Exception:  # noqa: BLE001
                pass

    Text.draw = rec
    try:
        fig.canvas.draw()
    finally:
        Text.draw = orig
    bad = []
    for i in range(len(drawn)):
        for j in range(i + 1, len(drawn)):
            a, b = drawn[i][1], drawn[j][1]
            if a.x0 + pad < b.x1 and b.x0 + pad < a.x1 and a.y0 + pad < b.y1 and b.y0 + pad < a.y1:
                bad.append((drawn[i][0], drawn[j][0]))
    return bad
