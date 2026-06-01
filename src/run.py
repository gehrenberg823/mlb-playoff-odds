"""End-to-end pipeline: scrape → aggregate → fetch Kalshi → write report."""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import pandas as pd

from .aggregate import aggregate
from .config import AGG_DIR, RAW_DIR, SIGNAL_DIR, load_config
from .fangraphs import fetch_all as fetch_fg
from .kalshi import fetch_all as fetch_kalshi
from .render import render as render_html
from .signals import build_report
from .teams import load_team_map


def run(target_date: str | None = None) -> Path:
    cfg = load_config()
    target = target_date or date.today().isoformat()

    n_configured = len(cfg["fangraphs"]["sources"])
    print(f"[1/4] Scraping FanGraphs ({n_configured} sources)…")
    per_source = fetch_fg(cfg)
    if len(per_source) < n_configured:
        print(
            f"  WARNING: only {len(per_source)}/{n_configured} sources fetched "
            f"({', '.join(per_source)}); aggregating over the available set."
        )

    raw_out = RAW_DIR / target
    raw_out.mkdir(parents=True, exist_ok=True)
    for src, df in per_source.items():
        df.to_csv(raw_out / f"{src}.csv", index=False)

    print("[2/4] Aggregating (mean across sources)…")
    agg = aggregate(per_source, cfg)
    AGG_DIR.mkdir(parents=True, exist_ok=True)
    agg.to_csv(AGG_DIR / f"{target}.csv", index=False)

    print("[3/4] Fetching Kalshi markets…")
    kal = fetch_kalshi(cfg)

    print("[4/4] Building fair-vs-market report…")
    report = build_report(agg, kal, load_team_map(), cfg)
    SIGNAL_DIR.mkdir(parents=True, exist_ok=True)
    out_path = SIGNAL_DIR / f"{target}.csv"
    report.to_csv(out_path, index=False)

    html_path = render_html(report, target)

    n_with_mkt = int(report["yes_ask"].notna().sum())
    print(
        f"Done. {len(agg)} teams × {len(cfg['fangraphs']['outcomes'])} outcomes; "
        f"{n_with_mkt} rows have Kalshi ask quotes."
    )
    print(f"  CSV:  {out_path}")
    print(f"  HTML: {html_path}")
    return out_path


def main() -> None:
    p = argparse.ArgumentParser(description="MLB playoff odds EV pipeline")
    p.add_argument("--date", default=None, help="YYYY-MM-DD (default: today)")
    args = p.parse_args()
    run(args.date)


if __name__ == "__main__":
    main()
