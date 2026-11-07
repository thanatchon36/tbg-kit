"""Entity resolution: maps raw names from many sources to canonical entity IDs.

ID prefixes: L listed company (L:TICKER), C Thai/foreign company, P person,
F family, S state, R crown, I institutional investor, U fund, K custodian,
N Thai NVDR, X unknown.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict

import pandas as pd
from rapidfuzz import fuzz, process

from .classify import classify_holder, guess_country
from .names import company_key, fix_thai, person_key, surname_key
from .utils import stable_id

PREFIX = {"listed": "L", "company": "C", "foreign": "C", "person": "P", "family": "F",
          "state": "S", "crown": "R", "institutional": "I", "fund": "U", "custodian": "K",
          "nvdr": "N", "unknown": "X"}

# Thai <-> English aliases for entities that appear in both scripts.
BUILTIN_ALIASES = {
    "กระทรวงการคลัง": "MINISTRY OF FINANCE",
    "สำนักงานประกันสังคม": "SOCIAL SECURITY OFFICE",
    "กองทุนประกันสังคม": "SOCIAL SECURITY OFFICE",
    "กองทุนบำเหน็จบำนาญข้าราชการ": "GOVERNMENT PENSION FUND",
    "กองทุนบำเหน็จบำนาญข้าราชการ (กบข.)": "GOVERNMENT PENSION FUND",
    "บริษัท ไทยเอ็นวีดีอาร์ จำกัด": "THAI NVDR COMPANY LIMITED",
    "การไฟฟ้าฝ่ายผลิตแห่งประเทศไทย": "ELECTRICITY GENERATING AUTHORITY OF THAILAND",
    "กองทุนเพื่อการฟื้นฟูและพัฒนาระบบสถาบันการเงิน": "FINANCIAL INSTITUTIONS DEVELOPMENT FUND",
    "กองทุนรวมวายุภักษ์หนึ่ง": "VAYUPAK FUND 1",
}


def _isnan(v) -> bool:
    return isinstance(v, float) and math.isnan(v)


class Resolver:
    def __init__(self, auto_score: int = 95, review_score: int = 88,
                 overrides: dict[str, str] | None = None, state_investors_as_state: bool = False):
        self.ents: dict[str, dict] = {}
        self.key2id: dict[str, str] = {}
        self.person2id: dict[str, str] = {}
        self.blocks: dict[str, list[str]] = defaultdict(list)
        self.review: list[dict] = []
        self.auto, self.rev = auto_score, review_score
        self.sias = state_investors_as_state
        self.overrides: dict[str, str] = {}
        for alias, canon in BUILTIN_ALIASES.items():
            self.overrides[company_key(alias)] = canon
        for alias, canon in (overrides or {}).items():
            if alias and canon:
                self.overrides[company_key(alias)] = canon

    # ------------------------------------------------------------------ store
    def _upsert(self, eid: str, etype: str, name: str, source: str | None = None, **attrs) -> str:
        e = self.ents.get(eid)
        if e is None:
            e = {"id": eid, "etype": etype, "name": fix_thai(name), "names": set(), "sources": set()}
            self.ents[eid] = e
        if name:
            e["names"].add(fix_thai(name))
        if source:
            e["sources"].add(source)
        for k, v in attrs.items():
            if v is None or v == "" or _isnan(v):
                continue
            if k not in e or e[k] in (None, "") or _isnan(e[k]):
                e[k] = v
        return eid

    def _register(self, key: str, eid: str) -> None:
        if key and key not in self.key2id:
            self.key2id[key] = eid
            self.blocks[key[:2]].append(key)

    def _override(self, name: str) -> tuple[str, str]:
        k = company_key(name)
        target = self.overrides.get(k)
        if target is None:
            return name, k
        if re.match(r"^[A-Z]:", target):
            return name, "ID::" + target
        return target, company_key(target)

    @staticmethod
    def _compatible(a: str, b: str) -> bool:
        """Guard against merging e.g. 'POWER 1' with 'POWER 2' or 'X' with 'X HOLDING'."""
        da, db = re.findall(r"\d+", a), re.findall(r"\d+", b)
        if da != db or len(a.split()) != len(b.split()):
            return False
        sa, sb = set(a.split()), set(b.split())
        xa, xb = sorted(sa - sb), sorted(sb - sa)
        if len(xa) != len(xb):
            return False
        # every differing token must be a near-identical spelling variant (typo-level)
        return all(fuzz.ratio(x, y) >= 88 for x, y in zip(xa, xb))

    # ------------------------------------------------------------------ public API
    def add_listed(self, ticker: str, name_en: str = "", name_th: str = "", **attrs) -> str:
        t = ticker.strip().upper()
        eid = f"L:{t}"
        self._upsert(eid, "listed", name_en or name_th or t, ticker=t, name_en=name_en,
                     name_th=name_th, is_listed=True, country="TH", **attrs)
        for nm in (name_en, name_th):
            self._register(company_key(nm), eid)
        self.key2id[f"TICKER::{t}"] = eid
        return eid

    def resolve_company(self, name: str, etype: str | None = None, source: str | None = None,
                        **attrs) -> str | None:
        if not name or not str(name).strip():
            return None
        name2, k = self._override(name)
        if k.startswith("ID::"):
            eid = k[4:]
            et = self.ents.get(eid, {}).get("etype", etype or "company")
            return self._upsert(eid, et, name, source=source, **attrs)
        if not k:
            return None
        eid = self.key2id.get(k) or self.key2id.get(f"TICKER::{k}")
        if eid is None:
            cands = self.blocks.get(k[:2], [])
            if cands:
                m = process.extractOne(k, cands, scorer=fuzz.token_sort_ratio, score_cutoff=self.rev)
                if m:
                    mkey, score, _ = m
                    if score >= self.auto and self._compatible(k, mkey):
                        eid = self.key2id[mkey]
                    elif re.findall(r"\d+", k) == re.findall(r"\d+", mkey):
                        self.review.append({"name": fix_thai(name), "key": k, "candidate_key": mkey,
                                            "candidate_id": self.key2id[mkey], "score": round(score, 1),
                                            "source": source or ""})
        if eid is None:
            if etype is None:
                etype = "foreign" if guess_country(name2) != "TH" else "company"
            eid = stable_id(PREFIX.get(etype, "C"), k)
        self._register(k, eid)
        et = self.ents.get(eid, {}).get("etype", etype or "company")
        if "country" not in attrs or not attrs.get("country"):
            attrs["country"] = guess_country(name2)
        return self._upsert(eid, et, name2 if name2 != name else name, source=source, **attrs)

    def resolve_person(self, name: str, source: str | None = None, **attrs) -> str | None:
        k = person_key(name)
        if not k:
            return None
        eid = self.person2id.get(k)
        if eid is None:
            eid = stable_id("P", k)
            self.person2id[k] = eid
        return self._upsert(eid, "person", name, source=source, surname=surname_key(name), **attrs)

    def resolve_any(self, name: str, source: str | None = None, **attrs) -> tuple[str | None, str | None]:
        """Resolve a holder name of unknown type (shareholder lists)."""
        if not name or not str(name).strip():
            return None, None
        name2, k = self._override(name)
        if k.startswith("ID::"):
            eid = k[4:]
            et = self.ents.get(eid, {}).get("etype", "company")
            return self._upsert(eid, et, name, source=source), et
        eid = self.key2id.get(k) or self.key2id.get(f"TICKER::{k}")
        if eid:
            self._upsert(eid, self.ents[eid]["etype"], name, source=source)
            return eid, self.ents[eid]["etype"]
        etype = classify_holder(name2, self.sias)
        if etype == "person":
            return self.resolve_person(name2, source=source, **attrs), "person"
        if etype in ("company", "foreign"):
            return self.resolve_company(name2, etype=etype, source=source, **attrs), etype
        if etype == "nvdr":
            eid = "N:THAI_NVDR"
            self._register(k, eid)
            return self._upsert(eid, "nvdr", "THAI NVDR COMPANY LIMITED", source=source), "nvdr"
        eid = stable_id(PREFIX.get(etype, "X"), k)
        self._register(k, eid)
        return self._upsert(eid, etype, name2, source=source, **attrs), etype

    # ------------------------------------------------------------------ export
    def to_frame(self) -> pd.DataFrame:
        rows = []
        for e in self.ents.values():
            r = {k: v for k, v in e.items() if k not in ("names", "sources")}
            r["aliases"] = " | ".join(sorted(e["names"]))[:2000]
            r["sources"] = ";".join(sorted(e["sources"]))
            rows.append(r)
        df = pd.DataFrame(rows)
        for c in ["ticker", "name_en", "name_th", "country", "sector", "industry", "market",
                  "market_cap", "surname", "is_listed", "fi_type", "lei", "juristic_id", "business"]:
            if c not in df.columns:
                df[c] = None
        df["is_listed"] = df["is_listed"].fillna(False).astype(bool)
        return df

    def review_frame(self) -> pd.DataFrame:
        if not self.review:
            return pd.DataFrame(columns=["name", "key", "candidate_key", "candidate_id", "score", "source"])
        return pd.DataFrame(self.review).drop_duplicates(["key", "candidate_key"])
