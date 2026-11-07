"""Synthetic raw data in the exact formats of the real sources.

Everything generated here is FICTIONAL (invented groups, firms, persons, tickers).
It exists to test the pipeline end-to-end and to preview figures and the paper.
Structures mimic what real Thai data contains: family pyramids, state groups,
foreign parents, bank groups, joint ventures, cross-holdings, a control cycle,
Thai NVDR, custodian accounts, funds, name-format noise, effective-only rows.
"""
from __future__ import annotations

import random
import zlib

import numpy as np
import pandas as pd
import yaml

from .names import company_key
from .utils import ensure_dir, write_csv

STEMS = ["Aster", "Banyan", "Cobalt", "Dahlia", "Ember", "Fjord", "Garnet", "Harbor", "Indigo", "Juniper",
         "Kestrel", "Lumen", "Magnolia", "Nimbus", "Onyx", "Peregrine", "Quartz", "Rowan", "Saffron",
         "Tamarind", "Umber", "Vireo", "Willow", "Xanthe", "Yarrow", "Zephyr", "Acacia", "Basalt", "Cedar",
         "Ebony", "Falcon", "Ginkgo", "Heron", "Iris", "Jasper", "Kapok", "Marigold", "Nectar", "Orchid",
         "Pinecone", "Quill", "Raven", "Sable", "Teak", "Verbena", "Wren", "Yew", "Zinnia"]
SECTORS = {"AGRO": ["AGRI", "FOOD"], "CONSUMP": ["FASHION", "HOME", "PERSON"],
           "INDUS": ["AUTO", "IMM", "PAPER", "PETRO", "PKG", "STEEL"], "PROPCON": ["CONMAT", "CONS", "PROP"],
           "RESOURC": ["ENERG", "MINE"], "SERVICE": ["COMM", "HELTH", "MEDIA", "PROF", "TOURISM", "TRANS"],
           "TECH": ["ETRON", "ICT"]}
WORDS = {"AGRI": ["Agro", "Farms", "Feedmill"], "FOOD": ["Foods", "Beverage", "Dairy"],
         "FASHION": ["Apparel", "Textile"], "HOME": ["Home", "Furnishing"], "PERSON": ["Care", "Cosmetics"],
         "AUTO": ["Auto Parts", "Motors"], "IMM": ["Machinery"], "PAPER": ["Paper"],
         "PETRO": ["Petrochemical", "Polymers"], "PKG": ["Packaging"], "STEEL": ["Steel"],
         "CONMAT": ["Cement", "Building Materials"], "CONS": ["Engineering", "Construction"],
         "PROP": ["Land", "Estate", "Property Development"], "ENERG": ["Energy", "Power", "Renewables"],
         "MINE": ["Mining"], "COMM": ["Retail", "Trading", "Stores"], "HELTH": ["Hospital", "Healthcare"],
         "MEDIA": ["Media", "Broadcasting"], "PROF": ["Services"], "TOURISM": ["Hotels", "Resorts"],
         "TRANS": ["Logistics", "Airways", "Shipping"], "ETRON": ["Electronics"],
         "ICT": ["Digital", "Telecom", "Data Center"],
         "FIN": ["Securities", "Asset Management", "Leasing", "Card Services", "Insurance Broker"]}
GIVEN = ["Anan", "Somchai", "Suda", "Niran", "Pranee", "Wichai", "Kanya", "Prasit", "Malee", "Somsak",
         "Ratana", "Chaiwat", "Nattaya", "Kittisak", "Siriporn", "Thanakorn", "Waraporn", "Apinya", "Ekachai",
         "Pakorn", "Duangjai", "Surasak", "Orawan", "Boonchai", "Jintana", "Weerapong", "Pimchanok", "Sakda"]
SYL = ["ana", "bun", "chai", "dee", "kul", "laem", "mong", "nak", "phan", "rat", "sak", "thong", "won",
       "yot", "siri", "phon", "chan", "kit", "wat", "sut", "rung", "pai", "lert", "ngam"]
