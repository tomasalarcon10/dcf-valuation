import json
import sys
from pathlib import Path

import numpy as np
import openpyxl
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import model  # noqa: E402

METRICS = json.loads((ROOT / "outputs" / "metrics.json").read_text())
ROWS = {r["ticker"]: r for r in METRICS["rows"]}


def test_universe_complete():
    assert len(model.load_universe()) == 82
    assert len(METRICS["rows"]) == 82


def test_gordon_identity_with_flat_growth():
    a = dict(model="fcff", rev0=100.0, g1=0.03, margin=0.2, tax=0.25, reinv_rate=0.03 / 0.11,
             rate=0.08, net_debt=0.0, minority=0.0)
    # growth 3% every year, reinvestment already at g / RONIC -> a growing perpetuity
    v = model.fcff_value(a, 0.03, 0.2, 0.08, 0.03)
    fcff1 = 100 * 1.03 * 0.2 * 0.75 * (1 - 0.03 / 0.11)
    assert v["ev"] == pytest.approx(fcff1 / (0.08 - 0.03), rel=1e-9)


def test_equity_model_zero_spread_is_book():
    a = dict(model="equity", book0=500.0, roe0=0.09, g1=0.04, rate=0.09)
    assert model.equity_value(a, 0.04, 1.0, 0.09, 0.025)["equity"] == pytest.approx(500.0)


def test_scenarios_are_ordered():
    for r in METRICS["rows"]:
        a = r["assumptions"]
        if (a.get("margin", 1) <= 0) or (r["model"] == "equity" and a["roe0"] <= a["rate"]):
            continue  # growth destroys value when returns sit below the cost of capital
        # equity value is floored at zero (limited liability); loss-makers sit at -100% in every case
        u = r["upside"]
        assert u["bear"] <= u["base"] + 1e-9 <= u["bull"] + 2e-9, r["ticker"]


def test_value_falls_as_rate_rises():
    for r in METRICS["rows"]:
        row = [v for v in r["grid"][3] if v is not None]
        assert all(x >= y - 1e-9 for x, y in zip(row, row[1:])), r["ticker"]


def test_implied_growth_reprices_market():
    mkt = model.load_market()
    c = next(c for c in model.load_universe() if c.ticker == "MSFT")
    a = model.assumptions(c, mkt)
    g = ROWS["MSFT"]["implied_growth"]
    assert model.value(dict(a, g1=g), "base")["equity"] == pytest.approx(c.mcap, rel=1e-6)


@pytest.mark.parametrize("ticker", ["AAPL", "JPM", "TSM", "EC", "CIB", "2222.SR"])
def test_excel_matches_python(ticker):
    wb = openpyxl.load_workbook(ROOT / "excel" / f"DCF_{ticker.replace('.', '_')}.xlsx", data_only=True)
    s = wb["Summary"]
    for k, sc in enumerate(["bear", "base", "bull"]):
        assert s.cell(7, 2 + k).value == pytest.approx(ROWS[ticker]["upside"][sc], abs=1e-6)
    grid = wb["Sensitivity"]
    for i, row in enumerate(ROWS[ticker]["grid"]):
        for j, v in enumerate(row):
            if v is not None:
                assert grid.cell(6 + i, 3 + j).value == pytest.approx(v, abs=1e-6)
