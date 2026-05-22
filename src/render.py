"""Render the signal report to a self-contained HTML file."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from .config import DATA_DIR, PROJECT_ROOT, load_config

# Served by GitHub Pages from `main:/docs`. Keeping the file at the repo
# root (not under data/) means we can publish via a normal git push.
WEB_DIR = PROJECT_ROOT / "docs"

OUTCOME_LABELS = {
    "make_playoffs":    "Make Playoffs",
    "win_division":     "Win Division",
    "win_pennant":      "Win Pennant",
    "win_world_series": "Win World Series",
}

DIVISION_LABELS = {
    ("AL", "E"): "AL East",
    ("AL", "C"): "AL Central",
    ("AL", "W"): "AL West",
    ("NL", "E"): "NL East",
    ("NL", "C"): "NL Central",
    ("NL", "W"): "NL West",
}

# Fixed pill order so divisions appear together in geographic order
TAB_ORDER = [
    "Make Playoffs",
    "AL East", "AL Central", "AL West",
    "NL East", "NL Central", "NL West",
    "Win Pennant",
    "Win World Series",
]


def _fmt_pct(x):
    return "" if pd.isna(x) else f"{x * 100:.1f}%"


def _fmt_cents(x):
    return "" if pd.isna(x) else f"{x * 100:.0f}¢"


def _market_url(ticker: str, template: str) -> str:
    if not ticker:
        return ""
    series = ticker.split("-", 1)[0]
    return template.format(
        ticker=ticker,
        ticker_lower=ticker.lower(),
        series=series,
        series_lower=series.lower(),
    )


def _tab_for(outcome: str, league: str, division: str) -> str:
    if outcome == "win_division":
        return DIVISION_LABELS.get((league, division), OUTCOME_LABELS["win_division"])
    return OUTCOME_LABELS.get(outcome, outcome)


def _to_rows(df: pd.DataFrame, url_template: str) -> list[dict]:
    out = []
    for _, r in df.iterrows():
        fair = r["fair_prob"]
        mid = r["implied_mid"]
        edge = None if pd.isna(fair) or pd.isna(mid) else fair - mid
        ticker = "" if pd.isna(r["kalshi_ticker"]) else r["kalshi_ticker"]
        out.append({
            "tab":      _tab_for(r["outcome"], r["league"], r["division"]),
            "outcome":  OUTCOME_LABELS.get(r["outcome"], r["outcome"]),
            "team":     f"{r['team_name']} ({r['team_abbr']})",
            "league":   r["league"],
            "division": r["division"],
            "fair":     _fmt_pct(fair),
            "fair_raw": None if pd.isna(fair) else float(fair),
            "bid":      _fmt_cents(r["yes_bid"]),
            "ask":      _fmt_cents(r["yes_ask"]),
            "last":     _fmt_cents(r["last_price"]),
            "mid":      _fmt_pct(mid),
            "edge":     "" if edge is None else f"{edge * 100:+.1f}%",
            "edge_raw": None if edge is None else float(edge),
            "ticker":   ticker,
            "ticker_url": _market_url(ticker, url_template),
        })
    return out


def render(report: pd.DataFrame, target_date: str) -> Path:
    WEB_DIR.mkdir(parents=True, exist_ok=True)
    cfg = load_config()
    url_template = cfg["kalshi"].get(
        "market_url_template",
        "https://kalshi.com/markets/{series_lower}/{ticker_lower}",
    )
    rows = _to_rows(report, url_template)
    present_tabs = {r["tab"] for r in rows}
    ordered_tabs = [t for t in TAB_ORDER if t in present_tabs]
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "date":         target_date,
        "rows":         rows,
        "tabs":         ordered_tabs,
    }
    html = _TEMPLATE.replace("__PAYLOAD__", json.dumps(payload))
    out = WEB_DIR / "index.html"
    out.write_text(html)
    return out


_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>MLB Playoff Odds — Fair vs Kalshi</title>
<link rel="stylesheet" href="https://cdn.datatables.net/2.1.8/css/dataTables.dataTables.min.css">
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         margin: 24px; color: #1a1a1a; background: #fafafa; }
  h1   { font-size: 20px; margin: 0 0 4px; }
  .meta { color: #666; font-size: 13px; margin-bottom: 16px; }
  .filters { margin-bottom: 12px; display: flex; gap: 8px; flex-wrap: wrap; }
  .filters button {
    background: #fff; border: 1px solid #ccc; padding: 4px 10px;
    border-radius: 999px; cursor: pointer; font-size: 13px;
  }
  .filters button.active { background: #1a1a1a; color: #fff; border-color: #1a1a1a; }
  table.dataTable { background: #fff; }
  table.dataTable th { font-weight: 600; }
  td.num { text-align: right; font-variant-numeric: tabular-nums; }
  td.edge-pos { color: #0a7c2e; font-weight: 600; }
  td.edge-neg { color: #b00020; }
  td.empty    { color: #aaa; }
</style>
</head>
<body>
<h1>MLB Playoff Odds</h1>
<div class="meta" id="meta"></div>
<div class="filters" id="filters"></div>
<table id="tbl" class="display compact" style="width:100%">
  <thead>
    <tr>
      <th>Outcome</th>
      <th>Team</th>
      <th>Lg</th>
      <th>Div</th>
      <th class="num">Fair</th>
      <th class="num">Bid</th>
      <th class="num">Ask</th>
      <th class="num">Last</th>
      <th class="num">Mid</th>
      <th class="num">Edge (Fair − Mid)</th>
      <th>Kalshi Ticker</th>
    </tr>
  </thead>
</table>

<script src="https://code.jquery.com/jquery-3.7.1.min.js"></script>
<script src="https://cdn.datatables.net/2.1.8/js/dataTables.min.js"></script>
<script>
const DATA = __PAYLOAD__;

document.getElementById("meta").textContent =
  `Data date: ${DATA.date} · Generated: ${DATA.generated_at} · ${DATA.rows.length} rows`;

// Pre-compute tab → row count for the pill labels
const TAB_COUNTS = DATA.rows.reduce((acc, r) => {
  acc[r.tab] = (acc[r.tab] || 0) + 1;
  return acc;
}, {});
const TABS = ["All", ...DATA.tabs];

let activeTab = "All";

const filterBar = document.getElementById("filters");
TABS.forEach(t => {
  const b = document.createElement("button");
  const count = t === "All" ? DATA.rows.length : (TAB_COUNTS[t] || 0);
  b.innerHTML = `${t} <span style="color:#888;font-size:11px">${count}</span>`;
  b.dataset.tab = t;
  if (t === "All") b.classList.add("active");
  b.addEventListener("click", () => {
    document.querySelectorAll(".filters button").forEach(x => x.classList.remove("active"));
    b.classList.add("active");
    activeTab = t;
    table.draw();
  });
  filterBar.appendChild(b);
});

// Custom row-level filter: keep rows whose tab matches the active pill
DataTable.ext.search.push((settings, _searchData, _idx, rowData) =>
  activeTab === "All" || rowData.tab === activeTab
);

const table = new DataTable("#tbl", {
  data: DATA.rows,
  pageLength: 30,
  order: [[4, "desc"]],
  columns: [
    { data: "outcome" },
    { data: "team" },
    { data: "league" },
    { data: "division" },
    { data: "fair", className: "num", type: "num-fmt",
      render: (d, t, row) => t === "sort" || t === "type" ? (row.fair_raw ?? -1) : d },
    { data: "bid",  className: "num" },
    { data: "ask",  className: "num" },
    { data: "last", className: "num" },
    { data: "mid",  className: "num" },
    { data: "edge", className: "num",
      render: (d, t, row) => {
        if (t === "sort" || t === "type") return row.edge_raw ?? -999;
        return d;
      },
      createdCell: (td, _val, rowData) => {
        if (rowData.edge_raw == null) td.classList.add("empty");
        else if (rowData.edge_raw > 0) td.classList.add("edge-pos");
        else if (rowData.edge_raw < 0) td.classList.add("edge-neg");
      },
    },
    { data: "ticker",
      render: (d, t, row) => {
        if (t === "sort" || t === "type" || t === "filter") return d || "";
        if (!d) return "";
        return `<a href="${row.ticker_url}" target="_blank" rel="noopener">${d}</a>`;
      } },
  ],
});
</script>
</body>
</html>
"""
