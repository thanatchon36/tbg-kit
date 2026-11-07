"""Name normalisation for Thai and English company / person names.

Handles common Thai-PDF artefacts (Private Use Area glyph variants, decomposed
sara am, doubled sara e), strips legal forms, removes personal titles, and
extracts surnames for family aggregation.
"""
from __future__ import annotations

import re
import unicodedata

# Thai glyph variants that many PDF fonts place in the Unicode Private Use Area.
# Mapping follows the widely used Windows/Mac Thai PUA layout. Verify on your corpus.
_PUA = {
    0xF700: "\u0E10", 0xF701: "\u0E34", 0xF702: "\u0E35", 0xF703: "\u0E36", 0xF704: "\u0E37",
    0xF705: "\u0E48", 0xF706: "\u0E49", 0xF707: "\u0E4A", 0xF708: "\u0E4B", 0xF709: "\u0E4C",
    0xF70A: "\u0E48", 0xF70B: "\u0E49", 0xF70C: "\u0E4A", 0xF70D: "\u0E4B", 0xF70E: "\u0E4C",
    0xF70F: "\u0E0D", 0xF710: "\u0E31", 0xF711: "\u0E4D", 0xF712: "\u0E47", 0xF713: "\u0E48",
    0xF714: "\u0E49", 0xF715: "\u0E4A", 0xF716: "\u0E4B", 0xF717: "\u0E4C", 0xF718: "\u0E38",
    0xF719: "\u0E39", 0xF71A: "\u0E3A",
}
_ZERO_WIDTH = {ord(c): None for c in "\u200b\u200c\u200d\ufeff\u00ad"}
_TRANS = {**_PUA, **_ZERO_WIDTH}
THAI_RANGE = "\u0E00-\u0E7F"


def fix_thai(s) -> str:
    """Repair common Thai text-extraction artefacts and normalise whitespace."""
    if s is None:
        return ""
    s = str(s)
    if not s or s.lower() == "nan":
        return ""
    s = s.translate(_TRANS)
    s = s.replace("\u0E4D\u0E32", "\u0E33")  # nikhahit + sara aa -> sara am
    s = s.replace("\u0E40\u0E40", "\u0E41")  # sara e + sara e -> sara ae
    s = unicodedata.normalize("NFC", s)
    return re.sub(r"\s+", " ", s).strip()


def has_pua(s: str) -> bool:
    return any(0xF700 <= ord(ch) <= 0xF71A for ch in (s or ""))


def script_of(s: str) -> str:
    th = len(re.findall(f"[{THAI_RANGE}]", s or ""))
    lat = len(re.findall(r"[A-Za-z]", s or ""))
    if th and lat:
        return "mixed"
    return "th" if th else ("en" if lat else "none")


# --------------------------------------------------------------------------- companies
_EN_LEGAL = [
    r"\bPUBLIC\s+COMPANY\s+LIMITED\b", r"\bPUBLIC\s+CO\s*[.,]*\s*LTD\b\.?",
    r"\bPUBLIC\s+LIMITED\s+COMPANY\b", r"\bCOMPANY\s+LIMITED\b", r"\bCO\s*[.,]+\s*LTD\b\.?",
    r"\bCO\s+LTD\b\.?", r"\bLIMITED\b", r"\bLTD\b\.?", r"\bPCL\b\.?", r"\bPLC\b\.?",
    r"\bINCORPORATED\b", r"\bINC\b\.?", r"\bCORPORATION\b", r"\bCORP\b\.?", r"\bL\.?L\.?C\b\.?",
    r"\bPTE\b\.?", r"\bSDN\.?\s*BHD\b\.?", r"\bBHD\b\.?", r"\bGMBH\b", r"\bB\.V\.?", r"\bN\.V\.?",
    r"\bS\.A\.?(?=\s|$)", r"\bA\.G\.?(?=\s|$)", r"\bK\.K\.?(?=\s|$)", r"\bCOMPANY\b", r"\bCO\b\.?",
]
_EN_LEGAL_RE = [re.compile(p) for p in _EN_LEGAL]
_TH_LEGAL = ["บริษัทมหาชนจำกัด", "ห้างหุ้นส่วนจำกัด", "ห้างหุ้นส่วนสามัญ", "(มหาชน)", "มหาชน",
             "บริษัท", "จำกัด", "บจก.", "บมจ.", "หจก.", "บจก", "บมจ", "หจก"]