FOREIGN = [("JP", "Corporation (Japan)"), ("SG", "Holdings Pte. Ltd."), ("HK", "Group Limited (Hong Kong)"),
           ("CN", "Industrial Co., Ltd. (China)"), ("NL", "International B.V."), ("US", "Global Inc.")]
SUFFIX_TH = ["Co., Ltd.", "Company Limited", "CO.,LTD.", "Co.,Ltd"]
CUSTODIANS = ["OCEANIC NOMINEES LIMITED", "HARBOURVIEW CUSTODY SERVICES A/C CLIENTS",
              "NORTHSTAR NOMINEES PTE. LTD.", "MERIDIAN BANK CUSTODY ACCOUNT"]


class World:
    def __init__(self, seed: int = 42):
        self.rng = np.random.default_rng(seed)
        random.seed(seed)
        self.comp: dict[str, dict] = {}       # canonical name -> attrs
        self.keys: set[str] = set()
        self.edges: list[tuple] = []          # (owner, owned, pct, owner_kind)
        self.listed: dict[str, str] = {}      # ticker -> name
        self.persons: set[str] = set()
        self.boards: dict[str, list[str]] = {}
        self.tickers: set[str] = set()
        self.seeds, self.brand = [], {}
        self.bank_pool: list[str] = []
        self.indep_pool = [self.person(self.surname_random()) for _ in range(650)]

    # ---------------------------------------------------------------- helpers
    def u(self, a, b):
        return float(self.rng.uniform(a, b))

    def surname_random(self):
        return "".join(random.choice(SYL) for _ in range(3)).upper()

    def person(self, surname):
        name = f"{random.choice(['MR.', 'MRS.', 'MISS', 'MR.'])} {random.choice(GIVEN).upper()} {surname}"
        self.persons.add(name)
        return name

    def company(self, name, country="TH", sector=None, group=None):
        base, n = name, 2
        while company_key(name) in self.keys:   # keep synthetic firms distinct after normalisation
            for suf in (" Public Company Limited", " Company Limited", " Co., Ltd.", " CO.,LTD.", " Co.,Ltd",
                        " Pte. Ltd.", " Limited", " Inc.", " B.V."):
                if suf in base:
                    i = base.index(suf)
                    name = f"{base[:i]} {n}{base[i:]}"
                    break
            else:
                name = f"{base} {n}"
            n += 1
        self.keys.add(company_key(name))
        self.comp[name] = dict(country=country, sector=sector, group=group)
        return name

    def new_ticker(self, base):
        base = base.upper()[:4]
        for i in range(1, 99):
            tk = f"{base[:3]}{i}" if len(base) >= 3 else f"{base}{i}"
            if tk not in self.tickers:
                self.tickers.add(tk)
                return tk
        raise RuntimeError("ticker space")

    def add_listed(self, name, ticker):
        self.listed[ticker] = name
        self.comp[name]["ticker"] = ticker
        self.comp[name]["mcap"] = float(np.exp(self.rng.normal(9.3, 1.3)))  # THB million

    def own(self, owner, owned, pct, kind="company"):
        self.edges.append((owner, owned, round(float(pct), 2), kind))

    def subs(self, parent, stem, sectors, n, depth=1, maxd=4, foreign_rate=0.1):
        for _ in range(n):
            sec = random.choice(sectors)
            if self.rng.random() < foreign_rate:
                cc, suf = random.choice(FOREIGN[:3] + [("VN", "Co., Ltd. (Vietnam)"), ("MM", "Limited (Myanmar)")])
                name = self.company(f"{stem} {random.choice(WORDS[sec])} {suf}", cc, sec, stem)
            else:
                name = self.company(f"{stem} {random.choice(WORDS[sec])} {random.choice(SUFFIX_TH)}", "TH", sec, stem)
            r = self.rng.random()
            pct = 100.0 if r < 0.35 else (self.u(51, 99.99) if r < 0.8 else (50.0 if r < 0.88 else self.u(20, 49)))
            self.own(parent, name, pct)
            if depth < maxd and self.rng.random() < 0.28:
                self.subs(name, stem, sectors, int(self.rng.integers(1, 5)), depth + 1, maxd, foreign_rate)

    def board(self, ticker, family=(), execs=(), bank_link=0.0):
        b = list(family) + list(execs) + random.sample(self.indep_pool, int(self.rng.integers(3, 6)))
        if self.bank_pool and self.rng.random() < bank_link:
            b.append(random.choice(self.bank_pool))
        self.boards[ticker] = list(dict.fromkeys(b))


