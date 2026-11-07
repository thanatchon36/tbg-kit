"""Assemble raw source files into clean, de-duplicated network tables.

Inputs  (all optional, under <workspace>/data/raw and data/manual):
  universe/listed_companies.csv, shareholders/top10.csv, subsidiaries/extracted.csv,
  dbd/boj5.csv, fi/pillar3.csv, fi/fi_licenses.csv, gleif/th_entities.csv,
  gleif/relationships.csv, directors/directors.csv, manual/entity_overrides.csv,
  manual/family_map.csv
Outputs (<workspace>/data/processed): entities.csv, holdings.csv, board_seats.csv,
  parent_links.csv, person_family.csv ; review queues in <workspace>/review.
"""
from __future__ import annotations

import math

import networkx as nx
import numpy as np
import pandas as pd

from .classify import fi_type_from
from .names import company_key, fix_thai, person_key, surname_key
from .resolve import Resolver
from .utils import LOG, read_table, to_float, write_csv


def read_glob(folder, pattern: str, kind: str) -> pd.DataFrame:
    """Concatenate every CSV/XLSX in `folder` matching `pattern` (users may add files freely)."""
    files = sorted(set(folder.glob(pattern)) | set(folder.glob(pattern.replace(".csv", ".xlsx"))))
    frames = [f for f in (read_table(x, kind) for x in files) if len(f)]
    return pd.concat(frames, ignore_index=True) if frames else read_table(folder / "__none__.csv", kind)


def _latest(df: pd.DataFrame, key: str, date_col: str, limit=None) -> pd.DataFrame:
    if df.empty:
        return df
    d = df.copy()
    d["_d"] = d[date_col].astype(str)
    if limit not in (None, "", "None"):
        d = d[(d["_d"] == "") | (d["_d"] <= str(limit))]
    last = d.groupby(key)["_d"].transform("max")
    return d[d["_d"] == last].drop(columns="_d")


def _pct_series(s: pd.Series) -> pd.Series:
    v = s.map(to_float)
    nonnull = v.dropna()
    if len(nonnull) and nonnull.max() <= 1.0 and nonnull.median() < 1.0:
        LOG.warning("percentages look like fractions (0-1); converting to 0-100")
        v = v * 100.0
    return v


