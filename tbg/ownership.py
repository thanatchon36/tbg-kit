"""Ownership and control measures on the holding network.

For every candidate ultimate owner a and every firm c it reaches:
  cash-flow rights   CF(a,c) = sum_s w(s,c) * CF(a,s),            CF(a,a) = 1
  control rights     CR(a,c) = sum_s min(w(s,c), CR(a,s)),         CR(a,a) = 1
CF equals the (a,c) entry of M(I-M)^-1 (Brioschi et al. 1989). CR is the
weakest-link measure of Claessens et al. (2000), applied block by block so that a
block of votes is never counted twice. Cycles are solved by fixed-point iteration.

Ultimate owner (UO) at threshold t is found in two stages:
  1. terminal owners (families, persons, state, crown, foreign parents, private
     companies with no known shareholders); the largest CR >= t wins;
  2. firms left without a stage-1 UO are 'widely held'; their own subsidiaries are
     assigned to the controlling widely held firm (La Porta et al. 1999 categories).
"""
from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass

import networkx as nx
import pandas as pd

from .utils import LOG

FIRM_TYPES = {"listed", "company", "foreign"}


@dataclass
class Graph:
    preds: dict
    succ: dict


def make_graph(holdings: pd.DataFrame) -> Graph:
    preds, succ = defaultdict(list), defaultdict(list)
    for o, d, p in holdings[["owner", "owned", "pct"]].itertuples(index=False):
        if o == d or not (p > 0):
            continue
        w = min(float(p) / 100.0, 1.0)
        preds[d].append((o, w))
        succ[o].append(d)
    return Graph(dict(preds), dict(succ))


def propagate(g: Graph, a: str, max_iter: int = 500, tol: float = 1e-10) -> tuple[dict, dict]:
    """CF and CR of source a over all its descendants."""
    order, seen, q = [], {a}, deque([a])
    while q:
        x = q.popleft()
        for y in g.succ.get(x, ()):
            if y not in seen:
                seen.add(y)
                order.append(y)
                q.append(y)
    if not order:
        return {}, {}
    desc = set(order)
    indeg = {c: sum(1 for s, _ in g.preds.get(c, ()) if s in desc) for c in order}
    q = deque(c for c in order if indeg[c] == 0)
    topo = []
    while q:
        c = q.popleft()
        topo.append(c)
        for d in g.succ.get(c, ()):
            if d in desc:
                indeg[d] -= 1
                if indeg[d] == 0:
                    q.append(d)
    cf, cr = {a: 1.0}, {a: 1.0}

    def upd(c):
        scf = scr = 0.0
        for s, w in g.preds.get(c, ()):
            if s == a:
                scf += w
                scr += w
            else:
                v = cf.get(s)
                if v:
                    scf += w * v
                    scr += min(w, cr[s])
        return scf, (scr if scr < 1.0 else 1.0)

    for c in topo:
        cf[c], cr[c] = upd(c)
    topo_set = set(topo)
    rest = [c for c in order if c not in topo_set]
    if rest:  # nodes on or below a cycle: Gauss-Seidel fixed point
        for c in rest:
            cf[c], cr[c] = 0.0, 0.0
        for _ in range(max_iter):
            delta = 0.0
            for c in rest:
                n1, n2 = upd(c)
                delta = max(delta, abs(n1 - cf[c]), abs(n2 - cr[c]))
                cf[c], cr[c] = n1, n2
            if delta < tol:
                break
    del cf[a], cr[a]
    return cf, cr


def chain_depth(g: Graph, a: str, cr: dict, t: float, listed: set) -> tuple[dict, dict]:
    """Shortest control chain from a; intermediates must be controlled by a at >= t."""
    dist, via = {a: 0}, {a: False}
    q = deque([a])
    while q:
        s = q.popleft()
        if s != a and cr.get(s, 0.0) < t:
            continue
        for c in g.succ.get(s, ()):
            if c not in dist:
                dist[c] = dist[s] + 1
                via[c] = via[s] or (s != a and s in listed)
                q.append(c)
    return dist, via


