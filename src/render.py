"""Render the signal report to a self-contained HTML file.

UI rebuilt 2026-07-14 (user request):
  * Edge is EXECUTABLE, computed at the touch — Buy Yes edge = fair - ask,
    Buy No edge = bid - fair (i.e. (1-fair) - (1-bid)) — and the page ranks by
    the better side by default. The old Fair-vs-MID edge flattered wide books.
  * Every ticker deep-links to the exact market (?op_market_ticker=).
  * No pagination (all rows, sticky header), no jQuery/DataTables CDN — the
    page is fully self-contained and works offline.
  * Spread shown as a column; wide books (>7c) get a dimmed edge as a
    liquidity hint (the edge is still real — it's priced at the touch).
  * Row highlight at |edge| >= 5%; no-quote rows dimmed.
  * Freshness guard: banner ambers when the snapshot is older than 24h
    (computed client-side), and the source count is shown (e.g. 5/5).
  * Dark GitHub-style theme to match the other boards.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from .config import DATA_DIR, PROJECT_ROOT, load_config

# Served by GitHub Pages from `main:/docs`.
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

TAB_ORDER = [
    "Make Playoffs",
    "AL East", "AL Central", "AL West",
    "NL East", "NL Central", "NL West",
    "Win Pennant",
    "Win World Series",
]

WIDE_SPREAD = 0.07     # dim the edge above this bid/ask width (liquidity hint)


def _fmt_pct(x):
    return "" if pd.isna(x) else f"{x * 100:.1f}%"


def _fmt_cents(x):
    return "" if pd.isna(x) else f"{x * 100:.0f}¢"


def _market_url(ticker: str) -> str:
    """Deep link to the exact market: /markets/{series}/{event}?op_market_ticker=.
    KXMLBPLAYOFFS-26-CWS -> series kxmlbplayoffs, event kxmlbplayoffs-26."""
    if not ticker:
        return ""
    series = ticker.split("-", 1)[0].lower()
    event = ticker.rsplit("-", 1)[0].lower()
    return f"https://kalshi.com/markets/{series}/{event}?op_market_ticker={ticker}"


def _tab_for(outcome: str, league: str, division: str) -> str:
    if outcome == "win_division":
        return DIVISION_LABELS.get((league, division), OUTCOME_LABELS["win_division"])
    return OUTCOME_LABELS.get(outcome, outcome)


def _to_rows(df: pd.DataFrame) -> list[dict]:
    out = []
    for _, r in df.iterrows():
        fair = r["fair_prob"]
        bid, ask = r["yes_bid"], r["yes_ask"]
        # Executable taker edges at the touch (NOT vs mid — mid flatters wide books)
        yes_edge = None if pd.isna(fair) or pd.isna(ask) else float(fair - ask)
        no_edge = None if pd.isna(fair) or pd.isna(bid) else float(bid - fair)
        side = price = edge = None
        cands = []
        if yes_edge is not None:
            cands.append(("Yes", float(ask), yes_edge))
        if no_edge is not None:
            cands.append(("No", float(1 - bid), no_edge))
        if cands:
            side, price, edge = max(cands, key=lambda c: c[2])
        spread = None if pd.isna(bid) or pd.isna(ask) else float(ask - bid)

        # Maker posts on a 1c grid: bid+1c (join at bid on a 1c spread); when a
        # side has no bid, undercut the ask by 1c. Same conventions as the golf
        # books board — the realistic play on these wide season books.
        def _post(b, a):
            if pd.isna(b) and pd.isna(a):
                return None
            if pd.isna(b):
                return max(0.01, float(a) - 0.01)
            p = float(b) + 0.01
            if not pd.isna(a) and p >= float(a):
                p = float(b)          # 1c spread -> join the bid
            return min(p, 0.99)
        yes_post = _post(bid, ask)
        no_post = _post(None if pd.isna(ask) else 1 - ask,
                        None if pd.isna(bid) else 1 - bid)
        post_side = post_price = post_roi = None
        if not pd.isna(fair):
            pcands = []
            if yes_post:
                pcands.append(("Yes", yes_post, float(fair) / yes_post - 1.0))
            if no_post:
                pcands.append(("No", no_post, float(1 - fair) / no_post - 1.0))
            if pcands:
                post_side, post_price, post_roi = max(pcands, key=lambda c: c[2])

        # Source disagreement: min-max of the 5 FanGraphs sources
        fmin = r.get("fair_min") if "fair_min" in r else None
        fmax = r.get("fair_max") if "fair_max" in r else None
        has_range = fmin is not None and fmax is not None and not pd.isna(fmin) and not pd.isna(fmax)
        disagree = bool(has_range and (fmax - fmin) > 0.10)

        ticker = "" if pd.isna(r["kalshi_ticker"]) else r["kalshi_ticker"]
        out.append({
            "tab":      _tab_for(r["outcome"], r["league"], r["division"]),
            "outcome":  OUTCOME_LABELS.get(r["outcome"], r["outcome"]),
            "team":     f"{r['team_name']} ({r['team_abbr']})",
            "div":      f"{r['league']} {r['division']}",
            "league":   r["league"],
            "fair":     _fmt_pct(fair),
            "fair_raw": None if pd.isna(fair) else float(fair),
            "book":     (f"{_fmt_cents(bid)}–{_fmt_cents(ask)}"
                         if not pd.isna(bid) and not pd.isna(ask)
                         else _fmt_cents(bid) or _fmt_cents(ask)),
            "last":     _fmt_cents(r["last_price"]),
            "spread":   _fmt_cents(spread),
            "wide":     bool(spread is not None and spread > WIDE_SPREAD),
            "side":     side,
            "price":    None if price is None else f"{price * 100:.0f}¢",
            "edge":     None if edge is None else f"{edge * 100:+.1f}%",
            "edge_raw": edge,
            "ask_raw":  None if pd.isna(ask) else float(ask),
            "src":      f"{fmin*100:.0f}–{fmax*100:.0f}%" if has_range else "",
            "src_w":    None if not has_range else float(fmax - fmin),
            "disagree": disagree,
            "post_side": post_side,
            "post":     None if post_price is None else f"{post_price * 100:.0f}¢",
            "post_roi": post_roi,
            "post_roi_d": None if post_roi is None else f"{post_roi * 100:+.1f}%",
            "ticker":   ticker,
            "url":      _market_url(ticker),
        })
    return out


def render(report: pd.DataFrame, target_date: str) -> Path:
    WEB_DIR.mkdir(parents=True, exist_ok=True)
    rows = _to_rows(report)
    present_tabs = {r["tab"] for r in rows}
    ordered_tabs = [t for t in TAB_ORDER if t in present_tabs]
    n_sources = int(report["n_sources"].max()) if "n_sources" in report else None
    payload = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "date":         target_date,
        "rows":         rows,
        "tabs":         ordered_tabs,
        "n_sources":    n_sources,
    }
    html = _TEMPLATE.replace("__PAYLOAD__", json.dumps(payload))
    out = WEB_DIR / "index.html"
    out.write_text(html)
    return out


_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MLB Playoff Odds — Fair vs Kalshi</title>
<style>
 :root{--bg:#0d1117;--card:#161b22;--line:#21262d;--txt:#e6edf3;--mut:#8b949e;--acc:#3fb950;--neg:#f85149;--amber:#d29922}
 *{box-sizing:border-box}
 body{margin:0;background:var(--bg);color:var(--txt);font:14px/1.45 -apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
 .wrap{max-width:1060px;margin:0 auto;padding:26px 18px 70px}
 h1{font-size:22px;margin:0 0 4px}
 .meta{color:var(--mut);font-size:12.5px;margin:0 0 6px}
 .meta b{color:var(--txt)}
 .stale{display:none;background:rgba(210,153,34,.12);border:1px solid var(--amber);color:var(--amber);
   border-radius:8px;padding:8px 12px;font-size:12.5px;margin:10px 0}
 .filters{margin:14px 0 6px;display:flex;gap:8px;flex-wrap:wrap}
 .filters button{background:var(--card);color:var(--mut);border:1px solid var(--line);
   padding:5px 12px;border-radius:999px;cursor:pointer;font-size:12.5px;font-weight:600}
 .filters button.active{color:var(--txt);border-color:var(--acc);background:rgba(63,185,80,.08)}
 .filters.lg button.active{border-color:#58a6ff;background:rgba(88,166,255,.08)}
 .filters button span{opacity:.55;font-size:11px}
 .tblwrap{overflow-x:auto;border:1px solid var(--line);border-radius:10px;margin-top:10px}
 table{width:100%;border-collapse:collapse;background:var(--card)}
 thead th{position:sticky;top:0;background:#1b232e;z-index:2;
   font-size:10.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--mut);
   text-align:right;padding:9px 12px;border-bottom:1px solid var(--line);cursor:pointer;
   user-select:none;white-space:nowrap}
 thead th:first-child,thead th:nth-child(2),thead th:nth-child(3){text-align:left}
 thead th.sorted-asc::after{content:" ▲";font-size:9px;color:var(--acc)}
 thead th.sorted-desc::after{content:" ▼";font-size:9px;color:var(--acc)}
 td{padding:6px 12px;font-size:13px;text-align:right;border-bottom:1px solid var(--line);
   font-variant-numeric:tabular-nums;white-space:nowrap}
 td:first-child,td:nth-child(2),td:nth-child(3){text-align:left}
 tr:last-child td{border-bottom:none}
 tr.big{background:rgba(63,185,80,.10)}
 tr.noquote td{opacity:.45}
 .pos{color:var(--acc);font-weight:600} .negv{color:var(--neg)} .dash{color:var(--mut)}
 td.widecell{opacity:.5}
 td a{color:inherit;text-decoration:none;border-bottom:1px dotted var(--mut)}
 td a:hover{color:#58a6ff;border-bottom-color:#58a6ff}
 .note{color:var(--mut);font-size:11.5px;margin-top:10px}
</style>
</head>
<body><div class="wrap">
<h1>MLB Playoff Odds — Fair vs Kalshi</h1>
<div class="meta" id="meta"></div>
<div class="stale" id="stale"></div>
<div class="filters" id="tabs"></div>
<div class="filters lg" id="lgs"></div>
<div class="meta" id="groupline" style="margin-top:4px"></div>
<div class="tblwrap"><table id="tbl">
 <thead><tr>
  <th data-k="outcome">Outcome</th>
  <th data-k="team">Team</th>
  <th data-k="div">Div</th>
  <th data-k="fair_raw">Fair</th>
  <th data-k="src_w" title="min–max across the 5 FanGraphs sources">Src Range</th>
  <th data-k="book">Bid–Ask</th>
  <th data-k="spread">Spread</th>
  <th data-k="side">Take</th>
  <th data-k="price">Price</th>
  <th data-k="edge_raw">Take Edge</th>
  <th data-k="post_side">Post</th>
  <th data-k="post_roi">Post ROI</th>
  <th data-k="ticker">Market</th>
 </tr></thead>
 <tbody id="rows"></tbody>
</table></div>
<p class="note">Take = crossing at the touch (Buy Yes edge = fair − ask · Buy No edge = bid − fair).
 Post = maker order at bid+1¢ (join on a 1¢ spread), ROI = fair ÷ post − 1 — no taker fees, fills not guaranteed.
 Rows highlight at take edge ≥ +5%. Edges dim on books wider than 7¢ or when the 5 FanGraphs sources
 disagree by more than 10 points (red Src Range). Dimmed rows have no Kalshi quotes.</p>

<script>
const DATA = __PAYLOAD__;

// ---- meta + freshness (client-side so a stale page can warn about itself)
const gen = new Date(DATA.generated_at);
const ageH = (Date.now() - gen.getTime()) / 3600000;
document.getElementById("meta").innerHTML =
  `Data date <b>${DATA.date}</b> · generated <b>${gen.toLocaleString()}</b>` +
  (DATA.n_sources ? ` · <b>${DATA.n_sources}/5</b> FanGraphs sources` : "") +
  ` · ${DATA.rows.length} rows`;
if (ageH > 24) {
  const s = document.getElementById("stale");
  s.style.display = "block";
  s.textContent = `⚠ This snapshot is ${Math.round(ageH)} hours old — the daily refresh may have failed.`;
}

// ---- filters: outcome tabs + league pills
let activeTab = DATA.tabs[0], activeLg = "All";
function pill(bar, label, count, on) {
  const b = document.createElement("button");
  b.innerHTML = count == null ? label : `${label} <span>${count}</span>`;
  if (on) b.classList.add("active");
  return b;
}
const tabBar = document.getElementById("tabs");
DATA.tabs.forEach(t => {
  const n = DATA.rows.filter(r => r.tab === t).length;
  const b = pill(tabBar, t, n, t === activeTab);
  b.onclick = () => { activeTab = t; setActive(tabBar, b); draw(); };
  tabBar.appendChild(b);
});
const lgBar = document.getElementById("lgs");
["All", "AL", "NL"].forEach(l => {
  const b = pill(lgBar, l === "All" ? "Both leagues" : l, null, l === "All");
  b.onclick = () => { activeLg = l; setActive(lgBar, b); draw(); };
  lgBar.appendChild(b);
});
function setActive(bar, btn) {
  bar.querySelectorAll("button").forEach(x => x.classList.remove("active"));
  btn.classList.add("active");
}

// ---- sorting (raw-value aware, nulls last)
let sortKey = "edge_raw", sortDir = -1;
document.querySelectorAll("thead th").forEach(th => {
  th.onclick = () => {
    const k = th.dataset.k;
    sortDir = (sortKey === k) ? -sortDir : (k === "team" || k === "outcome" || k === "div" ? 1 : -1);
    sortKey = k;
    draw();
  };
});
function cmp(a, b) {
  const va = a[sortKey], vb = b[sortKey];
  if (va == null && vb == null) return 0;
  if (va == null) return 1;             // nulls always last
  if (vb == null) return -1;
  if (typeof va === "number") return (va - vb) * sortDir;
  return String(va).localeCompare(String(vb)) * sortDir;
}

function draw() {
  document.querySelectorAll("thead th").forEach(th => {
    th.classList.toggle("sorted-asc", th.dataset.k === sortKey && sortDir === 1);
    th.classList.toggle("sorted-desc", th.dataset.k === sortKey && sortDir === -1);
  });
  const rows = DATA.rows
    .filter(r => (r.tab === activeTab) &&
                 (activeLg === "All" || r.league === activeLg))
    .sort(cmp);
  // Group consistency: fair should sum to ~100% per division/pennant group
  // (~1200% for the 12 playoff spots) — a rich/cheap ask sum flags a whole
  // group mispriced, not just one team. Computed over the FULL tab (both leagues).
  const grp = DATA.rows.filter(r => r.tab === activeTab);
  const fairSum = grp.reduce((s, r) => s + (r.fair_raw || 0), 0) * 100;
  const quoted = grp.filter(r => r.ask_raw != null);
  const askSum = quoted.reduce((s, r) => s + r.ask_raw, 0) * 100;
  document.getElementById("groupline").innerHTML =
    `Group check — Σ fair <b>${fairSum.toFixed(0)}%</b> · Σ Kalshi ask <b>${askSum.toFixed(0)}%</b>` +
    ` <span style="opacity:.7">(${quoted.length}/${grp.length} quoted)</span>` +
    (quoted.length === grp.length && askSum > fairSum + 2
      ? ` <span class="negv">— book is rich; NO side favored</span>`
      : quoted.length === grp.length && askSum < fairSum - 2
      ? ` <span class="pos">— book is cheap; YES side favored</span>` : "");
  document.getElementById("rows").innerHTML = rows.map(r => {
    const cls = [];
    if (r.edge_raw != null && r.edge_raw >= 0.05) cls.push("big");
    if (!r.side) cls.push("noquote");
    const edgeCls = r.edge_raw == null ? "dash" : (r.edge_raw > 0 ? "pos" : "negv");
    const wide = r.wide ? " widecell" : "";
    return `<tr class="${cls.join(" ")}">
      <td>${r.outcome}</td>
      <td>${r.url ? `<a href="${r.url}" target="_blank" rel="noopener" title="Open on Kalshi">${r.team}</a>` : r.team}</td>
      <td>${r.div}</td>
      <td>${r.fair || "—"}</td>
      <td class="${r.disagree ? "negv" : ""}" ${r.disagree ? 'title="sources disagree by >10 points — weak consensus"' : ""}>${r.src || "—"}</td>
      <td>${r.book || "—"}</td>
      <td>${r.spread || "—"}</td>
      <td>${r.side ? `<span class="${r.side === "Yes" ? "pos" : "negv"}">${r.side}</span>` : "—"}</td>
      <td>${r.price || "—"}</td>
      <td class="${edgeCls}${wide}${r.disagree ? " widecell" : ""}">${r.edge || "—"}</td>
      <td>${r.post_side ? `<span class="${r.post_side === "Yes" ? "pos" : "negv"}">${r.post_side} ${r.post}</span>` : "—"}</td>
      <td class="${r.post_roi == null ? "dash" : (r.post_roi > 0 ? "pos" : "negv")}${r.disagree ? " widecell" : ""}">${r.post_roi_d || "—"}</td>
      <td>${r.url ? `<a href="${r.url}" target="_blank" rel="noopener">${r.ticker}</a>` : (r.ticker || "—")}</td>
    </tr>`;
  }).join("");
}
draw();
</script>
</body>
</html>
"""
