"""Kalshi public-API client. Fetches markets for our 5 season-outlook series.

No auth needed for market data. When a series has no live event for the
configured season year, returns an empty DataFrame for that outcome.
"""
from __future__ import annotations

import json
import time
from typing import Iterable

import pandas as pd
import requests

from .config import load_config


def _get(base: str, path: str, params: dict, ua: str, timeout: int) -> dict:
    backoff = 1.0
    for attempt in range(5):
        r = requests.get(
            f"{base}{path}", params=params, headers={"User-Agent": ua}, timeout=timeout
        )
        if r.status_code == 429:
            time.sleep(backoff)
            backoff *= 2
            continue
        r.raise_for_status()
        return json.loads(r.text, strict=False)
    r.raise_for_status()
    return json.loads(r.text, strict=False)


def fetch_event_markets(series_ticker: str, year: str, cfg: dict) -> list[dict]:
    """Return raw market dicts for {series}-{year}, or [] if none exist."""
    k = cfg["kalshi"]
    event_ticker = f"{series_ticker}-{year}"
    d = _get(
        k["base_url"],
        "/markets",
        {"event_ticker": event_ticker, "limit": 200},
        cfg["http"]["user_agent"],
        cfg["http"]["timeout_seconds"],
    )
    return d.get("markets") or []


def _ticker_team_suffix(ticker: str, event_ticker: str) -> str:
    prefix = event_ticker + "-"
    return ticker[len(prefix):] if ticker.startswith(prefix) else ticker


def _to_float(x):
    """Parse Kalshi's `*_dollars` string fields (e.g., '0.2700') to float."""
    if x in (None, ""):
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def markets_to_df(outcome: str, series_ticker: str, year: str, markets: list[dict]) -> pd.DataFrame:
    event_ticker = f"{series_ticker}-{year}"
    rows = []
    for m in markets:
        rows.append({
            "outcome": outcome,
            "series_ticker": series_ticker,
            "event_ticker": event_ticker,
            "kalshi_ticker": m.get("ticker"),
            "kalshi_team_suffix": _ticker_team_suffix(m.get("ticker", ""), event_ticker),
            "kalshi_team_label": m.get("yes_sub_title") or m.get("subtitle"),
            # Kalshi exposes both integer-cent and decimal-dollar fields; the
            # *_dollars fields are populated for season-outlook markets while
            # the integer ones often return null. Prefer dollars and fall back.
            "yes_bid":    _to_float(m.get("yes_bid_dollars"))    or m.get("yes_bid"),
            "yes_ask":    _to_float(m.get("yes_ask_dollars"))    or m.get("yes_ask"),
            "last_price": _to_float(m.get("last_price_dollars")) or m.get("last_price"),
            "status": m.get("status"),
            "volume": _to_float(m.get("volume_fp")) or m.get("volume"),
            "open_interest": _to_float(m.get("open_interest_fp")) or m.get("open_interest"),
        })
    return pd.DataFrame(rows)


def fetch_all(cfg: dict | None = None) -> pd.DataFrame:
    """One DataFrame per outcome stacked together. An outcome may pull from
    multiple Kalshi series (e.g. divisions = 6 series, pennant = 2 series).
    Series with no live event are silently skipped.
    """
    cfg = cfg or load_config()
    year = cfg["kalshi"]["season_year"]
    frames = []
    for outcome, series_list in cfg["kalshi"]["outcomes"].items():
        for series in series_list:
            markets = fetch_event_markets(series, year, cfg)
            if markets:
                frames.append(markets_to_df(outcome, series, year, markets))
            time.sleep(0.4)
    if not frames:
        return pd.DataFrame(columns=[
            "outcome","series_ticker","event_ticker","kalshi_ticker",
            "kalshi_team_suffix","kalshi_team_label","yes_bid","yes_ask",
            "last_price","status","volume","open_interest",
        ])
    return pd.concat(frames, ignore_index=True)
