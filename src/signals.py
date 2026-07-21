"""Build the fair-vs-market table.

For each outcome and team, one row with:
  - aggregated fair probability (mean of FanGraphs sources)
  - Kalshi yes_bid / yes_ask / last_price (NaN if no market exists)
  - implied mid (mean of bid/ask when both present)
  - fair_minus_mid (fair_prob - implied_mid, useful sanity column)
"""
from __future__ import annotations

import pandas as pd

from .config import load_config


def _kalshi_by_outcome(kalshi_df: pd.DataFrame, outcome: str) -> pd.DataFrame:
    if kalshi_df.empty:
        cols = ["kalshi_team_suffix", "kalshi_ticker", "yes_bid", "yes_ask", "last_price"]
        return pd.DataFrame(columns=cols)
    return kalshi_df[kalshi_df.outcome == outcome][
        ["kalshi_team_suffix", "kalshi_ticker", "yes_bid", "yes_ask", "last_price"]
    ].copy()


def build_report(
    aggregated: pd.DataFrame,
    kalshi_df: pd.DataFrame,
    team_map: pd.DataFrame,
    cfg: dict | None = None,
    pinnacle_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    cfg = cfg or load_config()
    outcomes = list(cfg["fangraphs"]["outcomes"].keys())

    agg = aggregated.merge(
        team_map[["fg_abbr", "kalshi_abbr"]],
        left_on="team_abbr",
        right_on="fg_abbr",
        how="left",
    ).drop(columns=["fg_abbr"])

    rows = []
    for outcome in outcomes:
        kal = _kalshi_by_outcome(kalshi_df, outcome)

        cols = ["team_id","team_abbr","team_name","league","division",
                "kalshi_abbr", outcome, "n_sources"]
        ren = {outcome: "fair_prob"}
        # carry source min/max through when the aggregate provides them
        if f"{outcome}_min" in agg.columns:
            cols += [f"{outcome}_min", f"{outcome}_max"]
            ren[f"{outcome}_min"] = "fair_min"
            ren[f"{outcome}_max"] = "fair_max"
        block = agg[cols].rename(columns=ren)
        block.insert(0, "outcome", outcome)

        merged = block.merge(
            kal, left_on="kalshi_abbr", right_on="kalshi_team_suffix", how="left"
        ).drop(columns=["kalshi_team_suffix"])

        rows.append(merged)

    report = pd.concat(rows, ignore_index=True)

    # Independent sharp-market anchor (devigged Pinnacle futures), where offered.
    if pinnacle_df is not None and not pinnacle_df.empty:
        report = report.merge(pinnacle_df, on=["outcome", "team_abbr"], how="left")
    else:
        report["pinnacle_prob"] = pd.NA

    # Kalshi's *_dollars fields are already decimals in [0,1] (e.g. "0.27" = 27¢).
    for col in ("yes_bid", "yes_ask", "last_price", "pinnacle_prob"):
        report[col] = pd.to_numeric(report[col], errors="coerce")

    report["implied_mid"] = report[["yes_bid", "yes_ask"]].mean(axis=1)
    report["fair_minus_mid"] = report["fair_prob"] - report["implied_mid"]

    col_order = [
        "outcome","team_abbr","team_name","league","division",
        "fair_prob","n_sources","pinnacle_prob",
        "kalshi_ticker","yes_bid","yes_ask","last_price","implied_mid","fair_minus_mid",
    ]
    if "fair_min" in report.columns:
        col_order[6:6] = ["fair_min", "fair_max"]
    return report[col_order].sort_values(["outcome", "league", "division", "team_abbr"]).reset_index(drop=True)
