import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
AGG_DIR = DATA_DIR / "aggregated"
SIGNAL_DIR = DATA_DIR / "signals"


def load_config() -> dict:
    with open(PROJECT_ROOT / "config.json") as f:
        return json.load(f)