def build(cfg: dict) -> dict[str, pd.DataFrame]:
    P = cfg["_paths"]
    raw, man = P["raw"], P["manual"]
    oc = cfg["ownership"]

    ov = read_table(man / "entity_overrides.csv", "overrides")
    overrides = dict(zip(ov["alias"], ov["canonical"]))
    res = Resolver(cfg["resolution"]["auto_merge_score"], cfg["resolution"]["review_score"],
                   overrides, oc.get("state_investors_as_state", False))
    holdings: list[dict] = []
    parent_links: list[dict] = []
    seats: list[dict] = []

    # 1. universe of listed companies -----------------------------------------
    uni = read_glob(raw / "universe", "*.csv", "universe").drop_duplicates("ticker", keep="last")
    for r in uni.itertuples(index=False):
        if not r.ticker.strip():
            continue
        res.add_listed(r.ticker, fix_thai(r.name_en), fix_thai(r.name_th), market=r.market,
                       industry=r.industry, sector=r.sector, market_cap=to_float(r.market_cap),
                       source="set_universe")
    LOG.info("universe: %d listed companies", len(uni))

    # 2. SET top-10 shareholders -------------------------------------------------
    top = _latest(read_glob(raw / "shareholders", "*.csv", "top10"), "ticker", "as_of",
                  cfg["project"].get("as_of"))
    top["pct_v"] = _pct_series(top["pct"]) if len(top) else []
    for r in top.itertuples(index=False):
        t = r.ticker.strip().upper()
        if not t:
            continue
        owned = f"L:{t}"
        if owned not in res.ents:
            res.add_listed(t, source="set_top10")
        owner, _ = res.resolve_any(r.holder_name, source="set_top10")
        if owner:
            holdings.append(dict(owner=owner, owned=owned, pct=r.pct_v, source="set_top10",
                                 as_of=r.as_of, basis="direct", relationship="shareholder",
                                 doc=r.source or "SET"))
    LOG.info("top-10 rows: %d", len(top))

    # 3. subsidiaries from 56-1 One Report -------------------------------------
    sub = read_glob(raw / "subsidiaries", "*.csv", "subsidiaries")
    if len(sub):
        sub["fy"] = sub["fiscal_year"].map(to_float)
        lim = cfg["project"].get("data_year")
        if lim:
            sub = sub[sub["fy"].isna() | (sub["fy"] <= float(lim))]
        last = sub.groupby("reporting_ticker")["fy"].transform("max")
        sub = sub[(sub["fy"] == last) | last.isna()]
        sub["pd"] = _pct_series(sub["pct_direct"])
        sub["pe"] = _pct_series(sub["pct_effective"])
    reporters = set()
    for r in sub.itertuples(index=False):
        t = r.reporting_ticker.strip().upper()
        if not t or not r.entity_name.strip():
            continue
        reporter = f"L:{t}"
        if reporter not in res.ents:
            res.add_listed(t, source="one_report")
        reporters.add(reporter)
        owned = res.resolve_company(r.entity_name, source="one_report", country=r.country or None,
                                    business=r.business or None, sector=r.sector or None)
        if r.entity_name_alt.strip():
            res._register(company_key(r.entity_name_alt), owned)
        if r.immediate_parent.strip():
            parent = res.resolve_company(r.immediate_parent, source="one_report")
            pct = r.pd if not math.isnan(r.pd) else r.pe
            src = "one_report_direct"
        else:
            parent = reporter
            direct_known = not math.isnan(r.pd)
            pct = r.pd if direct_known else r.pe
            src = "one_report_direct" if direct_known else "one_report_effective"
        if parent and owned and parent != owned:
            holdings.append(dict(owner=parent, owned=owned, pct=pct, source=src,
                                 as_of=str(r.fiscal_year), basis="direct" if src.endswith("direct") else "effective",
                                 relationship=r.relationship or "subsidiary", doc=r.source_doc,
                                 reporter=reporter))
    LOG.info("subsidiary rows: %d from %d reporting companies", len(sub), len(reporters))

    # 4. DBD shareholder lists (BOJ.5) ----------------------------------------
    boj = _latest(read_glob(raw / "dbd", "*.csv", "boj5"), "company_name", "as_of",
                  cfg["project"].get("as_of"))
    if len(boj):
        boj["pct_v"] = _pct_series(boj["pct"])
        sh = boj["shares"].map(to_float)
        tot = sh.groupby(boj["company_name"]).transform("sum")
        boj["pct_v"] = boj["pct_v"].fillna(sh / tot * 100.0)  # BOJ.5 often lists shares only
    for r in boj.itertuples(index=False):
        owned = res.resolve_company(r.company_name, source="dbd_boj5", juristic_id=r.juristic_id or None)
        owner, _ = res.resolve_any(r.holder_name, source="dbd_boj5")
        if owned and owner and owned != owner:
            holdings.append(dict(owner=owner, owned=owned, pct=r.pct_v, source="dbd_boj5", as_of=r.as_of,
                                 basis="direct", relationship="shareholder", doc=r.source_doc))

    # 5. Pillar 3 financial-group composition ---------------------------------
    p3 = read_glob(raw / "fi", "pillar3*.csv", "pillar3")
    for r in p3.itertuples(index=False):
        bank = f"L:{r.bank_ticker.strip().upper()}"
        if bank not in res.ents:
            continue
        owned = res.resolve_company(r.entity_name, source="pillar3", country=r.country or None)
        pct = to_float(r.pct)
        parent_links.append(dict(child=owned, parent=bank, link="financial_group", source="pillar3"))
        if not math.isnan(pct) and owned != bank:
            holdings.append(dict(owner=bank, owned=owned, pct=pct, source="pillar3", as_of=r.as_of,
                                 basis="effective", relationship=r.relationship or "subsidiary",
                                 doc=r.source_doc))

    # 6. GLEIF ------------------------------------------------------------------
    gle = read_table(raw / "gleif" / "th_entities.csv", "gleif_entities")
    lei2id = {}
    for r in gle.itertuples(index=False):
        if r.lei:
            eid = res.key2id.get(company_key(r.legal_name))
            if eid:
                res._upsert(eid, res.ents[eid]["etype"], r.legal_name, source="gleif", lei=r.lei)
                lei2id[r.lei] = eid
    grel = read_table(raw / "gleif" / "relationships.csv", "gleif_relationships")
    for r in grel.itertuples(index=False):
        child = lei2id.get(r.child_lei) or res.key2id.get(company_key(r.child_name))
        parent = lei2id.get(r.parent_lei) or (res.resolve_company(r.parent_name, source="gleif", lei=r.parent_lei)
                                              if r.parent_name else None)
        if child and parent and child != parent:
            parent_links.append(dict(child=child, parent=parent, link=r.relationship_type, source="gleif"))

    # 7. directors ---------------------------------------------------------------
    dirs = read_glob(raw / "directors", "*.csv", "directors")
    for r in dirs.itertuples(index=False):
        if r.ticker.strip():
            ent = f"L:{r.ticker.strip().upper()}"
            if ent not in res.ents:
                res.add_listed(r.ticker, source="directors")
        else:
            ent = res.resolve_company(r.entity_name, source="directors")
        pid = res.resolve_person(r.person_name, source="directors")
        if ent and pid:
            seats.append(dict(person=pid, entity=ent, position=r.position, as_of=r.as_of, source=r.source))

    # 8. FI licences -----------------------------------------------------------
    lic = read_glob(raw / "fi", "fi_licenses*.csv", "fi_licenses")
    lic_map = {}
    for r in lic.itertuples(index=False):
        eid = res.resolve_company(r.entity_name, source="fi_license")
        if eid:
            lic_map[eid] = fi_type_from(license_type=r.license_type)

    # ---------------------------------------------------------------- assemble
    ents = res.to_frame()
    ents["fi_type"] = [lic_map.get(i) or fi_type_from(n, s or "") if et in ("listed", "company", "foreign") else ""
                       for i, n, s, et in zip(ents["id"], ents["name"], ents["sector"].fillna(""), ents["etype"])]
    H = pd.DataFrame(holdings, columns=["owner", "owned", "pct", "source", "as_of", "basis",
                                        "relationship", "doc", "reporter"])
    H, issues = clean_holdings(H, oc)
    seats_df = pd.DataFrame(seats, columns=["person", "entity", "position", "as_of", "source"]).drop_duplicates(
        ["person", "entity"])
    links = pd.DataFrame(parent_links, columns=["child", "parent", "link", "source"]).drop_duplicates()

    # person -> family mapping (manual first, then surname)
    fam = read_table(man / "family_map.csv", "family_map")
    manual_fam = {person_key(a): b for a, b in zip(fam["person_name"], fam["family_id"]) if a and b}
    pf = []
    for r in ents[ents["etype"] == "person"].itertuples(index=False):
        names = str(r.aliases).split(" | ")
        fid = next((manual_fam[person_key(n)] for n in names if person_key(n) in manual_fam), None)
        method = "manual" if fid else "surname"
        if not fid:
            sk = surname_key(r.name)
            fid = f"F:{sk}" if sk else ""
        pf.append(dict(person=r.id, family_id=fid, method=method, name=r.name))
    pf = pd.DataFrame(pf, columns=["person", "family_id", "method", "name"])

    out = P["processed"]
    write_csv(ents, out / "entities.csv")
    write_csv(H, out / "holdings.csv")
    write_csv(seats_df, out / "board_seats.csv")
    write_csv(links, out / "parent_links.csv")
    write_csv(pf, out / "person_family.csv")
    rv = P["review"]
    write_csv(res.review_frame(), rv / "entity_resolution_candidates.csv")
    write_csv(issues, rv / "holdings_issues.csv")
    write_csv(ents[["id", "etype", "name", "aliases", "sources"]].sort_values("etype"), rv / "holder_types.csv")
    LOG.info("entities=%d holdings=%d seats=%d links=%d review_pairs=%d issues=%d",
             len(ents), len(H), len(seats_df), len(links), len(res.review), len(issues))
    return {"entities": ents, "holdings": H, "seats": seats_df, "links": links, "person_family": pf}


