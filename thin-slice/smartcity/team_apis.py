"""Bridge to the team's API clients in ../APIs (one place that knows where they live).

Every outside call goes through those modules (DRY with flood-thin-slice). Some of them read API keys
at import time, so they are imported lazily and a missing key just means "use the fixture".
"""
import importlib
import logging
import os
import sys
from pathlib import Path

log = logging.getLogger("team-apis")

APIS_DIR = Path(os.getenv("TEAM_APIS_DIR", Path(__file__).resolve().parents[2] / "APIs"))
for p in (APIS_DIR, APIS_DIR / "notification"):
    if p.is_dir() and str(p) not in sys.path:
        sys.path.insert(0, str(p))


def load(name: str):
    """Import a team API module, or return None if it (or its API key) is unavailable."""
    try:
        return importlib.import_module(name)
    except KeyError as exc:  # module reads os.environ[...] at import time
        log.info("%s unavailable: environment variable %s not set", name, exc)
    except ImportError as exc:
        log.warning("%s unavailable: %s", name, exc)
    return None
