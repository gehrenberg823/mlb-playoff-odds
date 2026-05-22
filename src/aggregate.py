"""Combine per-source FanGraphs DataFrames into a single mean-aggregated table."""
from __future__ import annotations

import pandas as pd

from .config import load_config

KEY_COLS = ["team_id", "team_abbr", "team_name", "league", "division"]


def aggregate(per_source: dict[str, pd.DataFrame], cfg: dict | None = None) -> pd.DataFrame:
    cfg = cfg or load_config()
    outcomes = list(cfg["fangraphs"]["outcomes"].keys())

    combined = pd.concat(per_source.values(), ignore_index=True)
    n_sources_seen = combined.groupby("team_abbr")["source"].nunique().rename("n_sources")

    agg = (
        combined.groupby(KEY_COLS, as_index=False)[outcomes]
        .mean()
        .merge(n_sources_seen, on="team_abbr")
        .sort_values(["league", "division", "team_abbr"])
        .reset_index(drop=True)
    )
    return agg
