"""Pure-logic tests for the flood rules copied from load_all.flood_check. No database needed."""
import pytest

from api.flood import band_for, grade

WL = (2.40, 2.75, 3.00)  # 10%, 0.5%, 0.1% AEP water levels


@pytest.mark.parametrize("level, band", [
    (1.00, None), (2.39, None), (2.40, "10%"), (2.74, "10%"),
    (2.75, "0.5%"), (2.99, "0.5%"), (3.00, "0.1%"), (4.50, "0.1%"),
])
def test_band_for(level, band):
    assert band_for(level, *WL) == band


@pytest.mark.parametrize("kind, depth, expected", [
    ("road", None, "unsafe"), ("building", None, "unsafe"),
    ("road", 0.05, "safe"), ("road", 0.10, "caution"), ("road", 0.29, "caution"), ("road", 0.30, "unsafe"),
    ("building", -0.20, "safe"), ("building", 0.00, "caution"), ("building", 0.14, "caution"),
    ("building", 0.15, "unsafe"), ("hospital", 0.05, "caution"),
])
def test_grade(kind, depth, expected):
    assert grade(kind, depth) == expected