def aggregate_families(entities: pd.DataFrame, holdings: pd.DataFrame, person_family: pd.DataFrame,
                       mode: str = "surname") -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Collapse persons into family nodes (Thai surnames are largely unique by law)."""
    if mode == "none" or person_family is None or person_family.empty:
        return entities, holdings, {}
    pf = person_family.copy()
    if mode == "manual":
        pf = pf[pf["method"] == "manual"]
    pf = pf[pf["family_id"].astype(str).str.len() > 2]
    pmap = dict(zip(pf["person"], pf["family_id"]))
    if not pmap:
        return entities, holdings, {}
    H = holdings.copy()
    H["owner"] = H["owner"].map(lambda x: pmap.get(x, x))
    agg = {"pct": "sum", "source": "first", "as_of": "first", "basis": "first", "relationship": "first"}
    H = H.groupby(["owner", "owned"], as_index=False).agg({k: v for k, v in agg.items() if k in H.columns})
    fam_ids = sorted(set(pmap.values()))
    fam_rows = pd.DataFrame({"id": fam_ids, "etype": "family",
                             "name": ["Family " + f.split(":", 1)[1].title() for f in fam_ids],
                             "country": "TH"})
    E = pd.concat([entities, fam_rows], ignore_index=True)
    return E, H, pmap


def compute(entities: pd.DataFrame, holdings: pd.DataFrame, cfg: dict,
            person_family: pd.DataFrame | None = None, family_mode: str | None = None) -> dict:
    oc = cfg["ownership"]
    mode = family_mode or oc["family_aggregation"]
    E, H, pmap = aggregate_families(entities, holdings, person_family, mode)
    g = make_graph(H)
    etype = dict(zip(E["id"], E["etype"]))
    fi = dict(zip(E["id"], E.get("fi_type", pd.Series([""] * len(E))).fillna("")))
    listed = {e for e, t in etype.items() if t == "listed"}
    non_cand = set(oc["non_candidate_types"])
    owned, owners = set(g.preds), set(g.succ)
    cands = [e for e in owners if e not in owned and etype.get(e, "unknown") not in non_cand]
    LOG.info("ownership graph: %d edges, %d owners, %d owned, %d terminal candidates",
             len(H), len(owners), len(owned), len(cands))

    best, pairs, cache = {}, [], {}
    for a in cands:
        cf, cr = propagate(g, a, oc["max_iter"], oc["tol"])
        hit = False
        for c, r in cr.items():
            if r >= oc["min_store_cr"]:
                f = cf[c]
                pairs.append((a, c, f, r, 1))
                b = best.get(c)
                if b is None or r > b[0] + 1e-12 or (abs(r - b[0]) <= 1e-12 and f > b[1]):
                    best[c] = (r, f, a)
                hit = True
        if hit:
            cache[a] = (cf, cr)

    firms = [c for c in owned if etype.get(c) in FIRM_TYPES]
    rows, depth_cache = [], {}
    for t in oc["thresholds"]:
        uo1 = {c: (best[c][2], best[c][0], best[c][1]) for c in firms if c in best and best[c][0] >= t}
        wh_src = [w for w in firms if w not in uo1 and w in owners]
        best2 = {}
        for w in wh_src:
            if w not in cache:
                cache[w] = propagate(g, w, oc["max_iter"], oc["tol"])
            cf, cr = cache[w]
            for c, r in cr.items():
                if c in uo1 or c == w or etype.get(c) not in FIRM_TYPES or r < t:
                    continue
                b = best2.get(c)
                if b is None or r > b[1] or (r == b[1] and cf[c] > b[2]):
                    best2[c] = (w, r, cf[c])

        def apex(c):
            x, seen = c, set()
            while x in best2 and x not in seen:
                seen.add(x)
                x = best2[x][0]
            return x

        for c in firms:
            if c in uo1:
                uo, r, f = uo1[c]
                stage = 1
            elif c in best2:
                uo, stage = apex(c), 2
                cfx, crx = cache[uo]
                r, f = crx.get(c, math.nan), cfx.get(c, math.nan)
            else:
                uo, stage, r, f = None, 0, math.nan, math.nan
            depth = via = None
            if uo is not None:
                key = (uo, t)
                if key not in depth_cache:
                    depth_cache[key] = chain_depth(g, uo, cache[uo][1], t, listed)
                d, v = depth_cache[key]
                depth, via = d.get(c), v.get(c, False)
            rows.append(dict(firm=c, threshold=t, uo_id=uo, stage=stage, cr=r, cf=f,
                             wedge=(r - f) if uo is not None else math.nan,
                             depth=depth, pyramid=bool(depth is not None and depth >= 2),
                             pyramid_listed=bool(via), uo_type=uo_type(uo, stage, etype, fi)))
    for t in oc["thresholds"]:  # listed firms with no shareholder data at all
        for c in sorted(listed - owned):
            rows.append(dict(firm=c, threshold=t, uo_id=None, stage=0, cr=math.nan, cf=math.nan, wedge=math.nan,
                             depth=None, pyramid=False, pyramid_listed=False, uo_type="listed_no_data"))
    uo_df = pd.DataFrame(rows)
    pairs_df = pd.DataFrame(pairs, columns=["owner", "firm", "cf", "cr", "stage"])
    G = nx.DiGraph()
    G.add_edges_from(zip(H["owner"], H["owned"]))
    cyc = [sorted(c) for c in nx.strongly_connected_components(G) if len(c) > 1]
    cycles = pd.DataFrame([{"cycle_id": i, "size": len(c), "members": ";".join(c)} for i, c in enumerate(cyc)],
                          columns=["cycle_id", "size", "members"])
    return {"uo": uo_df, "pairs": pairs_df, "cycles": cycles, "entities_agg": E, "holdings_agg": H,
            "person_to_family": pmap}


def uo_type(uo, stage: int, etype: dict, fi: dict) -> str:
    if uo is None:
        return "widely_held"
    t = etype.get(uo, "unknown")
    if stage == 2:
        return "widely_held_financial" if fi.get(uo) else "widely_held_corporation"
    return {"family": "family", "person": "family", "state": "state", "crown": "crown",
            "foreign": "foreign", "company": "private_unresolved", "listed": "listed_no_data",
            "institutional": "state_investor"}.get(t, t)


def dbd_priority_queue(uo_df: pd.DataFrame, entities: pd.DataFrame, t: float) -> pd.DataFrame:
    """Private holding companies without shareholder data, ranked by what they control."""
    u = uo_df[(uo_df["threshold"] == t) & (uo_df["uo_type"] == "private_unresolved")]
    if u.empty:
        return pd.DataFrame(columns=["entity", "name", "n_firms", "n_listed", "mcap_controlled"])
    E = entities.set_index("id")
    mcap = pd.to_numeric(E.get("market_cap"), errors="coerce")
    g = u.groupby("uo_id")
    out = pd.DataFrame({
        "n_firms": g.size(),
        "n_listed": g["firm"].apply(lambda s: sum(x.startswith("L:") for x in s)),
        "mcap_controlled": g["firm"].apply(lambda s: float(mcap.reindex(list(s)).fillna(0).sum())),
    }).reset_index().rename(columns={"uo_id": "entity"})
    out["name"] = out["entity"].map(E["name"])
    return out.sort_values(["n_listed", "mcap_controlled", "n_firms"], ascending=False)[
        ["entity", "name", "n_firms", "n_listed", "mcap_controlled"]]
