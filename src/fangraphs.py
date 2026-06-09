"""Fetch FanGraphs playoff-odds JSON for one projection source."""
from __future__ import annotations

import json
import logging
import re
import time

import pandas as pd
from curl_cffi import requests as cffi_requests

from .config import load_config

logger = logging.getLogger(__name__)

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.+?)</script>', re.S
)

# FanGraphs sits behind a Cloudflare JS/TLS-fingerprint challenge: plain
# requests/curl get a 403 "Just a moment..." page, while a real browser passes
# transparently. curl_cffi impersonates a browser's TLS fingerprint and clears
# the challenge. We rotate impersonation targets across retries because a given
# target's fingerprint can age out and start returning 403 (older chrome builds
# already do); a fresh target then gets through.
_IMPERSONATE_TARGETS = ["chrome", "safari17_0", "chrome131", "chrome123"]


def _fetch_html(source: str, cfg: dict) -> str:
    """GET the page via a browser-impersonating client, with retry + backoff.

    Any non-200 (the Cloudflare challenge returns 403) or network error is
    retried, rotating the impersonation fingerprint each attempt. A single
    blip — or a stale fingerprint — must not abort the whole run and leave the
    team-side projections silently stale.
    """
    url = f"{cfg['fangraphs']['base_url']}/{source}/{cfg['fangraphs']['view']}"
    http = cfg["http"]
    timeout = http["timeout_seconds"]
    attempts = int(http.get("max_retries", 5))
    backoff = float(http.get("retry_backoff_seconds", 1.0))
    targets = http.get("impersonate_targets") or _IMPERSONATE_TARGETS

    last_err: Exception | None = None
    for attempt in range(1, attempts + 1):
        target = targets[(attempt - 1) % len(targets)]
        try:
            r = cffi_requests.get(url, impersonate=target, timeout=timeout)
            if r.status_code == 200:
                return r.text
            # 403 = Cloudflare challenge not cleared by this fingerprint; 429/5xx
            # are transient. Either way, retry with the next impersonation target.
            last_err = RuntimeError(f"HTTP {r.status_code} (impersonate={target})")
        except Exception as e:  # noqa: BLE001 — curl_cffi network/transport errors
            last_err = e

        if attempt < attempts:
            logger.warning(
                "FanGraphs '%s' fetch failed (attempt %d/%d, impersonate=%s): %s "
                "— retrying in %.1fs",
                source, attempt, attempts, target, last_err, backoff,
            )
            time.sleep(backoff)
            backoff *= 2

    raise RuntimeError(
        f"FanGraphs fetch failed for '{source}' after {attempts} attempts"
    ) from last_err


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
    """Fetch every configured source, tolerating individual failures.

    A source that still fails after all retries is skipped rather than
    aborting the run, so the team-side projections keep updating on a
    partial outage. We require at least ``fangraphs.min_sources`` to
    succeed — short of that we raise instead of publishing a too-thin
    aggregate (and never silently fall back to stale projections).
    """
    cfg = cfg or load_config()
    sources = cfg["fangraphs"]["sources"]
    min_sources = int(cfg["fangraphs"].get("min_sources", len(sources)))

    per_source: dict[str, pd.DataFrame] = {}
    failed: dict[str, str] = {}
    for src in sources:
        try:
            per_source[src] = parse_source(src, cfg)
        except Exception as e:  # network error after retries, or parse failure
            failed[src] = str(e)
            logger.error("FanGraphs source '%s' unavailable, skipping: %s", src, e)

    if len(per_source) < min_sources:
        raise RuntimeError(
            f"Only {len(per_source)}/{len(sources)} FanGraphs sources fetched "
            f"(need >= {min_sources}); failures: {failed}. "
            "Refusing to publish a partial team-odds aggregate."
        )

    if failed:
        logger.warning(
            "Proceeding with %d/%d FanGraphs sources; missing: %s",
            len(per_source), len(sources), ", ".join(failed),
        )
    return per_source
