"""Downloaders for public data.

Be polite: identify yourself in config.yaml (collect.user_agent), keep the delay, and read each
site's terms of use first. SET website endpoints are EXPERIMENTAL: they change without notice and
may refuse scripts. SETSMART exports or manual entry into the CSV templates are always valid.
"""
from __future__ import annotations

import io
import time

import pandas as pd
import requests

from .utils import LOG, SCHEMAS, ensure_dir, read_table, write_csv

LISTED_XLS = "https://www.set.or.th/dat/eod/listedcompany/static/listedCompanies_en_US.xls"
IND_KW = [("agro", "AGRO"), ("consumer", "CONSUMP"), ("financ", "FINCIAL"), ("industrial", "INDUS"),
          ("property", "PROPCON"), ("resource", "RESOURC"), ("service", "SERVICE"), ("tech", "TECH")]
SEC_KW = [("bank", "BANK"), ("insur", "INSUR"), ("financ", "FIN"), ("agribus", "AGRI"), ("food", "FOOD"),
          ("fashion", "FASHION"), ("home", "HOME"), ("personal", "PERSON"), ("auto", "AUTO"), ("machinery", "IMM"),
          ("paper", "PAPER"), ("petro", "PETRO"), ("packag", "PKG"), ("steel", "STEEL"),
          ("construction material", "CONMAT"), ("construction serv", "CONS"), ("reit", "PF&REIT"),
          ("property dev", "PROP"), ("energy", "ENERG"), ("mining", "MINE"), ("commerce", "COMM"),
          ("health", "HELTH"), ("media", "MEDIA"), ("professional", "PROF"), ("tourism", "TOURISM"),
          ("transport", "TRANS"), ("electronic", "ETRON"), ("information", "ICT")]


def _code(s, table) -> str:
    s = str(s).lower()
    return next((c for k, c in table if k in s), "")


def _session(cfg) -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": cfg["collect"]["user_agent"], "Accept-Language": "en,th;q=0.8"})
    return s


def _get(s, url, cfg, **kw):
    for attempt in range(3):
        try:
            r = s.get(url, timeout=cfg["collect"]["timeout"], **kw)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(5 * (attempt + 1))
                continue
            return r
        except requests.RequestException as e:
            LOG.warning("%s: %s", url, e)
            time.sleep(5 * (attempt + 1))
    return None


def gleif(cfg, limit=None) -> None:
    """All LEI records registered in Thailand, plus their direct and ultimate accounting parents."""
    base, s = cfg["collect"]["gleif_base"], _session(cfg)
    out = ensure_dir(cfg["_paths"]["raw"] / "gleif")
    ents, todo, page = [], [], 1
    while True:
        r = _get(s, f"{base}/lei-records", cfg, params={"filter[entity.legalAddress.country]": "TH",
                                                          "page[size]": 200, "page[number]": page})
        if r is None or r.status_code != 200:
            LOG.error("GLEIF page %d failed (%s)", page, getattr(r, "status_code", "no response"))
            break
        js = r.json()
        for d in js.get("data", []):
            a = d.get("attributes", {})
            e = a.get("entity", {})
            name = (e.get("legalName") or {}).get("name", "")
            ents.append(dict(lei=a.get("lei"), legal_name=name, country="TH", status=e.get("status", ""),
                             category=e.get("category", ""), legal_form=(e.get("legalForm") or {}).get("id", "")))
            for kind in ("direct-parent", "ultimate-parent"):
                links = ((d.get("relationships") or {}).get(kind) or {}).get("links", {})
                if "lei-record" in links:   # absent when the entity reports an exception instead
                    todo.append((a.get("lei"), name, kind, links["lei-record"]))
        last = js.get("meta", {}).get("pagination", {}).get("lastPage", page)
        LOG.info("GLEIF page %d/%d", page, last)
        if page >= last or (limit and len(ents) >= limit):
            break
        page += 1
        time.sleep(1.0)
    rels = []
    for child, cname, kind, url in todo:
        r = _get(s, url, cfg)
        time.sleep(1.0)
        if r is None or r.status_code != 200:
            continue
        pa = r.json().get("data", {}).get("attributes", {})
        rels.append(dict(child_lei=child, parent_lei=pa.get("lei", ""), relationship_type=kind, child_name=cname,
                         parent_name=((pa.get("entity") or {}).get("legalName") or {}).get("name", "")))
    write_csv(pd.DataFrame(ents, columns=SCHEMAS["gleif_entities"]), out / "th_entities.csv")
    write_csv(pd.DataFrame(rels, columns=SCHEMAS["gleif_relationships"]), out / "relationships.csv")
    LOG.info("GLEIF: %d Thai entities, %d parent relationships", len(ents), len(rels))


