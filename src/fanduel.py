"""FanDuel MLB futures (site API) -> devigged fair probs per outcome/team.

Second market anchor next to Pinnacle, fetched from the "MLB Futures"
competition page (competitionId 12765173, eventTypeId 7511 — same
/api/competition-page endpoint pattern as the NFL futures project; params
must include eventTypeId or the API returns an opaque 400). Requires
curl_cffi's chrome impersonation, like the FanGraphs scrape.

Coverage (checked 2026-08-02): World Series Winner (30), AL/NL pennants
(15 each), divisions (5 each — a runaway division gets delisted, NL West
missing today), and — unlike Pinnacle — Team to Make/Miss Playoffs, which
devig two-way per team where both sides are priced.
"""
from __future__ import annotations

import re

import pandas as pd

FD_URL = ("https://sbapi.nj.sportsbook.fanduel.com/api/competition-page"
          "?_ak=FhMFpcPWXMeyZxOx&eventTypeId=7511&competitionId=12765173")

_GROUP_PATTERNS = [
    (re.compile(r"^World Series \d{4} Winner$", re.I), "win_world_series"),
    (re.compile(r"^(American|National) League \d{4} Winner$", re.I), "win_pennant"),
    (re.compile(r"^(AL|NL) (East|Central|West) \d{4} Winner$", re.I), "win_division"),
]
_MAKE_RE = re.compile(r"^Team to Make Playoffs \d{4}$", re.I)
_MISS_RE = re.compile(r"^Team to Miss Playoffs \d{4}$", re.I)

EXPECTED_TEAMS = {"win_world_series": 30, "win_pennant": 15, "win_division": 5}
OVERROUND_BAND = (1.01, 2.0)          # N-way group markets
TWO_WAY_BAND = (1.005, 1.30)          # per-team make/miss pair


def _implied(american: float) -> float:
    a = float(american)
    return (-a) / (-a + 100.0) if a < 0 else 100.0 / (a + 100.0)


def _power_devig(implieds: list[float]) -> list[float]:
    t = sum(implieds)
    if t <= 1.0:
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


def _runner_prices(mk: dict) -> list[tuple[str, float]]:
    out = []
    for rn in mk.get("runners") or []:
        odds = (((rn.get("winRunnerOdds") or {}).get("americanDisplayOdds") or {})
                .get("americanOdds"))
        if odds is not None:
            out.append((rn.get("runnerName") or "", _implied(odds)))
    return out


def fetch_futures(team_map: pd.DataFrame, timeout: int = 30) -> pd.DataFrame:
    """Return DataFrame(outcome, team_abbr, fanduel_prob)."""
    from curl_cffi import requests as cr
    r = cr.get(FD_URL, impersonate="chrome", timeout=timeout)
    markets = (r.json().get("attachments") or {}).get("markets") or {}

    nick_to_abbr = {str(t.team_name).lower(): t.fg_abbr for t in team_map.itertuples()}

    def abbr_for(full_name: str) -> str | None:
        low = (full_name or "").lower().strip()
        for nick, abbr in nick_to_abbr.items():
            if low == nick or low.endswith(" " + nick):
                return abbr
        return None

    rows = []
    make_imp: dict[str, float] = {}
    miss_imp: dict[str, float] = {}

    for mk in markets.values():
        name = mk.get("marketName") or ""

        outcome = next((o for pat, o in _GROUP_PATTERNS if pat.match(name)), None)
        if outcome:
            def skip(reason: str):
                print(f"  FanDuel sanity: SKIPPING '{name}' — {reason}")

            priced = _runner_prices(mk)
            want = EXPECTED_TEAMS[outcome]
            if len(priced) != want:
                skip(f"{len(priced)}/{want} teams priced — devig would inflate the rest")
                continue
            unmapped = [nm for nm, _ in priced if abbr_for(nm) is None]
            if unmapped:
                skip(f"unmapped team name(s): {unmapped}")
                continue
            t = sum(p for _, p in priced)
            if not (OVERROUND_BAND[0] <= t <= OVERROUND_BAND[1]):
                skip(f"implied sum {t:.3f} outside sane band {OVERROUND_BAND}")
                continue
            for (nm, _), prob in zip(priced, _power_devig([p for _, p in priced])):
                rows.append({"outcome": outcome, "team_abbr": abbr_for(nm),
                             "fanduel_prob": prob})
        elif _MAKE_RE.match(name):
            make_imp.update({nm: p for nm, p in _runner_prices(mk)})
        elif _MISS_RE.match(name):
            miss_imp.update({nm: p for nm, p in _runner_prices(mk)})

    # make_playoffs: per-team binary, so devig each make/miss PAIR two-way
    # (p = make / (make + miss)). Teams missing either side stay blank — a
    # one-sided price still carries the vig and would bias the anchor up.
    for nm, mk_p in make_imp.items():
        ms_p = miss_imp.get(nm)
        abbr = abbr_for(nm)
        if ms_p is None or abbr is None:
            continue
        t = mk_p + ms_p
        if not (TWO_WAY_BAND[0] <= t <= TWO_WAY_BAND[1]):
            print(f"  FanDuel sanity: SKIPPING playoffs pair '{nm}' — implied sum {t:.3f}")
            continue
        rows.append({"outcome": "make_playoffs", "team_abbr": abbr,
                     "fanduel_prob": mk_p / t})

    return pd.DataFrame(rows, columns=["outcome", "team_abbr", "fanduel_prob"])
