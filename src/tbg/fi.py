"""Finance-business nexus between bank groups and other business groups.

Three link types between a bank group B and a business group G:
  ownership  holdings (>= link_min_pct) between any member of B and any member of G
  directors  persons sitting on a board of a financial institution in B and on a board in G
  funds      funds managed by B's asset-management arm holding shares of G's listed firms
"""
from __future__ import annotations

from collections import defaultdict

import pandas as pd

from .names import fix_thai


def nexus(entities: pd.DataFrame, holdings: pd.DataFrame, seats: pd.DataFrame, members: pd.DataFrame,
          groups: pd.DataFrame, amc_brand_map: dict, link_min_pct: float = 1.0) -> tuple[pd.DataFrame, dict]:
    E = entities.set_index("id")
    fi = E.get("fi_type", pd.Series(dtype=str)).fillna("")
    gid = dict(zip(members["entity"], members["group_id"]))
    bank_entities = [e for e, t in fi.items() if t in ("bank", "fin_holding")]
    bank_groups = sorted({gid[e] for e in bank_entities if e in gid})
    bset = set(bank_groups)
    links = defaultdict(lambda: {"ownership": 0, "directors": 0, "funds": 0})

    h = holdings[holdings["pct"] >= link_min_pct]
    for o, d in zip(h["owner"], h["owned"]):
        a, b = gid.get(o), gid.get(d)
        if a and b and a != b:
            if a in bset and b not in bset:
                links[(a, b)]["ownership"] += 1
            elif b in bset and a not in bset:
                links[(b, a)]["ownership"] += 1

    if seats is not None and len(seats):
        s = seats.copy()
        s["g"] = s["entity"].map(gid)
        s["is_fi"] = s["entity"].map(lambda e: bool(fi.get(e, "")))
        for _, grp in s.dropna(subset=["g"]).groupby("person"):
            bank_side = set(grp.loc[grp["is_fi"] & grp["g"].isin(bset), "g"])
            other = set(grp.loc[~grp["g"].isin(bset), "g"])
            for bg in bank_side:
                for og in other:
                    links[(bg, og)]["directors"] += 1

    # funds -> bank group via AMC brand
    brand = {k.upper(): v.upper() for k, v in (amc_brand_map or {}).items()}
    funds = E[E["etype"] == "fund"]
    fund_bank = {}
    for fid, name in funds["name"].items():
        n = fix_thai(name).upper()
        for k, tk in brand.items():
            if k in n and f"L:{tk}" in gid:
                fund_bank[fid] = gid[f"L:{tk}"]
                break
    for o, d in zip(holdings["owner"], holdings["owned"]):
        if o in fund_bank:
            g = gid.get(d)
            if g and g != fund_bank[o] and g not in bset:
                links[(fund_bank[o], g)]["funds"] += 1

    lab = dict(zip(groups["group_id"], groups["label"]))
    df = pd.DataFrame([dict(bank_group=k[0], group=k[1], **v) for k, v in links.items()],
                      columns=["bank_group", "group", "ownership", "directors", "funds"])
    df["total"] = df[["ownership", "directors", "funds"]].sum(axis=1)
    df["bank_label"] = df["bank_group"].map(lab)
    df["group_label"] = df["group"].map(lab)
    df = df.sort_values("total", ascending=False).reset_index(drop=True)
    big = groups[groups["n_firms"] >= 10]["group_id"]
    big = [g for g in big if g not in bset]
    linked = set(df.loc[df["directors"] > 0, "group"])
    summary = {
        "n_bank_groups": len(bank_groups),
        "n_fi_entities": int((fi != "").sum()),
        "n_banks": int((fi == "bank").sum()),
        "n_nexus_pairs": int(len(df)),
        "n_director_links": int(df["directors"].sum()) if len(df) else 0,
        "n_ownership_links": int(df["ownership"].sum()) if len(df) else 0,
        "n_fund_links": int(df["funds"].sum()) if len(df) else 0,
        "share_big_groups_bank_interlock": (sum(g in linked for g in big) / len(big)) if big else float("nan"),
        "bank_groups": bank_groups,
    }
    return df, summary
