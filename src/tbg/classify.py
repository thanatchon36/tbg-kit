"""Rule-based classification of shareholder names (Thai and English).

Order matters: the first matching rule wins. Unmatched names fall back to
person / foreign / company heuristics. Review `review/holder_types.csv` after
each build and add aliases or overrides where rules misfire.
"""
from __future__ import annotations

import re

from .names import fix_thai, has_title, is_person_like, looks_like_company

_RULES_RAW: list[tuple[str, list[str]]] = [
    ("nvdr", [r"NVDR", r"เอ็นวีดีอาร์"]),
    # Holdings related to the Crown are kept in a separate, neutral category.
    ("crown", [r"CROWN PROPERTY", r"ทรัพย์สินพระมหากษัตริย์", r"ทรัพย์สินส่วนพระมหากษัตริย์",
               r"HIS MAJESTY", r"พระบาทสมเด็จพระ"]),
    ("institutional", [r"SOCIAL SECURITY", r"ประกันสังคม", r"GOVERNMENT PENSION FUND",
                       r"บำเหน็จบำนาญข้าราชการ", r"VAYUPAK", r"วายุภักษ์", r"THAILAND FUTURE FUND"]),
    ("state", [r"MINISTRY OF", r"^กระทรวง", r"FINANCIAL INSTITUTIONS DEVELOPMENT FUND",
               r"กองทุนเพื่อการฟื้นฟู", r"ELECTRICITY GENERATING AUTHORITY", r"การไฟฟ้า",
               r"PROVINCIAL ELECTRICITY", r"METROPOLITAN ELECTRICITY", r"STATE RAILWAY",
               r"^การ(?:รถไฟ|ท่าเรือ|ทางพิเศษ|ประปา|เคหะ|สื่อสาร|ท่องเที่ยว)", r"BANK OF THAILAND",
               r"ธนาคารแห่งประเทศไทย", r"STATE ENTERPRISE", r"รัฐวิสาหกิจ", r"^องค์การ",
               r"AUTHORITY OF THAILAND", r"STATE AGENCY", r"\(STATE\)"]),
    ("custodian", [r"NOMINEE", r"CUSTOD", r"CLEARSTREAM", r"EUROCLEAR", r"STATE STREET",
                   r"BNY MELLON", r"BANK OF NEW YORK", r"\bA/C\b", r"FOR THE ACCOUNT OF",
                   r"เพื่อลูกค้า", r"CLIENTS? ACCOUNT", r"UBS AG", r"\bBRANCH\b.*\bCLIENT"]),
    ("fund", [r"\bFUND\b", r"กองทุน", r"\bETF\b", r"UNIT TRUST", r"PROVIDENT", r"สำรองเลี้ยงชีพ",
              r"\bRMF\b", r"\bSSF\b", r"\bLTF\b", r"MUTUAL FUND"]),
]
RULES = [(t, [re.compile(p) for p in pats]) for t, pats in _RULES_RAW]

_COUNTRY_HINTS = [
    ("SG", r"\bPTE\b|SINGAPORE"), ("MY", r"SDN\.?\s*BHD|MALAYSIA"), ("HK", r"HONG KONG|\(HK\)"),
    ("NL", r"\bB\.V\b|\bB\.V\.|NETHERLANDS"), ("DE", r"\bGMBH\b|GERMANY"),
    ("JP", r"\bK\.K\b|KABUSHIKI|JAPAN"), ("CN", r"\bCHINA\b|SHANGHAI|BEIJING|SHENZHEN"),
    ("VN", r"VIETNAM|VIET NAM"), ("ID", r"^PT\s|INDONESIA"), ("US", r"\bLLC\b|\bINC\b\.?$|DELAWARE"),
    ("GB", r"\bPLC\b|UNITED KINGDOM|\bU\.K\.\b"), ("KY", r"CAYMAN"), ("VG", r"BRITISH VIRGIN|\bBVI\b"),
    ("LU", r"LUXEMBOURG"), ("MM", r"MYANMAR"), ("KH", r"CAMBODIA"), ("LA", r"\bLAO\b|LAOS"),
    ("PH", r"PHILIPPINES"), ("IN", r"\bINDIA\b|PRIVATE LIMITED$"), ("AU", r"AUSTRALIA|PTY"),
]
_COUNTRY_RE = [(c, re.compile(p)) for c, p in _COUNTRY_HINTS]


def classify_holder(name: str, state_investors_as_state: bool = False) -> str:
    s = fix_thai(name).upper()
    if not s:
        return "unknown"
    for etype, pats in RULES:
        if any(p.search(s) for p in pats):
            if etype == "institutional" and state_investors_as_state:
                return "state"
            return etype
    if has_title(s) or is_person_like(s):
        return "person"
    if guess_country(s) != "TH":
        return "foreign"
    return "company" if looks_like_company(s) or s else "unknown"


def guess_country(name: str, default: str = "TH") -> str:
    s = fix_thai(name).upper()
    if re.search(r"[\u0E00-\u0E7F]", s):
        return "TH"
    if "(THAILAND)" in s or "THAILAND" in s or "SIAM" in s or "BANGKOK" in s:
        return "TH"
    for code, rx in _COUNTRY_RE:
        if rx.search(s):
            return code
    return default


_FI_RULES = [
    ("fin_holding", [r"FINANCIAL GROUP", r"ไฟแนนเชียล ?กรุ๊ป", r"FINANCIAL HOLDING"]),
    ("asset_mgmt", [r"ASSET MANAGEMENT", r"หลักทรัพย์จัดการกองทุน", r"FUND MANAGEMENT", r"บริหารสินทรัพย์"]),
    ("securities", [r"SECURITIES", r"หลักทรัพย์"]),
    ("insurance", [r"INSURANCE", r"ASSURANCE", r"ประกันภัย", r"ประกันชีวิต"]),
    ("bank", [r"\bBANK\b", r"^ธนาคาร"]),
    ("leasing", [r"LEASING", r"ลีสซิ่ง", r"HIRE PURCHASE", r"เช่าซื้อ", r"\bCARDS?\b", r"บัตรเครดิต",
                 r"\bCREDIT\b", r"สินเชื่อ"]),
]
_FI_RE = [(t, [re.compile(p) for p in ps]) for t, ps in _FI_RULES]
SECTOR_FI = {"BANK": "bank", "FIN": "finance", "INSUR": "insurance"}


def fi_type_from(name: str = "", sector: str = "", license_type: str = "") -> str:
    """Return a financial-institution type or '' for non-financial entities."""
    if license_type:
        lt = license_type.lower()
        for key in ("bank", "insurance", "securities", "asset_mgmt", "leasing", "fin_holding"):
            if key.split("_")[0] in lt:
                return key
        return "finance"
    if sector and sector.upper() in SECTOR_FI:
        sec = SECTOR_FI[sector.upper()]
        if sec == "bank":
            return "bank"
    s = fix_thai(name).upper()
    for t, pats in _FI_RE:
        if any(p.search(s) for p in pats):
            return t
    if sector and sector.upper() in SECTOR_FI:
        return SECTOR_FI[sector.upper()]
    return ""
