"""Fetch FanGraphs playoff-odds JSON for one projection source."""
from __future__ import annotations

import json
import re
from typing import Iterable

import pandas as pd
import requests

from .config import load_config

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.+?)</script>', re.S
)


def _fetch_html(source: str, cfg: dict) -> str:
    url = f"{cfg['fangraphs']['base_url']}/{source}/{cfg['fangraphs']['view']}"
    headers = {"User-Agent": cfg["http"]["user_agent"]}
    r = requests.get(url, headers=headers, timeout=cfg["http"]["timeout_seconds"])
    r.raise_for_status()
    return r.text


def _extract_team_rows(html: str) -> list[dict]:
    m = _NEXT_DATA_RE.search(html)
    if not m:
        raise RuntimeError("__NEXT_DATA__ block not found")
    data = json.loads(m.group(1))
    queries = data["props"]["pageProps"]["dehydratedState"]["queries"]
    for q in queries:
        qd = q.get("state", {}).get("data")
        if isinstance(qd, list) and qd and isinstance(qd[0], dict) and "endData" in qd[0]:
            return qd
    raise RuntimeError("team-rows query not found in __NEXT_DATA__")


def parse_source(source: str, cfg: dict | None = None) -> pd.DataFrame:
    cfg = cfg or load_config()
    rows = _extract_team_rows(_fetch_html(source, cfg))
    outcomes = cfg["fangraphs"]["outcomes"]
    records = []
    for r in rows:
        end = r.get("endData", {}) or {}
        rec = {
            "team_id":   r.get("teamId"),
            "team_abbr": r.get("abbName"),
            "team_name": r.get("shortName"),
            "league":    r.get("league"),
            "division":  r.get("division"),
            "source":    source,
        }
        for outcome_key, fg_field in outcomes.items():
            rec[outcome_key] = end.get(fg_field)
        records.append(rec)
    df = pd.DataFrame(records)
    df = df.sort_values(["league", "division", "team_abbr"]).reset_index(drop=True)
    return df


def fetch_all(cfg: dict | None = None) -> dict[str, pd.DataFrame]:
    cfg = cfg or load_config()
    return {src: parse_source(src, cfg) for src in cfg["fangraphs"]["sources"]}