def clean_holdings(H: pd.DataFrame, oc: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """De-duplicate edges, prune double-counted effective edges, check totals <= 100%."""
    issues = []
    H = H.copy()
    H["pct"] = pd.to_numeric(H["pct"], errors="coerce")
    bad = H["pct"].isna() | (H["pct"] <= 0) | (H["pct"] > 100.0001) | (H["owner"] == H["owned"])
    for r in H[bad].itertuples(index=False):
        issues.append(dict(issue="invalid_pct_or_self_loop", owner=r.owner, owned=r.owned, pct=r.pct, source=r.source))
    H = H[~bad]
    prio = {s: i for i, s in enumerate(oc["edge_source_priority"])}
    H["_p"] = H["source"].map(lambda s: prio.get(s, 99))
    H = H.sort_values(["_p", "as_of", "pct"], ascending=[True, False, False])
    H = H.drop_duplicates(["owner", "owned"], keep="first")

    # effective edges: drop if the owned entity already has direct ownership information
    eff = H["source"].eq("one_report_effective")
    direct_owned = set(H.loc[~eff, "owned"])
    drop_idx = list(H[eff & H["owned"].isin(direct_owned)].index)
    remaining = H[eff & ~H.index.isin(drop_idx)]
    if len(remaining):
        G = nx.DiGraph()
        G.add_edges_from(zip(H.loc[~eff, "owner"], H.loc[~eff, "owned"]))
        for owned, grp in remaining.groupby("owned"):
            if len(grp) < 2:
                continue
            reps = list(grp["owner"])
            for idx, rep in zip(grp.index, reps):
                if any(o != rep and rep in G and o in G and nx.has_path(G, rep, o) for o in reps):
                    drop_idx.append(idx)
    for r in H.loc[drop_idx].itertuples(index=False):
        issues.append(dict(issue="effective_edge_pruned", owner=r.owner, owned=r.owned, pct=r.pct, source=r.source))
    H = H.drop(index=drop_idx)

    # totals per owned entity
    tot = H.groupby("owned")["pct"].sum()
    over = tot[tot > 100.0 + oc["pct_tolerance"]]
    for owned, t in over.items():
        issues.append(dict(issue="total_over_100", owner="", owned=owned, pct=round(t, 3), source=""))
    if oc.get("scale_over_100", True) and len(over):
        f = (100.0 / H["owned"].map(tot)).clip(upper=1.0)
        H["pct"] = np.where(H["owned"].isin(over.index), H["pct"] * f, H["pct"])
    H = H.drop(columns="_p").reset_index(drop=True)
    return H, pd.DataFrame(issues, columns=["issue", "owner", "owned", "pct", "source"])
