"""Smoke tests: every API client imports cleanly and the thin slice is valid Python.

Nothing here calls the network. API keys are given dummy values so modules that read them at import time load.
"""
import importlib
import os
import py_compile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
API_MODULES = sorted(p.stem for p in (ROOT / "APIs").glob("*.py"))


@pytest.fixture(autouse=True)
def dummy_keys(monkeypatch):
    for name in ("TICKETMASTER_API_KEY", "TOMTOM_API_KEY", "NTA_API_KEY"):
        monkeypatch.setenv(name, os.environ.get(name, "dummy"))


@pytest.mark.parametrize("name", API_MODULES)
def test_api_module_imports(name):
    importlib.import_module(name)


def test_thin_slice_is_valid_python():
    py_compile.compile(str(ROOT / "flood-thin-slice" / "load_all.py"), doraise=True)


def test_expected_api_functions_exist():
    """load_all.py calls these by name; a rename in APIs/ would otherwise only fail at run time."""
    expected = {
        "busAPI": ["BusTripUpdatesQuery", "DublinBusTimetableDownload"],
        "csoAPI": ["smallAreaBoundaries", "smallAreaPopulation"],
        "gsiLidarAPI": ["lidarTiles", "downloadTile"],
        "marineTideAPI": ["tideGaugeReadings"],
        "metEireannAPI": ["weatherWarnings", "pointForecast"],
        "opwAPI": ["latestWaterLevels", "downloadCframNodes", "downloadCframRiverExtents",
                   "downloadCframCoastalExtents", "downloadCoastalExtremeLevels"],
        "osmAPI": ["infrastructureQuery"],
    }
    for module, funcs in expected.items():
        mod = importlib.import_module(module)
        for fn in funcs:
            assert callable(getattr(mod, fn, None)), f"{module}.{fn} is missing"
