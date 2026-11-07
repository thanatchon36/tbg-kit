"""Business-group assignment.

A firm's group apex is its ultimate owner at the group threshold, or the firm
itself when it is widely held. Seeds (seeds/business_groups.yaml) only provide
human-readable labels: membership always comes from the data.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pandas as pd
import yaml

from .names import short_company_name
from .utils import LOG

SET_INDUSTRY_OF_SECTOR = {
    "AGRI": "AGRO", "FOOD": "AGRO", "FASHION": "CONSUMP", "HOME": "CONSUMP", "PERSON": "CONSUMP",
    "BANK": "FINCIAL", "FIN": "FINCIAL", "INSUR": "FINCIAL", "AUTO": "INDUS", "IMM": "INDUS",
    "PAPER": "INDUS", "PETRO": "INDUS", "PKG": "INDUS", "STEEL": "INDUS", "CONMAT": "PROPCON",
    "CONS": "PROPCON", "PF&REIT": "PROPCON", "PROP": "PROPCON", "ENERG": "RESOURC", "MINE": "RESOURC",
    "COMM": "SERVICE", "HELTH": "SERVICE", "MEDIA": "SERVICE", "PROF": "SERVICE", "TOURISM": "SERVICE",
    "TRANS": "SERVICE", "ETRON": "TECH", "ICT": "TECH",
}


def load_seeds(path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data.get("groups", [])


def assign(entities_agg: pd.DataFrame, uo: pd.DataFrame, holdings: pd.DataFrame, seats: pd.DataFrame,
           seeds: list[dict], t: float, link_min_pct: float = 1.0, split_under=("state", "crown")) -> dict:
    U = uo[uo["threshold"] == t].copy()
    E = entities_agg.set_index("id")
    U["group_id"] = U["uo_id"].where(U["uo_id"].notna(), U["firm"])
    if split_under:
        U["group_id"] = _split_groups(U, holdings, set(split_under))
    apex_of_wh = U[U["uo_id"].isna()]
    members = pd.concat([
        U[["firm", "group_id", "depth", "cr", "cf", "wedge", "pyramid", "uo_type"]].rename(columns={"firm": "entity"}),
        pd.DataFrame({"entity": U["group_id"].unique(), "group_id": U["group_id"].unique()}),
    ], ignore_index=True).drop_duplicates("entity", keep="first")
    members["role"] = "subsidiary"
    members.loc[members["entity"] == members["group_id"], "role"] = "apex"
    is_listed = members["entity"].str.startswith("L:")
    members.loc[is_listed & (members["role"] != "apex"), "role"] = "listed"
    etype = E["etype"]
    members.loc[(members["role"] == "subsidiary") & members["entity"].map(etype).eq("company")
                & members["entity"].isin(holdings["owner"]), "role"] = "holding"

    # group type from apex
    gt = U.drop_duplicates("group_id").set_index("group_id")["uo_type"]
    wh_self = set(apex_of_wh["firm"])
    fi = E.get("fi_type", pd.Series(dtype=str)).fillna("")

    nodata = set(U.loc[U["uo_id"].isna() & U["uo_type"].eq("listed_no_data"), "firm"])

    def gtype(g):
        if g in nodata:
            return "listed_no_data"
        if g in wh_self:
            return "widely_held_financial" if fi.get(g, "") else "widely_held_corporation"
        return gt.get(g, "unknown")

    sector = E.get("sector", pd.Series(dtype=object))
    mcap = pd.to_numeric(E.get("market_cap", pd.Series(dtype=float)), errors="coerce")
    country = E.get("country", pd.Series(dtype=object)).fillna("TH")
    rows = []
    for g, grp in members.groupby("group_id"):
        firms = grp[grp["role"] != "apex"]["entity"].tolist()
        if g.startswith(("L:", "C:")):
            firms_all = firms + [g]
        else:
            firms_all = firms
        secs = {SET_INDUSTRY_OF_SECTOR.get(str(sector.get(f, "")).upper(), None) for f in firms_all}
        secs.discard(None)
        listed = [f for f in firms_all if f.startswith("L:")]
        lw = grp[grp["entity"].isin(listed) & grp["wedge"].notna()]["wedge"]
        rows.append(dict(
            group_id=g, apex_name=E["name"].get(g, g), group_type=gtype(g), n_firms=len(firms_all),
            n_listed=len(listed), n_foreign=sum(str(country.get(f, "TH")) not in ("TH", "", "nan") for f in firms_all),
            n_fi=sum(bool(fi.get(f, "")) for f in firms_all), n_industries=len(secs),
            industries=";".join(sorted(secs)), max_depth=float(grp["depth"].max()) if grp["depth"].notna().any() else 0.0,
            mean_wedge_listed=float(lw.mean()) if len(lw) else float("nan"),
            mcap=float(mcap.reindex(listed).fillna(0).sum()), listed_tickers=";".join(sorted(x[2:] for x in listed)),
        ))
    groups = pd.DataFrame(rows)

    # labels from seeds ------------------------------------------------------
    gid_of = dict(zip(members["entity"], members["group_id"]))
    label, seed_rows = {}, []
    for s in seeds:
        gids = defaultdict(list)
        for tk in s.get("anchors", []) or []:
            gid = gid_of.get(f"L:{str(tk).upper()}")
            seed_rows.append(dict(seed=s.get("id"), anchor=tk, group_id=gid or "",
                                  status="found" if gid else "anchor_not_in_data"))
            if gid:
                gids[gid].append(tk)
        for gid in gids:
            label.setdefault(gid, []).append(s.get("name_en") or s.get("id"))
        if len(gids) > 1:
            seed_rows.append(dict(seed=s.get("id"), anchor="*", group_id=";".join(gids),
                                  status="anchors_split_across_groups"))

    def fallback(r):
        if r.group_id in label:
            return " / ".join(dict.fromkeys(label[r.group_id]))
        if r.group_id.startswith("F:"):
            return E["name"].get(r.group_id, r.group_id)
        if r.group_id.startswith("L:"):
            return f"{r.group_id[2:]} ({short_company_name(E['name'].get(r.group_id, ''), 22)})"
        return short_company_name(str(r.apex_name), 30)

    groups["label"] = groups.apply(fallback, axis=1) if len(groups) else []
    groups["seeded"] = groups["group_id"].isin(label) if len(groups) else []
    groups = groups.sort_values(["n_firms", "n_listed"], ascending=False).reset_index(drop=True)
    groups["rank"] = range(1, len(groups) + 1)

    ties = inter_group_ties(members, holdings, seats, link_min_pct)
    LOG.info("groups: %d (multi-firm %d, multi-listed %d)", len(groups), int((groups["n_firms"] >= 2).sum()),
             int((groups["n_listed"] >= 2).sum()))
    return {"members": members, "groups": groups, "seed_report": pd.DataFrame(seed_rows), "ties": ties}


def inter_group_ties(members: pd.DataFrame, holdings: pd.DataFrame, seats: pd.DataFrame,
                     link_min_pct: float) -> pd.DataFrame:
    gid = dict(zip(members["entity"], members["group_id"]))
    rows = defaultdict(lambda: {"ownership": 0, "directors": 0})
    h = holdings[holdings["pct"] >= link_min_pct]
    for o, d in zip(h["owner"], h["owned"]):
        a, b = gid.get(o), gid.get(d)
        if a and b and a != b:
            rows[tuple(sorted((a, b)))]["ownership"] += 1
    if seats is not None and len(seats):
        s = seats.assign(g=seats["entity"].map(gid)).dropna(subset=["g"])
        for _, grp in s.groupby("person"):
            gs = sorted(set(grp["g"]))
            for i in range(len(gs)):
                for j in range(i + 1, len(gs)):
                    rows[(gs[i], gs[j])]["directors"] += 1
    out = pd.DataFrame([dict(g1=k[0], g2=k[1], **v) for k, v in rows.items()],
                       columns=["g1", "g2", "ownership", "directors"])
    out["weight"] = out["ownership"] * 2 + out["directors"]
    return out


def _split_groups(U: pd.DataFrame, holdings: pd.DataFrame, types: set) -> list:
    """State- or Crown-controlled firms are grouped under their top firm (e.g. PTT, AOT) rather than
    under the owning agency, so unrelated state enterprises do not merge into one 'group'.
    Ultimate-owner statistics are unaffected."""
    uo_of = dict(zip(U["firm"], U["uo_id"]))
    best = {}
    for o, d in zip(*holdings.sort_values("pct", ascending=False)[["owner", "owned"]].to_numpy().T):
        if d not in best and isinstance(uo_of.get(d), str) and (o == uo_of[d] or uo_of.get(o) == uo_of[d]):
            best[d] = o
    out = []
    for f, u, ut, g in zip(U["firm"], U["uo_id"], U["uo_type"], U["group_id"]):
        if ut not in types or not isinstance(u, str):
            out.append(g)
            continue
        x, seen = f, set()
        while True:
            o = best.get(x)
            if o is None or o == u or o in seen:
                break
            seen.add(x)
            x = o
        out.append(x)
    return out