def generate(paths: dict, seed: int = 42) -> dict:
    w = World(seed)
    rng = w.rng

    # ------------------------------------------------------------ bank groups
    banks = [("Alpha", "family"), ("Beta", "state"), ("Gamma", "foreign"), ("Kappa", "widely"), ("Lambda", "saffron")]
    for stem, kind in banks:
        bank = w.company(f"{stem} Bank Public Company Limited", "TH", "BANK", stem + "Bank")
        tk = w.new_ticker(stem[:3] + "B")
        w.add_listed(bank, tk)
        w.comp[bank]["mcap"] *= 4
        w.brand[f"{stem.upper()} ASSET MANAGEMENT"] = tk
        fam = []
        if kind == "family":
            sur = "ALPHAWONG"
            fam = [w.person(sur) for _ in range(3)]
            hold = w.company(f"{stem} Financial Group Public Company Limited", "TH", "FIN", stem + "Bank")
            w.add_listed(hold, w.new_ticker(stem[:3] + "F"))
            hc = w.company(f"{stem} Family Holding Co., Ltd.", "TH", None, stem + "Bank")
            for p in fam:
                w.own(p, hc, 100 / 3, "person")
            w.own(hc, hold, w.u(28, 40))
            w.own(hold, bank, 99.5)
        elif kind == "state":
            w.own("MINISTRY OF FINANCE", bank, w.u(51, 56), "state")
        elif kind == "foreign":
            parent = w.company(f"{stem} Financial Group Inc. (Japan)", "JP", "BANK", stem + "Bank")
            w.own(parent, bank, w.u(70, 78))
        elif kind == "saffron":
            pass  # owned later by the Saffron business group (finance-business nexus)
        w.subs(bank, stem, ["FIN"], int(rng.integers(5, 9)), maxd=2, foreign_rate=0.15)
        w.bank_pool += [w.person(w.surname_random()) for _ in range(10)]
        w.board(tk, fam, w.bank_pool[-6:], 0)

    # ------------------------------------------------------------ business groups
    gtypes = ["family"] * 34 + ["state"] * 7 + ["foreign"] * 7
    state_apex = ["MINISTRY OF FINANCE", "SYNTHETIC ELECTRICITY AUTHORITY (STATE)", "SYNTHETIC PORT AUTHORITY (STATE)"]
    cycle_done = False
    for gi, (stem, gtype) in enumerate(zip(STEMS, gtypes)):
        ind = random.sample(list(SECTORS), k=int(rng.integers(2, 6)))
        secs = [s for i in ind for s in SECTORS[i]]
        big = gi < 8
        n_listed = int(rng.integers(5, 9)) if big else 1 + int(min(rng.poisson(1.6), 5))
        fam, execs, holdings_cos = [], [w.person(w.surname_random()) for _ in range(3)], []
        if gtype == "family":
            sur = (stem + random.choice(["KUL", "WONG", "PHAN", "SIRI", "CHAI"])).upper()
            fam = [w.person(sur) for _ in range(int(rng.integers(3, 7)))]
            for hname in ["Holding", "Capital", "Investment"][: int(rng.integers(1, 4))]:
                hc = w.company(f"{stem} {hname} {random.choice(SUFFIX_TH)}", "TH", None, stem)
                shares = rng.dirichlet(np.ones(len(fam))) * 100
                for p, s in zip(fam, shares):
                    w.own(p, hc, s, "person")
                holdings_cos.append(hc)
        elif gtype == "state":
            holdings_cos = [state_apex[gi % 3]]
        else:
            cc, suf = random.choice(FOREIGN)
            parent = w.company(f"{stem} {suf}", cc, None, stem)
            thai = w.company(f"{stem} (Thailand) Co., Ltd.", "TH", None, stem)
            w.own(parent, thai, 100)
            holdings_cos = [thai]
        listed_names = []
        for k in range(n_listed):
            sec = secs[k % len(secs)]
            nm = w.company(f"{stem} {random.choice(WORDS[sec])} Public Company Limited", "TH", sec, stem)
            w.add_listed(nm, w.new_ticker(stem[:3]))
            if big:
                w.comp[nm]["mcap"] *= 3
            kind = "state" if gtype == "state" else "company"
            if k == 0 or not listed_names or rng.random() < 0.45:
                w.own(random.choice(holdings_cos), nm, w.u(25, 52), kind)
            else:
                w.own(random.choice(listed_names), nm, w.u(22, 58))       # pyramid via listed firm
            if gtype == "family":
                for p in random.sample(fam, k=min(len(fam), int(rng.integers(1, 4)))):
                    w.own(p, nm, w.u(0.4, 4.5), "person")
            listed_names.append(nm)
            nsub = int(np.clip(rng.lognormal(2.6 if big else 2.0, 0.7), 2, 140))
            w.subs(nm, stem, secs, nsub)
            w.board(w.comp[nm]["ticker"], random.sample(fam, k=min(3, len(fam))) if fam else [],
                    execs, bank_link=0.3)
        for hc in holdings_cos:  # sister companies outside the listed arm
            if hc in w.comp and gtype == "family":
                w.subs(hc, stem, secs, int(rng.integers(0, 8)), maxd=2)
        if gtype == "family" and len(listed_names) >= 2 and rng.random() < 0.3:
            w.own(listed_names[1], listed_names[0], w.u(1, 5))            # reciprocal cross-holding
        if not cycle_done and len(listed_names) >= 3:
            w.own(listed_names[2], listed_names[0], 4.0)                 # 3-firm control cycle
            cycle_done = True
        # joint ventures with another group's flagship
        if gi > 0 and rng.random() < 0.35:
            other = random.choice([n for n in w.listed.values() if w.comp[n]["group"] != stem])
            jv = w.company(f"{stem}-{w.comp[other]['group']} Joint Venture Co., Ltd.", "TH", random.choice(secs), stem)
            w.own(listed_names[0], jv, 50)
            w.own(other, jv, 50)
        if stem == "Saffron":
            w.own(holdings_cos[0], "Lambda Bank Public Company Limited", 34.0)
        anchors = [w.comp[n]["ticker"] for n in listed_names[:2]]
        w.seeds.append({"id": stem.lower(), "name_en": f"{stem} Group", "owner_type_hint": gtype,
                        "anchors": anchors, "verified": True})

    # ------------------------------------------------------------ standalone listed firms
    for i in range(370):
        widely = i >= 280
        ind = random.choice(list(SECTORS))
        sec = random.choice(SECTORS[ind])
        stem = "".join(random.choice(SYL) for _ in range(2)).title()
        nm = w.company(f"{stem} {random.choice(WORDS[sec])} Public Company Limited", "TH", sec, f"solo{i}")
        w.add_listed(nm, w.new_ticker("Z" + stem[:2]))
        if not widely:
            sur = w.surname_random()
            fam = [w.person(sur) for _ in range(int(rng.integers(1, 4)))]
            for p, s in zip(fam, rng.dirichlet(np.ones(len(fam))) * w.u(22, 60)):
                w.own(p, nm, s, "person")
        w.subs(nm, stem, SECTORS[ind], int(np.clip(rng.lognormal(1.2, 0.8), 0, 30)), maxd=3)
        w.board(w.comp[nm]["ticker"], [], [], bank_link=0.08)

    return emit(w, paths)