def set_universe(cfg) -> None:
    url = cfg["collect"].get("set_endpoints", {}).get("listed_xls", LISTED_XLS)
    r = _get(_session(cfg), url, cfg)
    if r is None or r.status_code != 200 or len(r.content) < 1000:
        LOG.error("Could not download the SET company list (%s). Download 'listed companies' (Excel) from the SET "
                  "website by hand and fill data/raw/universe/listed_companies.csv.", getattr(r, "status_code", "-"))
        return
    df = None
    for reader in (lambda b: pd.read_excel(io.BytesIO(b), header=None),
                   lambda b: pd.read_html(io.BytesIO(b), header=None)[0]):
        try:
            df = reader(r.content)
            break
        except Exception:  # noqa: BLE001 - the file is sometimes HTML disguised as .xls
            continue
    hdr = None if df is None else next((i for i in range(min(15, len(df)))
                                        if df.iloc[i].astype(str).str.strip().str.lower().eq("symbol").any()), None)
    if hdr is None:
        LOG.error("Unexpected format of the SET list; fill listed_companies.csv by hand.")
        return
    df.columns = df.iloc[hdr].astype(str).str.strip().str.lower()
    df = df.iloc[hdr + 1:].dropna(subset=["symbol"])
    out = pd.DataFrame({"ticker": df["symbol"].astype(str).str.strip(), "name_en": df.get("company", ""),
                        "name_th": "", "market": df.get("market", ""),
                        "industry": df.get("industry", pd.Series("", index=df.index)).map(lambda x: _code(x, IND_KW)),
                        "sector": df.get("sector", pd.Series("", index=df.index)).map(lambda x: _code(x, SEC_KW)),
                        "market_cap": ""})
    p = write_csv(out, ensure_dir(cfg["_paths"]["raw"] / "universe") / "set_listed.csv")
    LOG.info("SET universe: %d companies -> %s (add market_cap from SETSMART for value weights)", len(out), p)


def _parse_holders(js, tk) -> list[dict]:
    found, date, stack = [], "", [js]
    while stack:
        o = stack.pop()
        if isinstance(o, dict):
            for k, v in o.items():
                if not date and "date" in k.lower() and isinstance(v, str):
                    date = v[:10]
                stack.append(v)
        elif isinstance(o, list):
            if o and isinstance(o[0], dict) and any("name" in k.lower() for k in o[0]) and \
                    any("percent" in k.lower() for k in o[0]):
                found = o
            else:
                stack.extend(o)
    rows = []
    for i, h in enumerate(found, 1):
        name = next((h[k] for k in h if "name" in k.lower()), "")
        p = next((h[k] for k in h if "percent" in k.lower()), "")
        sh = next((h[k] for k in h if ("share" in k.lower() or "number" in k.lower()) and "percent" not in k.lower()), "")
        rows.append(dict(ticker=tk, as_of=date, rank=i, holder_name=name, shares=sh, pct=p, source="set_website"))
    return rows


def set_shareholders(cfg, tickers=None, lang="en", limit=None) -> None:
    """EXPERIMENTAL: top-10 shareholders from the SET website's JSON endpoint (see config.yaml)."""
    tpl = cfg["collect"].get("set_endpoints", {}).get("shareholders")
    if not tpl:
        LOG.error("collect.set_endpoints.shareholders is not set in config.yaml")
        return
    if not tickers:
        uni = pd.concat([read_table(p, "universe") for p in (cfg["_paths"]["raw"] / "universe").glob("*.csv")] or
                        [pd.DataFrame(columns=["ticker"])])
        tickers = sorted(set(uni["ticker"].str.strip()) - {""})
    tickers = tickers[:limit] if limit else tickers
    s = _session(cfg)
    s.headers.update({"Referer": "https://www.set.or.th/", "Accept": "application/json"})
    rows, fails = [], 0
    for tk in tickers:
        r = _get(s, tpl.format(symbol=tk, lang=lang), cfg)
        if r is None or r.status_code != 200 or "json" not in r.headers.get("content-type", ""):
            fails += 1
            if fails >= 5 and not rows:
                LOG.error("The SET endpoint does not answer scripts (status %s). Use a SETSMART export or fill "
                          "shareholders/top10_manual.csv; see README.", getattr(r, "status_code", "-"))
                break
            continue
        rows += _parse_holders(r.json(), tk)
        time.sleep(cfg["collect"]["delay_seconds"])
    if rows:
        write_csv(pd.DataFrame(rows, columns=SCHEMAS["top10"]),
                  ensure_dir(cfg["_paths"]["raw"] / "shareholders") / "set_top10.csv")
    LOG.info("SET shareholders: %d rows for %d tickers (%d failures)", len(rows), len(tickers), fails)


def documents(cfg, limit=None) -> None:
    """Download PDFs listed in data/manual/document_urls.csv (doc_type: one_report | pillar3 | boj5)."""
    P = cfg["_paths"]
    urls = read_table(P["manual"] / "document_urls.csv", "document_urls")
    s, n = _session(cfg), 0
    for r in urls.itertuples(index=False):
        if not r.url.strip():
            continue
        folder = ensure_dir(P["raw"] / "documents" / (r.doc_type.strip() or "one_report"))
        stem = "_".join(x for x in (r.ticker.strip().upper(), r.year.strip(), r.lang.strip().lower()) if x)
        out = folder / f"{stem or f'doc{n}'}.pdf"
        if out.exists():
            continue
        resp = _get(s, r.url.strip(), cfg)
        if resp is None or resp.status_code != 200 or not resp.content.startswith(b"%PDF"):
            LOG.warning("not a PDF (download by hand into %s): %s", folder, r.url)
            continue
        out.write_bytes(resp.content)
        n += 1
        LOG.info("saved %s (%.1f MB)", out.name, len(resp.content) / 1e6)
        if limit and n >= limit:
            break
        time.sleep(cfg["collect"]["delay_seconds"])
    LOG.info("documents: %d downloaded", n)
