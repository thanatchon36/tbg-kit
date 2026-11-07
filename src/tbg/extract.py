"""Find relevant pages in PDFs and extract tables with Claude.

1. `extract pages`  scores every page by keywords and writes interim/pages_<kind>.csv
   (edit the `pages` column by hand if a report needs other pages).
2. `extract run`    sends the pages as text or, when text extraction is poor, as a PDF slice.
   `--batch` uses the Message Batches API (asynchronous, lower cost); collect with `extract collect-batch`.
Responses are cached in interim/llm/<kind>/ so re-runs only send what is missing.
Requires the ANTHROPIC_API_KEY environment variable. Check model names and limits at docs.claude.com.
"""
from __future__ import annotations

import base64
import io
import json
import re
from pathlib import Path

import pandas as pd

from .names import fix_thai
from .utils import LOG, SCHEMAS, ensure_dir, read_json, to_float, write_csv, write_json

KINDS = {
    "subsidiaries": dict(docs="one_report", out=("subsidiaries", "llm_subsidiaries.csv"), schema="subsidiaries",
                         kw=["โครงสร้างการถือหุ้น", "บริษัทย่อย", "บริษัทร่วม", "การร่วมค้า", "สัดส่วนการถือหุ้น",
                             "subsidiar", "associate", "joint venture", "shareholding structure",
                             "ownership interest", "investments in"]),
    "shareholders": dict(docs="one_report", out=("shareholders", "llm_top10.csv"), schema="top10",
                         kw=["ผู้ถือหุ้นรายใหญ่", "ผู้ถือหุ้น 10 ราย", "major shareholder", "top 10 shareholders",
                             "จำนวนหุ้น", "number of shares"]),
    "directors": dict(docs="one_report", out=("directors", "llm_directors.csv"), schema="directors",
                      kw=["คณะกรรมการบริษัท", "รายชื่อกรรมการ", "board of directors", "กรรมการอิสระ",
                          "independent director"]),
    "pillar3": dict(docs="pillar3", out=("fi", "pillar3_llm.csv"), schema="pillar3",
                    kw=["กลุ่มธุรกิจทางการเงิน", "financial business group", "financial group", "consolidat",
                        "subsidiar"]),
    "boj5": dict(docs="boj5", out=("dbd", "boj5_llm.csv"), schema="boj5",
                 kw=["ผู้ถือหุ้น", "บัญชีรายชื่อผู้ถือหุ้น", "shareholder", "จำนวนหุ้น"]),
}
MAX_BATCH_BYTES = 200_000_000   # keep each batch below the API size limit (verify current limits)


def page_texts(pdf: Path) -> list[str]:
    try:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(str(pdf))
        out = []
        for i in range(len(doc)):
            tp = doc[i].get_textpage()
            out.append(fix_thai(tp.get_text_range()))
            tp.close()
        doc.close()
        return out
    except Exception as e:  # noqa: BLE001
        LOG.debug("pypdfium2 failed on %s (%s); using pypdf", pdf.name, e)
        from pypdf import PdfReader
        return [fix_thai(p.extract_text() or "") for p in PdfReader(str(pdf)).pages]


def _score(t: str, kw) -> float:
    tl = t.lower()
    hits = sum(tl.count(k.lower()) for k in kw)
    pcts = len(re.findall(r"\d{1,3}(?:\.\d+)?\s?%", t)) + tl.count("ร้อยละ")
    return hits * 2 + min(pcts, 40) * 0.5


def find_pages(cfg, kind) -> pd.DataFrame:
    k, P, L = KINDS[kind], cfg["_paths"], cfg["llm"]
    docs = sorted((P["raw"] / "documents" / k["docs"]).glob("*.pdf"))
    rows = []
    for pdf in docs:
        texts = page_texts(pdf)
        n = len(texts)
        if kind == "boj5" or n <= L["max_pages_per_request"] // 2:
            pages = list(range(n))
        else:
            ranked = sorted(((_score(t, k["kw"]), i) for i, t in enumerate(texts)), reverse=True)
            sel = set()
            for s, i in ranked[: L["max_candidate_pages"]]:
                if s >= 4:
                    sel.update(range(max(0, i - L["context_pages"]), min(n, i + L["context_pages"] + 1)))
            pages = sorted(sel)[: L["max_candidate_pages"]]
        chars = sum(len(texts[i]) for i in pages)
        poor = chars < 150 * max(1, len(pages)) or sum(texts[i].count("\ufffd") for i in pages) > 20
        rows.append(dict(doc=str(pdf.relative_to(P["raw"])), n_pages=n, pages=" ".join(str(i + 1) for i in pages),
                         n_selected=len(pages), text_quality="poor" if poor else "ok"))
    df = pd.DataFrame(rows, columns=["doc", "n_pages", "pages", "n_selected", "text_quality"])
    write_csv(df, P["interim"] / f"pages_{kind}.csv")
    LOG.info("%s: %d documents, %d pages selected (%d with poor text)", kind, len(df), int(df["n_selected"].sum()),
             int((df["text_quality"] == "poor").sum()))
    return df


