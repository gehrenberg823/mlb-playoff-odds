"""Load the FanGraphs ↔ Kalshi team-abbreviation map."""
from __future__ import annotations

import pandas as pd

from .config import PROJECT_ROOT


def load_team_map() -> pd.DataFrame:
    return pd.read_csv(PROJECT_ROOT / "teams.csv")
