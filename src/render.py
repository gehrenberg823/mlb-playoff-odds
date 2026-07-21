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
        # Executable taker edges at the touch (NOT vs mid — mid flatters wide
        # books), NET of Kalshi's taker fee 0.07·P·(1−P) — ~1.7¢ at midbook,
        # which turns many small gross edges negative. Maker (Post) is fee-free.
        def _fee(p):
            return 0.07 * p * (1 - p)
        yes_edge = None if pd.isna(fair) or pd.isna(ask) else float(fair - ask - _fee(ask))
        no_edge = None if pd.isna(fair) or pd.isna(bid) else float(bid - fair - _fee(bid))
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
        pinn = r.get("pinnacle_prob")
        out.append({
            "tab":      _tab_for(r["outcome"], r["league"], r["division"]),
            "outcome":  OUTCOME_LABELS.get(r["outcome"], r["outcome"]),
            "team":     f"{r['team_name']} ({r['team_abbr']})",
            "div":      f"{r['league']} {r['division']}",
            "league":   r["league"],
            "fair":     _fmt_pct(fair),
            "fair_raw": None if pd.isna(fair) else float(fair),
            "pinn":     _fmt_pct(pinn),
            "pinn_raw": None if pinn is None or pd.isna(pinn) else float(pinn),
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
 body{margin:0;background:var(--bg);color:var(--txt);font:13px/1.4 -apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
 .wrap{margin:0;padding:6px 10px 8px}
 .wrap.measure{width:max-content}
 .top{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
 h1{font-size:15px;margin:0}
 .meta{color:var(--mut);font-size:11.5px;margin:0}
 .meta b{color:var(--txt)}
 .help{color:var(--mut);font-size:11px;cursor:help;border-bottom:1px dotted var(--mut)}
 .stale{display:none;background:rgba(210,153,34,.12);border:1px solid var(--amber);color:var(--amber);
   border-radius:8px;padding:4px 10px;font-size:11.5px;margin:4px 0 0}
 .filterrow{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:5px 0 0}
 .filters{display:flex;gap:5px;flex-wrap:wrap}
 .filters button{background:var(--card);color:var(--mut);border:1px solid var(--line);
   padding:2px 9px;border-radius:999px;cursor:pointer;font-size:11.5px;font-weight:600}
 .filters button.active{color:var(--txt);border-color:var(--acc);background:rgba(63,185,80,.08)}
 .filters.lg button.active{border-color:#58a6ff;background:rgba(88,166,255,.08)}
 .filters button span{opacity:.55;font-size:10px}
 .tables{display:flex;gap:10px;align-items:flex-start;margin-top:5px}
 .tblwrap{flex:1 1 auto;border:1px solid var(--line);border-radius:10px;overflow:hidden}
 table{width:100%;border-collapse:collapse;background:var(--card)}
 thead th{background:#1b232e;
   font-size:9.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--mut);
   text-align:right;padding:4px 7px;border-bottom:1px solid var(--line);cursor:pointer;
   user-select:none;white-space:nowrap}
 thead th.sorted-asc::after{content:" ▲";font-size:9px;color:var(--acc)}
 thead th.sorted-desc::after{content:" ▼";font-size:9px;color:var(--acc)}
 td{padding:2px 7px;font-size:12px;text-align:right;border-bottom:1px solid var(--line);
   font-variant-numeric:tabular-nums;white-space:nowrap}
 th.left,td.left{text-align:left}
 tr:last-child td{border-bottom:none}
 tr.big{background:rgba(63,185,80,.10)}
 tr.noquote td{opacity:.45}
 .pos{color:var(--acc);font-weight:600} .negv{color:var(--neg)} .dash{color:var(--mut)}
 td.widecell{opacity:.5}
 td a{color:inherit;text-decoration:none;border-bottom:1px dotted var(--mut)}
 td a:hover{color:#58a6ff;border-bottom-color:#58a6ff}
</style>
</head>
<body><div class="wrap">
<div class="top">
 <h1>MLB Playoff Odds — Fair vs Kalshi</h1>
 <div class="meta" id="meta"></div>
 <span class="help" title="Take = crossing at the touch, NET of Kalshi taker fees (Buy Yes edge = fair − ask − 0.07·ask·(1−ask); Buy No mirrored). Post = maker order at bid+1¢ (join on a 1¢ spread), ROI = fair ÷ post − 1 — makers pay no fee, fills not guaranteed.
Pinn = de-vigged Pinnacle futures (independent sharp anchor; blank where Pinnacle offers no market). A big Fair-vs-Pinn gap usually means FanGraphs hasn't caught up to news — trust the edge less.
Rows highlight at net take edge ≥ +5%. Edges dim on books wider than 7¢ or when the 5 FanGraphs sources disagree by more than 10 points (red Src Range). Dimmed rows have no Kalshi quotes.">ⓘ how to read</span>
</div>
<div class="stale" id="stale"></div>
<div class="filterrow">
 <div class="filters" id="tabs"></div>
 <div class="filters lg" id="lgs"></div>
 <div class="meta" id="groupline"></div>
</div>
<div class="tables" id="tables"></div>

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

// ---- sorting (raw-value aware, nulls last; headers are re-created every draw,
// so clicks are delegated from the container)
let sortKey = "edge_raw", sortDir = -1;
document.getElementById("tables").addEventListener("click", e => {
  const th = e.target.closest("th");
  if (!th) return;
  const k = th.dataset.k;
  sortDir = (sortKey === k) ? -sortDir : (k === "team" || k === "div" ? 1 : -1);
  sortKey = k;
  draw();
});
function cmp(a, b) {
  const va = a[sortKey], vb = b[sortKey];
  if (va == null && vb == null) return 0;
  if (va == null) return 1;             // nulls always last
  if (vb == null) return -1;
  if (typeof va === "number") return (va - vb) * sortDir;
  return String(va).localeCompare(String(vb)) * sortDir;
}

// Division column only means something on the division tabs — drop it on the
// league/field-wide markets to give the fit-scaler more width to work with.
const NO_DIV_TABS = new Set(["Make Playoffs", "Win Pennant", "Win World Series"]);

// Column model: header label + full <td> renderer per row.
const COLS = [
  {k: "team", label: "Team", left: 1,
   td: r => `<td class="left">${r.url ? `<a href="${r.url}" target="_blank" rel="noopener" title="Open on Kalshi">${r.team}</a>` : r.team}</td>`},
  {k: "div", label: "Div", left: 1, td: r => `<td class="left">${r.div}</td>`},
  {k: "fair_raw", label: "Fair", td: r => `<td>${r.fair || "—"}</td>`},
  {k: "pinn_raw", label: "Pinn", optional: 1, title: "De-vigged Pinnacle futures — independent sharp anchor; a big Fair-vs-Pinn gap usually means FanGraphs hasn't caught up to news",
   td: r => `<td>${r.pinn || "—"}</td>`},
  {k: "src_w", label: "Src Range", title: "min–max across the 5 FanGraphs sources",
   td: r => `<td class="${r.disagree ? "negv" : ""}" ${r.disagree ? 'title="sources disagree by >10 points — weak consensus"' : ""}>${r.src || "—"}</td>`},
  {k: "book", label: "Bid–Ask", td: r => `<td>${r.book || "—"}</td>`},
  {k: "spread", label: "Spread", td: r => `<td>${r.spread || "—"}</td>`},
  {k: "side", label: "Take", td: r => `<td>${r.side ? `<span class="${r.side === "Yes" ? "pos" : "negv"}">${r.side}</span>` : "—"}</td>`},
  {k: "price", label: "Price", td: r => `<td>${r.price || "—"}</td>`},
  {k: "edge_raw", label: "Take Edge",
   td: r => `<td class="${r.edge_raw == null ? "dash" : (r.edge_raw > 0 ? "pos" : "negv")}${r.wide ? " widecell" : ""}${r.disagree ? " widecell" : ""}">${r.edge || "—"}</td>`},
  {k: "post_side", label: "Post", td: r => `<td>${r.post_side ? `<span class="${r.post_side === "Yes" ? "pos" : "negv"}">${r.post_side} ${r.post}</span>` : "—"}</td>`},
  {k: "post_roi", label: "Post ROI",
   td: r => `<td class="${r.post_roi == null ? "dash" : (r.post_roi > 0 ? "pos" : "negv")}${r.disagree ? " widecell" : ""}">${r.post_roi_d || "—"}</td>`},
  {k: "ticker", label: "Market", td: r => `<td>${r.url ? `<a href="${r.url}" target="_blank" rel="noopener">${r.ticker}</a>` : (r.ticker || "—")}</td>`},
];

function tableHTML(rows, cols) {
  const head = cols.map(c =>
    `<th data-k="${c.k}"${c.title ? ` title="${c.title}"` : ""} class="${c.left ? "left " : ""}${sortKey === c.k ? (sortDir === 1 ? "sorted-asc" : "sorted-desc") : ""}">${c.label}</th>`).join("");
  const body = rows.map(r => {
    const cls = [];
    if (r.edge_raw != null && r.edge_raw >= 0.05) cls.push("big");
    if (!r.side) cls.push("noquote");
    return `<tr class="${cls.join(" ")}">${cols.map(c => c.td(r)).join("")}</tr>`;
  }).join("");
  return `<div class="tblwrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function draw() {
  const rows = DATA.rows
    .filter(r => (r.tab === activeTab) &&
                 (activeLg === "All" || r.league === activeLg))
    .sort(cmp);
  // Drop the Div column on league/field-wide tabs, and optional columns
  // (e.g. Pinnacle) on tabs where no row has a value (no futures offered).
  const cols = COLS.filter(c =>
    !(NO_DIV_TABS.has(activeTab) && c.k === "div") &&
    !(c.optional && !rows.some(r => r[c.k] != null)));
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
  // Try both layouts — one table, and two half-height tables side by side —
  // and keep whichever fits the window at the LARGER scale. Splitting only
  // helps when height is the binding constraint AND the doubled width still
  // fits; measuring beats guessing from the aspect ratio.
  const el = document.getElementById("tables");
  let best = {s: -1, html: ""};
  for (const n of (rows.length > 16 ? [1, 2] : [1])) {
    const per = Math.ceil(rows.length / n);
    const parts = [];
    for (let i = 0; i < rows.length; i += per) parts.push(rows.slice(i, i + per));
    const h = parts.map(p => tableHTML(p, cols)).join("");
    el.innerHTML = h;
    const s = idealScale();
    if (s > best.s + 0.001) best = {s, html: h};
  }
  el.innerHTML = best.html;
  requestAnimationFrame(fit);
}

// ---- fit-to-viewport: scale the page so every row AND the ticker column are
// on screen with no scrolling, whatever the window/tab size. Scales DOWN when
// content overflows and UP (to MAX_SCALE) when there's spare room, so the text
// is always as big as the window allows.
const useZoom = typeof CSS !== "undefined" && CSS.supports && CSS.supports("zoom", "0.5");
const MAX_SCALE = 3;
function apply(s) {
  const b = document.body;
  if (useZoom) { b.style.zoom = s; }
  else {
    b.style.transformOrigin = "0 0";
    b.style.transform = s === 1 ? "" : `scale(${s})`;
    b.style.width = s === 1 ? "" : (100 / s) + "%";
  }
}
// Measure the content's NATURAL size by toggling the wrap to width:max-content
// (document.body always spans the full window, so it can't be measured). The
// class comes straight back off, so at rest the wrap — and the tables inside —
// stretch to the right edge and any leftover width pads the columns instead of
// piling up as blank margin.
function idealScale() {
  const w = document.querySelector(".wrap");
  apply(1);
  w.classList.add("measure");
  const s = Math.min(MAX_SCALE, innerWidth / w.offsetWidth, innerHeight / w.offsetHeight);
  w.classList.remove("measure");
  return s;
}
function fit() {
  const de = document.documentElement;
  let s = idealScale();
  apply(s);
  // Upscaling can create overflow the 1:1 measurement couldn't see (nowrap
  // columns hitting the viewport edge) — back off until nothing scrolls.
  for (let i = 0; i < 6 && s > 0.3 &&
       (de.scrollWidth > innerWidth + 1 || de.scrollHeight > innerHeight + 1); i++) {
    s *= 0.94;
    apply(s);
  }
}
window.addEventListener("resize", draw);   // re-draw: the split decision depends on orientation
draw();
</script>
</body>
</html>
"""
