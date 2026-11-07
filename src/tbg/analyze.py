"""Run the full analysis on processed tables and write results/ for figures and the paper."""
from __future__ import annotations

import math

import networkx as nx
import numpy as np
import pandas as pd

from . import fi as fimod
from . import groups as grp
from .ownership import compute, dbd_priority_queue
from .utils import LOG, write_csv, write_json

UO_ORDER = ["family", "state", "crown", "foreign", "widely_held_corporation", "widely_held_financial",
            "private_unresolved", "listed_no_data", "state_investor", "widely_held"]


def _read(P, name):
    return pd.read_csv(P["processed"] / name, encoding="utf-8-sig", keep_default_na=False,
                       na_values=[""], low_memory=False)


def load_processed(cfg):
    P = cfg["_paths"]
    E = _read(P, "entities.csv")
    H = _read(P, "holdings.csv")
    H["pct"] = pd.to_numeric(H["pct"], errors="coerce")
    S = _read(P, "board_seats.csv")
    L = _read(P, "parent_links.csv")
    PF = _read(P, "person_family.csv").fillna("")
    for c in ("fi_type", "sector", "country", "ticker"):
        if c in E:
            E[c] = E[c].fillna("")
    return E, H, S, L, PF


def uo_distribution(uo: pd.DataFrame, E: pd.DataFrame, t: float) -> pd.DataFrame:
    u = uo[(uo["threshold"] == t) & uo["firm"].str.startswith("L:")]
    mcap = pd.to_numeric(E.set_index("id")["market_cap"], errors="coerce")
    u = u.assign(mcap=u["firm"].map(mcap).fillna(0))
    tot_n, tot_m = len(u), u["mcap"].sum()
    d = u.groupby("uo_type").agg(n=("firm", "size"), mcap=("mcap", "sum")).reindex(UO_ORDER).dropna(how="all")
    d["share_n"] = d["n"] / max(tot_n, 1)
    d["share_mcap"] = d["mcap"] / tot_m if tot_m else np.nan
    return d.reset_index().rename(columns={"index": "uo_type"})


def run(cfg: dict) -> dict:
    P = cfg["_paths"]
    oc = cfg["ownership"]
    t = oc["group_threshold"]
    E, H, S, L, PF = load_processed(cfg)
    base = compute(E, H, cfg, PF)
    uo, Eagg, Hagg = base["uo"], base["entities_agg"], base["holdings_agg"]
    seeds = grp.load_seeds(P["seeds"])
    G = grp.assign(Eagg, uo, Hagg, S, seeds, t, oc["link_min_pct"], oc.get("split_groups_under", ["state", "crown"]))
    members, groups = G["members"], G["groups"]
    nex, nsum = fimod.nexus(Eagg, Hagg, S, members, groups, cfg["fi"]["amc_brand_map"], oc["link_min_pct"])

    R = P["results"]
    write_csv(uo, R / "ultimate_owners.csv")
    write_csv(base["pairs"], R / "control_pairs.csv")
    write_csv(base["cycles"], R / "cycles.csv")
    write_csv(members, R / "group_members.csv")
    write_csv(groups, R / "groups.csv")
    write_csv(G["ties"], R / "group_ties.csv")
    write_csv(nex, R / "fi_nexus.csv")
    write_csv(G["seed_report"], P["review"] / "seed_check.csv")
    write_csv(dbd_priority_queue(uo, Eagg, t), P["review"] / "dbd_priority_queue.csv")
    write_csv(Eagg, R / "entities_agg.csv")
    write_csv(Hagg, R / "holdings_agg.csv")

    # robustness -------------------------------------------------------------
    rob = []
    for th in oc["thresholds"]:
        d = uo_distribution(uo, Eagg, th)
        rob += [dict(spec=f"threshold {int(th * 100)}%", uo_type=r.uo_type, share=r.share_n) for r in d.itertuples()]
    for label, kw in [("no family aggregation", {"family_mode": "none"})]:
        alt = compute(E, H, cfg, PF, **kw)["uo"]
        d = uo_distribution(alt, E, t)
        rob += [dict(spec=label, uo_type=r.uo_type, share=r.share_n) for r in d.itertuples()]
    cfg2 = {**cfg, "ownership": {**oc, "non_candidate_types": [x for x in oc["non_candidate_types"]
                                                               if x != "institutional"]}}
    alt = compute(E, H, cfg2, PF)["uo"]
    d = uo_distribution(alt, E, t)
    rob += [dict(spec="state investors as owners", uo_type=r.uo_type, share=r.share_n) for r in d.itertuples()]
    robust = pd.DataFrame(rob)
    write_csv(robust, R / "robustness.csv")

    summary = summarize(cfg, E, H, S, L, uo, Eagg, Hagg, members, groups, base["cycles"], nsum)
    write_json(summary, R / "summary.json")

    # validation sample for manual checking -------------------------------
    u = uo[(uo["threshold"] == t) & uo["firm"].str.startswith("L:")]
    if len(u):
        samp = u.sample(min(100, len(u)), random_state=1)[["firm", "uo_id", "uo_type", "cr", "cf", "depth"]]
        samp = samp.assign(firm_name=samp["firm"].map(Eagg.set_index("id")["name"]),
                           uo_name=samp["uo_id"].map(Eagg.set_index("id")["name"]),
                           uo_id_checked="", is_correct="", note="")
        out = P["review"] / "validation_sample.csv"
        if not out.exists():
            write_csv(samp, out)
    LOG.info("analysis done: %d groups, %d listed firms with UO data", len(groups), len(u))
    return {"summary": summary, "groups": groups, "members": members, "uo": uo, "nexus": nex,
            "entities": Eagg, "holdings": Hagg, "seats": S, "ties": G["ties"], "robust": robust}


