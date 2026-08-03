"""Pinnacle MLB futures (guest API) -> devigged fair probs per outcome/team.

An independent sharp-market anchor shown next to the FanGraphs consensus:
Pinnacle reprices on news (trades, injuries) hours-to-days before projection
systems update their rosters, so a big Fair-vs-Pinnacle gap usually means
FanGraphs hasn't caught up to something the market knows.

Coverage (checked 2026-07-21): World Series Champion (30), AL/NL Pennant
Winner (15 each), and division winners — but NOT make_playoffs, and a
runaway division is sometimes delisted (NL West was missing). Missing
markets simply yield no rows; the report column is blank there.
"""
from __future__ import annotations

import re

import pandas as pd
import requests

BASE = "https://guest.api.arcadia.pinnacle.com/0.1"
HEADERS = {
    "x-api-key": "CmX2KcMrXuFmNg6YFbmTxE0y9CIrOi0R",
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "application/json",
}
SPORT_BASEBALL = 3

_OUTCOME_PATTERNS = [
    (re.compile(r"world series champion", re.I), "win_world_series"),
    (re.compile(r"league pennant winner", re.I), "win_pennant"),
    (re.compile(r"league (east|central|west) winner", re.I), "win_division"),
]


def _outcome_for(description: str) -> str | None:
    for pat, outcome in _OUTCOME_PATTERNS:
        if pat.search(description or ""):
            return outcome
    return None


def _implied(american: float) -> float:
    a = float(american)
    return (-a) / (-a + 100.0) if a < 0 else 100.0 / (a + 100.0)


def _power_devig(implieds: list[float]) -> list[float]:
    """N-way power devig: find k with sum(p_i^k) = 1 (bisection). Puts most of
    the vig on the longshots — essential for a 30-way World Series book, where
    a proportional split badly inflates the tail teams."""
    t = sum(implieds)
    if t <= 1.0:   # underround — proportional is the safe fallback
        return [p / t for p in implieds]
    lo, hi = 1.0, 20.0
    for _ in range(60):
        k = (lo + hi) / 2
        if sum(p ** k for p in implieds) > 1.0:
            lo = k
        else:
            hi = k
    k = (lo + hi) / 2
    return [p ** k for p in implieds]


def fetch_futures(team_map: pd.DataFrame, timeout: int = 40) -> pd.DataFrame:
    """Return DataFrame(outcome, team_abbr, pinnacle_prob).

    team_map is teams.csv (fg_abbr, kalshi_abbr, team_name-nickname); Pinnacle's
    full names ("Chicago White Sox") are matched by nickname suffix — MLB
    nicknames are unique, so the match is unambiguous.
    """
    mu = requests.get(f"{BASE}/sports/{SPORT_BASEBALL}/matchups",
                      headers=HEADERS, params={"brandId": 0}, timeout=timeout).json()
    futs = [m for m in mu
            if (m.get("special") or {}).get("category") == "Futures"
            and (m.get("league") or {}).get("name") == "MLB"]

    # Prices via the league-wide markets endpoint rather than per-matchup
    # /matchups/{id}/markets/related/straight: Pinnacle started geo-blocking
    # the per-matchup endpoint for futures from US IPs (403 BAD_LOCATION,
    # seen on NFL 2026-08-02; MLB still answered but is presumably next).
    # The league endpoint carries the same moneylines, one request for all.
    by_matchup = {}
    for lid in {m["league"]["id"] for m in futs}:
        r = requests.get(f"{BASE}/leagues/{lid}/markets/straight",
                         headers=HEADERS, timeout=timeout)
        body = r.json() if "json" in r.headers.get("content-type", "") else None
        if not isinstance(body, list):
            title = body.get("title") if isinstance(body, dict) else ""
            print(f"  Pinnacle sanity: league {lid} markets HTTP {r.status_code} {title or ''}")
            continue
        for mk in body:
            if mk.get("type") == "moneyline" and mk.get("period") == 0:
                by_matchup[mk.get("matchupId")] = mk

    nick_to_abbr = {str(r.team_name).lower(): r.fg_abbr for r in team_map.itertuples()}

    def abbr_for(full_name: str) -> str | None:
        low = (full_name or "").lower().strip()
        for nick, abbr in nick_to_abbr.items():
            if low == nick or low.endswith(" " + nick):
                return abbr
        return None

    # Devigging forces whatever is priced to sum to 100%, so a market is only
    # publishable when it is COMPLETE: every expected team present, priced, and
    # name-mapped, with a plausible overround. Anything less silently inflates
    # the remaining teams — skip the market instead (blank beats wrong).
    EXPECTED_TEAMS = {"win_world_series": 30, "win_pennant": 15, "win_division": 5}
    OVERROUND_BAND = (1.01, 2.0)

    rows = []
    for m in futs:
        desc = (m.get("special") or {}).get("description") or ""
        outcome = _outcome_for(desc)
        if not outcome:
            continue

        def skip(reason: str):
            print(f"  Pinnacle sanity: SKIPPING '{desc}' — {reason}")

        parts = {p["id"]: p.get("name") for p in m.get("participants", [])}
        if len(parts) != EXPECTED_TEAMS[outcome]:
            skip(f"{len(parts)} participants, expected {EXPECTED_TEAMS[outcome]}")
            continue
        ml = by_matchup.get(m["id"])
        if not ml:
            skip("no moneyline on league markets endpoint")
            continue
        priced = [(p["participantId"], p["price"]) for p in ml.get("prices", [])
                  if p.get("price") is not None and p.get("participantId") in parts]
        if len(priced) != len(parts):
            skip(f"only {len(priced)}/{len(parts)} teams priced — devig would inflate the rest")
            continue
        unmapped = [parts[pid] for pid, _ in priced if abbr_for(parts[pid]) is None]
        if unmapped:
            skip(f"unmapped team name(s): {unmapped} — extend teams.csv/nickname matching")
            continue
        implieds = [_implied(a) for _, a in priced]
        t = sum(implieds)
        if not (OVERROUND_BAND[0] <= t <= OVERROUND_BAND[1]):
            skip(f"implied sum {t:.3f} outside sane band {OVERROUND_BAND} — payload suspect")
            continue

        fair = _power_devig(implieds)
        assert abs(sum(fair) - 1.0) < 1e-6, f"devig failed to normalize ({sum(fair):.6f})"
        for (pid, _), prob in zip(priced, fair):
            rows.append({"outcome": outcome, "team_abbr": abbr_for(parts[pid]),
                         "pinnacle_prob": prob})

    return pd.DataFrame(rows, columns=["outcome", "team_abbr", "pinnacle_prob"])