def _meta(doc: str, kind: str) -> dict:
    stem = Path(doc).stem
    parts = stem.split("_")
    return {"doc": doc, "stem": stem, "ticker": parts[0].upper() if kind != "boj5" else "",
            "year": next((p for p in parts if re.fullmatch(r"(19|20)\d\d", p)), ""),
            "company": stem if kind == "boj5" else ""}


def _pdf_slice(path: Path, pages: list[int]) -> bytes:
    from pypdf import PdfReader, PdfWriter
    r, w = PdfReader(str(path)), PdfWriter()
    for p in pages:
        w.add_page(r.pages[p - 1])
    b = io.BytesIO()
    w.write(b)
    return b.getvalue()


def _system(cfg, kind) -> str:
    pr = cfg["_paths"]["prompts"]
    return (pr / "extract_common.md").read_text(encoding="utf-8") + "\n\n" + \
        (pr / f"extract_{kind}.md").read_text(encoding="utf-8")


def _requests(cfg, kind):
    P, L = cfg["_paths"], cfg["llm"]
    pages = pd.read_csv(P["interim"] / f"pages_{kind}.csv", dtype=str, keep_default_na=False, encoding="utf-8-sig")
    system, cache = _system(cfg, kind), ensure_dir(P["interim"] / "llm" / kind)
    for r in pages.itertuples(index=False):
        pg = [int(x) for x in r.pages.split()]
        if not pg:
            continue
        meta, src, texts = _meta(r.doc, kind), P["raw"] / r.doc, None
        mode = L["input_mode"] if L["input_mode"] != "auto" else ("pdf" if r.text_quality == "poor" else "text")
        step = L["max_pages_per_request"]
        for j in range(0, len(pg), step):
            ch = pg[j:j + step]
            cid = re.sub(r"[^A-Za-z0-9_-]", "_", meta["stem"])[:50] + f"__{j // step}"
            if (cache / f"{cid}.json").exists():
                continue
            if mode == "pdf":
                block = {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                                        "data": base64.b64encode(_pdf_slice(src, ch)).decode()}}
                where = f"The attached PDF contains original pages {', '.join(map(str, ch))} in that order."
            else:
                texts = texts or page_texts(src)
                block = {"type": "text", "text": "\n\n".join(f'<page number="{p}">\n{texts[p - 1]}\n</page>' for p in ch)}
                where = "Page text is wrapped in <page> tags with original page numbers."
            instr = (f"Document file: {meta['doc']}\nReporting entity (from file name): "
                     f"{meta['ticker'] or meta['company'] or 'unknown'}\nYear (from file name): "
                     f"{meta['year'] or 'unknown'}\n{where}\nReturn only the JSON object.")
            params = {"model": L["model"], "max_tokens": L["max_tokens"], "system": system,
                      "messages": [{"role": "user", "content": [block, {"type": "text", "text": instr}]}]}
            yield cid, {**meta, "pages": ch, "mode": mode}, params


def parse_json(text: str):
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j <= i:
        return None, "no JSON object in response"
    err = ""
    for cand in (t[i:j + 1], re.sub(r",\s*([}\]])", r"\1", t[i:j + 1])):
        try:
            return json.loads(cand), None
        except json.JSONDecodeError as e:
            err = str(e)
    return None, err


def _save(cache: Path, cid: str, meta: dict, text: str) -> None:
    parsed, err = parse_json(text)
    write_json({"meta": meta, "text": text, "parsed": parsed, "error": err}, cache / f"{cid}.json")


def run(cfg, kind, batch=False, limit=None, dry_run=False) -> None:
    P = cfg["_paths"]
    if not (P["interim"] / f"pages_{kind}.csv").exists():
        find_pages(cfg, kind)
    reqs = list(_requests(cfg, kind))
    reqs = reqs[:limit] if limit else reqs
    LOG.info("%s: %d requests to send", kind, len(reqs))
    if dry_run or not reqs:
        for cid, meta, p in reqs[:5]:
            LOG.info("  %s pages %s (%s mode, %.0f kB)", cid, meta["pages"], meta["mode"], len(json.dumps(p)) / 1e3)
        return
    import anthropic
    client, cache = anthropic.Anthropic(), P["interim"] / "llm" / kind
    if batch:
        part, size = [], 0
        for i, item in enumerate(reqs):
            part.append(item)
            size += len(json.dumps(item[2]))
            if size > MAX_BATCH_BYTES or i == len(reqs) - 1:
                b = client.messages.batches.create(requests=[{"custom_id": c, "params": p} for c, _, p in part])
                write_json({"batch_id": b.id, "meta": {c: m for c, m, _ in part}}, cache / f"batch_{b.id}.json")
                LOG.info("submitted batch %s (%d requests). Later: python -m tbg extract collect-batch --kind %s",
                         b.id, len(part), kind)
                part, size = [], 0
        return
    for n, (cid, meta, params) in enumerate(reqs, 1):
        try:
            resp = client.messages.create(**params)
            _save(cache, cid, meta, "".join(b.text for b in resp.content if getattr(b, "type", "") == "text"))
            LOG.info("[%d/%d] %s", n, len(reqs), cid)
        except Exception as e:  # noqa: BLE001
            LOG.error("%s: %s", cid, e)
    assemble(cfg, kind)