def summarize(cfg, E, H, S, L, uo, Eagg, Hagg, members, groups, cycles, nsum) -> dict:
    t = cfg["ownership"]["group_threshold"]
    et = E["etype"].value_counts()
    listed = E[E["etype"] == "listed"]["id"]
    u = uo[(uo["threshold"] == t) & uo["firm"].str.startswith("L:")]
    with_top = set(H.loc[H["source"] == "set_top10", "owned"])
    reporters = set(H["reporter"].dropna()) if "reporter" in H else set()
    gsize = groups.set_index("group_id")
    listed_g = u.assign(g=u["uo_id"].fillna(u["firm"]))
    multi_listed = set(gsize.index[gsize["n_listed"] >= 2])
    aff = listed_g["g"].isin(multi_listed)
    mcap = pd.to_numeric(E.set_index("id")["market_cap"], errors="coerce").fillna(0)
    tot_mcap = float(mcap.reindex(listed).sum())
    gm = groups.sort_values("mcap", ascending=False)
    shares = (gm["mcap"] / tot_mcap) if tot_mcap else gm["mcap"] * 0
    ctrl = u[u["uo_id"].notna()]
    dist20 = uo_distribution(uo, Eagg, t).set_index("uo_type")
    dist10 = uo_distribution(uo, Eagg, 0.10).set_index("uo_type")
    Gx = nx.DiGraph()
    Gx.add_edges_from(zip(H["owner"], H["owned"]))
    wcc = max((len(c) for c in nx.weakly_connected_components(Gx)), default=0)
    top = groups.iloc[0] if len(groups) else None
    multi = groups[groups["n_firms"] >= 2]
    apex_unres = multi["group_type"].eq("private_unresolved").mean() if len(multi) else math.nan

    def sh(d, k):
        return float(d["share_n"].get(k, 0.0)) if len(d) else 0.0

    s = {
        "n_entities": int(len(E)), "n_listed": int(et.get("listed", 0)), "n_companies": int(et.get("company", 0)),
        "n_foreign": int(et.get("foreign", 0)), "n_persons": int(et.get("person", 0)),
        "n_families": int((Eagg["etype"] == "family").sum()), "n_holdings": int(len(H)),
        "n_board_seats": int(len(S)), "n_directors": int(S["person"].nunique()) if len(S) else 0,
        "n_parent_links": int(len(L)),
        "n_listed_top10": int(len(with_top & set(listed))), "n_listed_subs": int(len(reporters & set(listed))),
        "n_groups_multi": int(len(multi)), "n_groups_10plus": int((groups["n_firms"] >= 10).sum()),
        "n_groups_multi_listed": int(len(multi_listed)),
        "share_listed_group_affiliated": float(aff.mean()) if len(aff) else math.nan,
        "share_uo_family_20": sh(dist20, "family"), "share_uo_state_20": sh(dist20, "state"),
        "share_uo_foreign_20": sh(dist20, "foreign"), "share_uo_crown_20": sh(dist20, "crown"),
        "share_uo_wh_20": sh(dist20, "widely_held") + sh(dist20, "widely_held_corporation")
        + sh(dist20, "widely_held_financial"),
        "share_uo_unresolved_20": sh(dist20, "private_unresolved") + sh(dist20, "listed_no_data"),
        "share_uo_family_10": sh(dist10, "family"), "share_uo_wh_10": sh(dist10, "widely_held"),
        "share_pyramid_listed": float(ctrl["pyramid"].mean()) if len(ctrl) else math.nan,
        "mean_wedge_listed": float(ctrl["wedge"].mean()) if len(ctrl) else math.nan,
        "median_wedge_listed": float(ctrl["wedge"].median()) if len(ctrl) else math.nan,
        "mean_ratio_cf_cr": float((ctrl["cf"] / ctrl["cr"]).replace([np.inf], np.nan).mean()) if len(ctrl) else math.nan,
        "max_depth": int(uo[uo["threshold"] == t]["depth"].max()) if uo["depth"].notna().any() else 0,
        "mean_depth_all": float(uo[uo["threshold"] == t]["depth"].mean()),
        "n_cycles": int(len(cycles)), "n_firms_in_cycles": int(cycles["size"].sum()) if len(cycles) else 0,
        "top10_groups_mcap_share": float(shares.head(10).sum()) if tot_mcap else math.nan,
        "hhi_groups_mcap": float((shares ** 2).sum() * 10000) if tot_mcap else math.nan,
        "largest_wcc_share": wcc / max(Gx.number_of_nodes(), 1),
        "apex_unresolved_share": float(apex_unres),
        "top_group_label": str(top["label"]) if top is not None else "",
        "top_group_firms": int(top["n_firms"]) if top is not None else 0,
        "top_group_industries": int(top["n_industries"]) if top is not None else 0,
        "max_industries": int(groups["n_industries"].max()) if len(groups) else 0,
        "threshold": t, "data_year": cfg["project"].get("data_year"), "as_of": cfg["project"].get("as_of"),
        **{k: v for k, v in nsum.items() if k != "bank_groups"},
    }
    # GLEIF agreement: GLEIF parent is an owner-ancestor or in the same group
    gid = dict(zip(members["entity"], members["group_id"]))
    gl = L[L["source"] == "gleif"]
    if len(gl):
        ok = 0
        for c, p in zip(gl["child"], gl["parent"]):
            ok += int((gid.get(c) is not None and gid.get(c) == gid.get(p)) or
                      (p in Gx and c in Gx and nx.has_path(Gx, p, c)))
        s["gleif_pairs"], s["gleif_agreement"] = int(len(gl)), ok / len(gl)
    else:
        s["gleif_pairs"], s["gleif_agreement"] = 0, math.nan
    return s