def company_key(name) -> str:
    """Matching key for organisations: upper-case, legal forms and punctuation removed."""
    s = fix_thai(name).upper()
    if not s:
        return ""
    s = s.replace("&", " AND ")
    for pat in _EN_LEGAL_RE:
        s = pat.sub(" ", s)
    for tok in _TH_LEGAL:
        s = s.replace(tok, " ")
    s = re.sub(rf"[^\w{THAI_RANGE} ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return re.sub(r"^THE\s+", "", s)


def short_company_name(name: str, max_len: int = 28) -> str:
    """Readable short label (keeps original casing, drops legal forms)."""
    s = fix_thai(name)
    for pat in [r"\s*\(?Public Company Limited\)?", r"\s*Public Co\.?,?\s*Ltd\.?",
                r"\s*Company Limited", r"\s*Co\.?,?\s*Ltd\.?", r"\s*Limited", r"\s*PCL\.?"]:
        s = re.sub(pat, "", s, flags=re.I)
    for tok in ["บริษัท", "จำกัด", "(มหาชน)"]:
        s = s.replace(tok, "")
    s = re.sub(r"\s+", " ", s).strip(" ,.")
    return s if len(s) <= max_len else s[: max_len - 1] + "…"


# --------------------------------------------------------------------------- persons
_TITLE_EN = re.compile(
    r"^(?:MR|MRS|MISS|MS|MSTR|DR|PROF|ASSOC\.?\s*PROF|ASST\.?\s*PROF|KHUNYING|THANPUYING|KHUN|"
    r"M\.?\s?R\.?\s?W\.?|M\.?\s?R\.?|M\.?\s?L\.?|M\.?\s?C\.?|GEN|LT\.?\s*GEN|MAJ\.?\s*GEN|ADM|ACM|"
    r"POL\.?\s*GEN|POL\.?\s*LT\.?\s*GEN|SIR|H\.?\s?E\.?)(?:\.|\s)\s*")
_TITLE_TH_NOSPACE = ["นางสาว", "น.ส.", "นาย", "นาง", "ด.ช.", "ด.ญ.", "ม.ร.ว.", "ม.ล.", "ม.จ.",
                     "ดร.", "ศ.", "รศ.", "ผศ.", "นพ.", "พญ.", "พล.อ.อ.", "พล.ร.อ.", "พล.ต.อ.",
                     "พล.อ.", "พล.ท.", "พล.ต.", "พ.อ.", "ร.ต.อ.", "คุณหญิง", "ท่านผู้หญิง"]
_TITLE_TH_SPACE = ["คุณ"]


def strip_titles(s: str) -> str:
    s = fix_thai(s)
    changed = True
    while changed and s:
        changed = False
        up = s.upper()
        m = _TITLE_EN.match(up + " ")
        if m and len(m.group(0).strip()) > 0 and len(s) > m.end() - 1:
            s = s[min(m.end(), len(s)):].strip()
            changed = True
            continue
        for t in _TITLE_TH_NOSPACE:
            if s.startswith(t) and len(s) > len(t) + 1:
                s = s[len(t):].strip()
                changed = True
                break
        else:
            for t in _TITLE_TH_SPACE:
                if s.startswith(t + " "):
                    s = s[len(t) + 1:].strip()
                    changed = True
                    break
    return s


def has_title(s: str) -> bool:
    s = fix_thai(s)
    if _TITLE_EN.match(s.upper() + " "):
        return True
    return any(s.startswith(t) for t in _TITLE_TH_NOSPACE) or any(
        s.startswith(t + " ") for t in _TITLE_TH_SPACE)


def person_key(name) -> str:
    s = strip_titles(name).upper()
    s = re.sub(rf"[^\w{THAI_RANGE} ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def surname_key(name) -> str:
    """Last name used for family aggregation ('ณ อยุธยา' / 'NA AYUDHYA' kept as one token)."""
    toks = person_key(name).split()
    if len(toks) < 2:
        return ""
    if len(toks) >= 3 and toks[-2] in {"ณ", "NA"}:
        return toks[-2] + " " + toks[-1]
    return toks[-1]


_COMPANY_HINTS_EN = re.compile(
    r"\b(CO|LTD|LIMITED|COMPANY|CORP|CORPORATION|INC|PCL|PLC|HOLDINGS?|GROUP|BANK|FUND|TRUST|"
    r"NOMINEES?|SECURITIES|ASSETS?|INVESTMENTS?|CAPITAL|ENTERPRISES?|INDUSTR(?:Y|IES)|INTERNATIONAL|"
    r"GMBH|PTE|BHD|LLC|LP|FOUNDATION|MINISTRY|OFFICE|AUTHORITY|DEPARTMENT|GOVERNMENT|PARTNERS(?:HIP)?|"
    r"VENTURES?|MANAGEMENT|SERVICES?|DEVELOPMENT|PROPERT(?:Y|IES)|ESTATE|ENERGY|POWER|FOODS?|TRADING|"
    r"LOGISTICS|SYSTEMS?|TECHNOLOG(?:Y|IES)|SOLUTIONS|RESOURCES|LEASING|INSURANCE|ASSURANCE|NVDR|"
    r"CUSTODY|BRANCH|ACCOUNT|CLIENTS?)\b")
_COMPANY_HINTS_TH = ["บริษัท", "จำกัด", "ธนาคาร", "กองทุน", "มูลนิธิ", "กระทรวง", "สำนักงาน",
                     "การไฟฟ้า", "องค์การ", "ห้างหุ้นส่วน", "สหกรณ์", "บจก", "บมจ", "หจก", "สมาคม",
                     "มหาวิทยาลัย"]


def looks_like_company(s: str) -> bool:
    s = fix_thai(s)
    return bool(_COMPANY_HINTS_EN.search(s.upper())) or any(t in s for t in _COMPANY_HINTS_TH)


def is_person_like(name) -> bool:
    s = fix_thai(name)
    if not s:
        return False
    if has_title(s):
        return True
    if looks_like_company(s):
        return False
    toks = re.sub(rf"[^\w{THAI_RANGE} ]", " ", s).split()
    return 2 <= len(toks) <= 4 and not any(t.isdigit() for t in toks)