def _variant(name: str, rng) -> str:
    r = rng.random()
    out = name
    if r < 0.25:
        out = name.replace("Co., Ltd.", "Company Limited").replace("Public Company Limited", "PCL")
    elif r < 0.4:
        out = name.upper()
    elif r < 0.5:
        out = name.replace("Company Limited", "Co., Ltd.")
    return out


def emit(w: World, paths: dict) -> dict:
    rng = w.rng
    raw, man = paths["raw"], paths["manual"]
    as_of, fy = "2026-03-15", 2025
    # universe ----------------------------------------------------------------
    rows = []
    for tk, nm in w.listed.items():
        c = w.comp[nm]
        sec = c["sector"] or "FIN"
        ind = next((i for i, ss in SECTORS.items() if sec in ss), "FINCIAL")
        if sec in ("BANK", "FIN"):
            ind = "FINCIAL"
        rows.append(dict(ticker=tk, name_en=nm, name_th="", market="SET" if rng.random() < 0.8 else "mai",
                         industry=ind, sector=sec, market_cap=round(c["mcap"], 1)))
    write_csv(pd.DataFrame(rows), ensure_dir(raw / "universe") / "listed_companies.csv")

    # top-10 shareholders --------------------------------------------------------
    into = {}
    for o, d, p, k in w.edges:
        into.setdefault(d, []).append((o, p))
    top = []
    funds = [f"{b} EQUITY FUND {i}" for b in w.brand for i in (1, 2, 3)] + ["SOCIAL SECURITY OFFICE",
                                                                          "GOVERNMENT PENSION FUND"]
    for tk, nm in w.listed.items():
        holders = list(into.get(nm, []))
        holders.append(("THAI NVDR COMPANY LIMITED" if rng.random() < 0.7 else "Thai NVDR Co., Ltd.", w.u(1.5, 11)))
        for c in random.sample(CUSTODIANS, k=int(rng.integers(1, 3))):
            holders.append((c, w.u(0.8, 5)))
        for f in random.sample(funds, k=int(rng.integers(1, 4))):
            holders.append((f, w.u(0.4, 3.2)))
        if not holders or max(p for _, p in holders) < 15:   # widely held: dispersed individuals
            for _ in range(6):
                holders.append((w.person(w.surname_random()), w.u(0.5, 7.5)))
        for _ in range(4):
            holders.append((w.person(w.surname_random()), w.u(0.2, 1.2)))
        holders.sort(key=lambda x: -x[1])
        tot = sum(p for _, p in holders[:10])
        f = min(1.0, 92 / tot) if tot else 1
        for rk, (h, p) in enumerate(holders[:10], 1):
            name = _variant(h, rng) if h in w.comp else h
            top.append(dict(ticker=tk, as_of=as_of, rank=rk, holder_name=name, shares=int(p * f * 1e7),
                            pct=f"{p * f:.2f}", source="SYNTHETIC"))
    write_csv(pd.DataFrame(top), ensure_dir(raw / "shareholders") / "top10.csv")

    # subsidiaries reported by each listed firm (56-1 One Report style) --------------
    out = {}
    for o, d, p, k in w.edges:
        out.setdefault(o, []).append((d, p))
    subs = []
    for tk, nm in w.listed.items():
        stack = [(nm, 1.0, 0)]
        seen = {nm}
        while stack:
            par, eff, dep = stack.pop()
            for child, p in out.get(par, []):
                if child in seen or p < 20 or dep >= 4:
                    continue
                seen.add(child)
                e2 = eff * p / 100
                indirect = par != nm
                hide_parent = indirect and rng.random() < 0.2
                rel = "subsidiary" if p > 50 else ("joint_venture" if p == 50 else "associate")
                subs.append(dict(reporting_ticker=tk, fiscal_year=fy, entity_name=_variant(child, rng),
                                 entity_name_alt="", relationship=rel,
                                 immediate_parent="" if (hide_parent or not indirect) else _variant(par, rng),
                                 pct_direct="" if hide_parent else f"{p:.2f}", pct_effective=f"{e2 * 100:.2f}",
                                 country=w.comp.get(child, {}).get("country", "TH"),
                                 business=w.comp.get(child, {}).get("sector") or "", sector=w.comp.get(child, {}).get("sector") or "",
                                 source_doc=f"{tk}_{fy}_56-1.pdf", page=int(rng.integers(20, 60)),
                                 confidence=round(w.u(0.85, 1.0), 2)))
                stack.append((child, e2, dep + 1))
    write_csv(pd.DataFrame(subs), ensure_dir(raw / "subsidiaries") / "extracted.csv")

    # DBD BOJ.5 for ~70% of private family holding companies ------------------------
    boj = []
    for o, d, p, k in w.edges:
        if k == "person" and d in w.comp and "ticker" not in w.comp[d]:
            if zlib.crc32(d.encode()) % 10 < 7:
                boj.append(dict(company_name=d, juristic_id="", as_of="2025-04-30", holder_name=o,
                                shares=int(p * 1e5), pct=f"{p:.2f}", source_doc="BOJ5_SYNTHETIC.pdf"))
    for o, d, p, k in w.edges:   # foreign parents of Thai holding companies
        if d.endswith("(Thailand) Co., Ltd.") and w.comp.get(o, {}).get("country", "TH") != "TH":
            boj.append(dict(company_name=d, juristic_id="", as_of="2025-04-30", holder_name=o,
                            shares=int(p * 1e5), pct=f"{p:.2f}", source_doc="BOJ5_SYNTHETIC.pdf"))
    write_csv(pd.DataFrame(boj), ensure_dir(raw / "dbd") / "boj5.csv")

    # directors -----------------------------------------------------------------
    drs = [dict(ticker=tk, entity_name="", person_name=p, position="Director", as_of=as_of, source="SYNTHETIC")
           for tk, b in w.boards.items() for p in b]
    write_csv(pd.DataFrame(drs), ensure_dir(raw / "directors") / "directors.csv")

    # FI licences + GLEIF ----------------------------------------------------------
    lic, gle, rel = [], [], []
    for nm, c in w.comp.items():
        if c.get("sector") in ("BANK", "FIN"):
            lt = "bank" if c.get("sector") == "BANK" else ("securities" if "Securities" in nm else
                                                           "asset_mgmt" if "Asset" in nm else "leasing")
            lic.append(dict(entity_name=nm, license_type=lt, regulator="SYNTHETIC", as_of=as_of, source="SYNTHETIC"))
            lei = f"SYN{zlib.crc32(nm.encode()):017d}"
            gle.append(dict(lei=lei, legal_name=nm.upper(), country=c["country"], status="ACTIVE", category="GENERAL",
                            legal_form=""))
            c["lei"] = lei
    for o, d, p, k in w.edges:
        if "lei" in w.comp.get(d, {}) and p > 50 and o in w.comp:
            rel.append(dict(child_lei=w.comp[d]["lei"], parent_lei=w.comp[o].get("lei", ""),
                            relationship_type="direct-parent", parent_name=o, child_name=d))
    write_csv(pd.DataFrame(lic), ensure_dir(raw / "fi") / "fi_licenses.csv")
    write_csv(pd.DataFrame(gle), ensure_dir(raw / "gleif") / "th_entities.csv")
    write_csv(pd.DataFrame(rel), raw / "gleif" / "relationships.csv")

    # manual files + seeds ----------------------------------------------------------
    ensure_dir(man)
    write_csv(pd.DataFrame([dict(alias="Thai NVDR Co., Ltd.", canonical="THAI NVDR COMPANY LIMITED",
                                 note="example override")]), man / "entity_overrides.csv")
    write_csv(pd.DataFrame(columns=["person_name", "family_id", "note"]), man / "family_map.csv")
    with (man / "seeds.yaml").open("w", encoding="utf-8") as fh:
        yaml.safe_dump({"groups": w.seeds}, fh, allow_unicode=True, sort_keys=False)
    return {"brand_map": w.brand, "n_listed": len(w.listed), "n_companies": len(w.comp),
            "n_edges": len(w.edges), "n_persons": len(w.persons)}
