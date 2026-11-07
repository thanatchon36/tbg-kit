"""Shared helpers: logging, Thai-safe CSV IO, flexible table reading, number parsing."""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd

LOG = logging.getLogger("tbg")


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO,
                        format="%(asctime)s | %(levelname)-7s | %(message)s", datefmt="%H:%M:%S")
    for noisy in ("fontTools", "matplotlib", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def ensure_dir(p) -> Path:
    p = Path(p)
    p.mkdir(parents=True, exist_ok=True)
    return p


def write_csv(df: pd.DataFrame, path) -> Path:
    """UTF-8 with BOM so that Thai text opens correctly in Excel."""
    path = Path(path)
    ensure_dir(path.parent)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if np.isnan(o) else float(o)
    if isinstance(o, (set, tuple)):
        return list(o)
    if isinstance(o, Path):
        return str(o)
    return str(o)


def write_json(obj, path) -> Path:
    path = Path(path)
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2, default=_json_default)
    return path


def read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def stable_id(prefix: str, key: str) -> str:
    return f"{prefix}:{hashlib.sha1(key.encode('utf-8')).hexdigest()[:10]}"


_NUM_RE = re.compile(r"[-+]?\d*\.?\d+")
_MISSING = {"", "-", "–", "—", "N/A", "n/a", "NA", "nan", "None", "null"}


def to_float(x) -> float:
    """Parse numbers such as '12.34%', '1,234.5', 'ร้อยละ 40'. Missing -> NaN."""
    if x is None:
        return math.nan
    if isinstance(x, (int, float, np.integer, np.floating)):
        x = float(x)
        return math.nan if math.isnan(x) else x
    s = str(x).strip()
    if s in _MISSING:
        return math.nan
    s = s.replace("ร้อยละ", "").replace("%", "").replace(",", "").replace(" ", "")
    m = _NUM_RE.search(s)
    return float(m.group()) if m else math.nan


# --------------------------------------------------------------------------- tables
SCHEMAS: dict[str, list[str]] = {
    "universe": ["ticker", "name_en", "name_th", "market", "industry", "sector", "market_cap"],
    "top10": ["ticker", "as_of", "rank", "holder_name", "shares", "pct", "source"],
    "subsidiaries": ["reporting_ticker", "fiscal_year", "entity_name", "entity_name_alt",
                     "relationship", "immediate_parent", "pct_direct", "pct_effective",
                     "country", "business", "sector", "source_doc", "page", "confidence"],
    "boj5": ["company_name", "juristic_id", "as_of", "holder_name", "shares", "pct", "source_doc"],
    "directors": ["ticker", "entity_name", "person_name", "position", "as_of", "source"],
    "fi_licenses": ["entity_name", "license_type", "regulator", "as_of", "source"],
    "pillar3": ["bank_ticker", "as_of", "entity_name", "relationship", "pct", "country",
                "business", "source_doc", "page"],
    "gleif_entities": ["lei", "legal_name", "country", "status", "category", "legal_form"],
    "gleif_relationships": ["child_lei", "parent_lei", "relationship_type", "parent_name", "child_name"],
    "family_map": ["person_name", "family_id", "note"],
    "overrides": ["alias", "canonical", "note"],
    "document_urls": ["doc_type", "ticker", "year", "lang", "url"],
    "validation": ["firm", "uo_id_checked", "is_correct", "note"],
}

COLUMN_SYNONYMS: dict[str, list[str]] = {
    "ticker": ["symbol", "stock", "securities symbol", "ชื่อย่อ", "ชื่อย่อหลักทรัพย์", "หลักทรัพย์"],
    "name_en": ["company name", "company", "name (en)", "english name", "company_name_en"],
    "name_th": ["ชื่อบริษัท", "company_name_th", "thai name", "name (th)"],
    "market": ["ตลาด"],
    "industry": ["กลุ่มอุตสาหกรรม"],
    "sector": ["หมวดธุรกิจ"],
    "market_cap": ["market cap", "marketcap", "mkt cap", "มูลค่าหลักทรัพย์ตามราคาตลาด"],
    "holder_name": ["shareholder", "shareholder name", "name", "ผู้ถือหุ้น", "ชื่อผู้ถือหุ้น", "holder"],
    "pct": ["%", "percent", "% of shares", "% shares", "สัดส่วน", "ร้อยละ", "% holding", "pct_holding"],
    "shares": ["number of shares", "จำนวนหุ้น", "no. of shares"],
    "as_of": ["date", "book closing date", "วันที่ปิดสมุดทะเบียน", "asof"],
    "reporting_ticker": ["reporter", "parent_ticker"],
    "entity_name": ["subsidiary", "company_name_sub", "investee"],
    "person_name": ["director", "director name", "กรรมการ", "ชื่อกรรมการ"],
    "position": ["ตำแหน่ง", "role"],
}


def _norm_col(c: str) -> str:
    return re.sub(r"\s+", " ", str(c).strip().lower())


def read_table(path, kind: str) -> pd.DataFrame:
    """Read CSV/XLSX leniently and map column names to the standard schema."""
    cols = SCHEMAS[kind]
    path = Path(path)
    if not path.exists():
        return pd.DataFrame(columns=cols)
    if path.suffix.lower() in {".xlsx", ".xls"}:
        df = pd.read_excel(path, dtype=str).fillna("")
    else:
        df = pd.read_csv(path, dtype=str, encoding="utf-8-sig", keep_default_na=False)
    rename, used = {}, set()
    for col in df.columns:
        n = _norm_col(col)
        for std in cols:
            if std in used:
                continue
            if n == std or n in {_norm_col(s) for s in COLUMN_SYNONYMS.get(std, [])}:
                rename[col] = std
                used.add(std)
                break
    df = df.rename(columns=rename)
    for c in cols:
        if c not in df.columns:
            df[c] = ""
    extra = [c for c in df.columns if c not in cols]
    return df[cols + extra].fillna("").astype(str)


def latex_escape(s) -> str:
    s = "" if s is None else str(s)
    rep = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
           "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\^{}"}
    return "".join(rep.get(ch, ch) for ch in s)
