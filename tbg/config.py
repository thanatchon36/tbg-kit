"""Configuration: built-in defaults, YAML overrides, and resolved workspace paths."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

DEFAULTS: dict[str, Any] = {
    "project": {
        "title": "Mapping Thailand's Business Groups",
        "short_title": "Thai Business Groups",
        "authors": "",
        "affiliation": "",
        "email": "",
        "keywords": [],
        "data_year": None,
        "as_of": None,
    },
    "workspace": "work",
    "seeds_file": "seeds/business_groups.yaml",
    "ownership": {
        "thresholds": [0.10, 0.20, 0.50],
        "group_threshold": 0.20,
        "family_aggregation": "surname",
        "non_candidate_types": ["nvdr", "custodian", "fund", "institutional", "unknown"],
        "state_investors_as_state": False,
        "min_store_cr": 0.005,
        "max_iter": 500,
        "tol": 1.0e-10,
        "edge_source_priority": ["dbd_boj5", "set_top10", "one_report_direct", "manual",
                                 "pillar3", "one_report_effective"],
        "pct_tolerance": 1.0,
        "scale_over_100": True,
        "link_min_pct": 1.0,
        "split_groups_under": ["state", "crown"],
    },
    "resolution": {"auto_merge_score": 95, "review_score": 88},
    "fi": {"amc_brand_map": {}},
    "llm": {
        "model": "claude-sonnet-5-5",
        "max_tokens": 16000,
        "input_mode": "auto",
        "max_pages_per_request": 20,
        "context_pages": 1,
        "max_candidate_pages": 24,
    },
    "collect": {
        "user_agent": "tbg-research/0.1 (academic research)",
        "delay_seconds": 2.5,
        "timeout": 60,
        "set_endpoints": {},
        "gleif_base": "https://api.gleif.org/api/v1",
    },
    "viz": {"min_group_size": 3, "label_top_groups": 40, "dpi": 300,
            "poster_inches": 24, "paper_inches": 6.5},
    "paper": {"compile": True, "engine": "auto", "arxiv_bundle": True},
}


def _deep_update(base: dict, upd: dict) -> dict:
    for k, v in (upd or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_update(base[k], v)
        else:
            base[k] = v
    return base


def load_config(path: str | Path | None = "config.yaml", workspace: str | None = None) -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    root = Path.cwd()
    if path:
        p = Path(path)
        if p.exists():
            root = p.resolve().parent
            with p.open(encoding="utf-8") as fh:
                _deep_update(cfg, yaml.safe_load(fh) or {})
    if workspace:
        cfg["workspace"] = workspace
    ws = (root / cfg["workspace"]).resolve()
    cfg["_paths"] = {
        "root": root,
        "ws": ws,
        "raw": ws / "data" / "raw",
        "manual": ws / "data" / "manual",
        "interim": ws / "data" / "interim",
        "processed": ws / "data" / "processed",
        "review": ws / "review",
        "results": ws / "results",
        "figures": ws / "figures",
        "paper": ws / "paper",
        "explorer": ws / "explorer",
        "prompts": root / "prompts",
        "paper_src": root / "paper",
        "templates": root / "templates",
        "seeds": root / cfg["seeds_file"],
    }
    return cfg
