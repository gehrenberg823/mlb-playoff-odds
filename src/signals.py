"""Build the fair-vs-market table.

For each outcome and team, one row with:
  - aggregated fair probability (mean of FanGraphs sources)
  - Kalshi yes_bid / yes_ask / last_price (NaN if no market exists)
  - implied mid (mean of bid/ask when both present)
  - fair_minus_mid (fair_prob - implied_mid, useful sanity column)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import load_config


def _kalshi_by_outcome(kalshi_df: pd.DataFrame, outcome: str) -> pd.DataFrame:
    if kalshi_df.empty:
        cols = ["kalshi_team_suffix", "kalshi_ticker", "yes_bid", "yes_ask", "last_price"]
        return pd.DataFrame(columns=cols)
    return kalshi_df[kalshi_df.outcome == outcome][
        ["kalshi_team_suffix", "kalshi_ticker", "yes_bid", "yes_ask", "last_price"]
    ].copy()


# Blend weights (logit space). Within the market anchor Pinnacle leads
# (sharpest futures book); the FG-vs-market 70/30 split is the user's
# original choice, unchanged when FanDuel was added 2026-08-02.
PINN_W, FD_W = 0.60, 0.40
FG_W, MKT_W = 0.70, 0.30


def build_report(
    aggregated: pd.DataFrame,
    kalshi_df: pd.DataFrame,
    team_map: pd.DataFrame,
    cfg: dict | None = None,
    pinnacle_df: pd.DataFrame | None = None,
    fanduel_df: pd.DataFrame | None = None,
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

    # Independent market anchors (devigged futures books), where offered.
    for df, col in ((pinnacle_df, "pinnacle_prob"), (fanduel_df, "fanduel_prob")):
        if df is not None and not df.empty:
            report = report.merge(df, on=["outcome", "team_abbr"], how="left")
        else:
            report[col] = pd.NA

    # Kalshi's *_dollars fields are already decimals in [0,1] (e.g. "0.27" = 27¢).
    for col in ("yes_bid", "yes_ask", "last_price", "pinnacle_prob", "fanduel_prob"):
        report[col] = pd.to_numeric(report[col], errors="coerce")

    # Market anchor = logit-space Pinnacle 60 / FanDuel 40, renormalized over
    # whichever books are present (single-book rows use that book alone).
    def _logit(p):
        p = p.clip(1e-4, 1 - 1e-4)
        return np.log(p / (1 - p))

    pn, fd = report["pinnacle_prob"], report["fanduel_prob"]
    w_pn = np.where(pn.notna(), PINN_W, 0.0)
    w_fd = np.where(fd.notna(), FD_W, 0.0)
    tw = w_pn + w_fd
    z_mkt = (w_pn * _logit(pn.fillna(0.5)) + w_fd * _logit(fd.fillna(0.5))) / np.where(tw > 0, tw, 1.0)
    report["market_prob"] = np.where(tw > 0, 1.0 / (1.0 + np.exp(-z_mkt)), np.nan)

    # Blend the market anchor into fair where offered: logit-space 70% FanGraphs
    # consensus / 30% market (FG keeps the majority — it's 5 sources — but the
    # futures books price news the projections haven't ingested yet). fg_prob
    # preserves the pure projection consensus; fair_min/max stay FG-relative.
    report["fg_prob"] = report["fair_prob"]
    mask = report["market_prob"].notna() & report["fair_prob"].notna()
    if mask.any():
        fg = report.loc[mask, "fair_prob"]
        mk = report.loc[mask, "market_prob"]
        z = FG_W * _logit(fg) + MKT_W * _logit(mk)
        report.loc[mask, "fair_prob"] = 1.0 / (1.0 + np.exp(-z))

    report["implied_mid"] = report[["yes_bid", "yes_ask"]].mean(axis=1)
    report["fair_minus_mid"] = report["fair_prob"] - report["implied_mid"]

    col_order = [
        "outcome","team_abbr","team_name","league","division",
        "fair_prob","fg_prob","n_sources","pinnacle_prob","fanduel_prob","market_prob",
        "kalshi_ticker","yes_bid","yes_ask","last_price","implied_mid","fair_minus_mid",
    ]
    if "fair_min" in report.columns:
        col_order[6:6] = ["fair_min", "fair_max"]
    return report[col_order].sort_values(["outcome", "league", "division", "team_abbr"]).reset_index(drop=True)