def collect_batch(cfg, kind) -> None:
    import anthropic
    client, cache = anthropic.Anthropic(), cfg["_paths"]["interim"] / "llm" / kind
    for bf in sorted(cache.glob("batch_*.json")):
        info = read_json(bf)
        if info.get("done"):
            continue
        b = client.messages.batches.retrieve(info["batch_id"])
        if b.processing_status != "ended":
            LOG.info("batch %s is still %s", info["batch_id"], b.processing_status)
            continue
        ok = 0
        for res in client.messages.batches.results(info["batch_id"]):
            if res.result.type == "succeeded":
                text = "".join(c.text for c in res.result.message.content if getattr(c, "type", "") == "text")
                _save(cache, res.custom_id, info["meta"].get(res.custom_id, {}), text)
                ok += 1
            else:
                LOG.warning("%s: %s", res.custom_id, res.result.type)
        info["done"] = True
        write_json(info, bf)
        LOG.info("batch %s: %d results saved", info["batch_id"], ok)
    assemble(cfg, kind)


def _row(kind, r, meta, doc) -> dict:
    def g(*ks):
        return next((str(r[x]).strip() for x in ks if r.get(x) not in (None, "")), "")
    base = {"confidence": g("confidence"), "note": g("note", "group_note")}
    if kind == "subsidiaries":
        return dict(reporting_ticker=meta.get("ticker", ""), fiscal_year=doc.get("fiscal_year") or meta.get("year", ""),
                    entity_name=g("entity_name"), entity_name_alt=g("entity_name_alt"), relationship=g("relationship"),
                    immediate_parent=g("immediate_parent"), pct_direct=g("pct_direct"), pct_effective=g("pct_effective"),
                    country=g("country"), business=g("business"), sector="", source_doc=meta.get("doc", ""),
                    page=g("page"), **base)
    if kind == "shareholders":
        return dict(ticker=meta.get("ticker", ""), as_of=doc.get("as_of", ""), rank=g("rank"),
                    holder_name=g("holder_name"), shares=g("shares"), pct=g("pct"), source=meta.get("doc", ""), **base)
    if kind == "directors":
        return dict(ticker=meta.get("ticker", ""), entity_name="", person_name=g("person_name"), position=g("position"),
                    as_of=doc.get("as_of", "") or meta.get("year", ""), source=meta.get("doc", ""), **base)
    if kind == "pillar3":
        return dict(bank_ticker=meta.get("ticker", ""), as_of=doc.get("as_of", "") or meta.get("year", ""),
                    entity_name=g("entity_name"), relationship=g("relationship"), pct=g("pct"), country=g("country"),
                    business=g("business"), source_doc=meta.get("doc", ""), page=g("page"), **base)
    return dict(company_name=doc.get("company_name") or meta.get("company", ""), juristic_id=doc.get("juristic_id", ""),
                as_of=doc.get("as_of", ""), holder_name=g("holder_name"), shares=g("shares"), pct=g("pct"),
                source_doc=meta.get("doc", ""), **base)


def assemble(cfg, kind) -> pd.DataFrame:
    k, P = KINDS[kind], cfg["_paths"]
    rows, issues = [], []
    for f in sorted((P["interim"] / "llm" / kind).glob("*.json")):
        if f.name.startswith("batch_"):
            continue
        js = read_json(f, {})
        doc = js.get("parsed") or {}
        if js.get("error"):
            issues.append(dict(file=f.name, issue="parse_error", detail=js["error"]))
            continue
        rows += [_row(kind, r, js.get("meta", {}), doc) for r in doc.get("rows", []) if isinstance(r, dict)]
        if doc.get("document_notes"):
            issues.append(dict(file=f.name, issue="note", detail=doc["document_notes"]))
    cols = SCHEMAS[k["schema"]] + [c for c in ("confidence", "note") if c not in SCHEMAS[k["schema"]]]
    df = pd.DataFrame(rows, columns=cols)
    folder, name = k["out"]
    write_csv(df, ensure_dir(P["raw"] / folder) / name)
    low = df[df["confidence"].map(to_float).fillna(0) < 0.8]
    write_csv(low, P["review"] / f"llm_{kind}_check.csv")
    write_csv(pd.DataFrame(issues, columns=["file", "issue", "detail"]), P["review"] / f"llm_{kind}_issues.csv")
    LOG.info("%s: %d rows -> raw/%s/%s; %d rows to check by hand; %d issues", kind, len(df), folder, name,
             len(low), len(issues))
    return df
