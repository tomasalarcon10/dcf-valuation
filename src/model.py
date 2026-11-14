"""DCF with scenarios for an 82-company global universe.

Two engines:
  * FCFF DCF (operating companies): 10-year projection, two-stage growth,
    reinvestment that converges to g / RONIC, Gordon terminal value.
  * Excess-return model (banks, insurers, holding companies): book value plus
    the present value of (ROE - cost of equity) x beginning book value.

Everything is converted to USD at spot FX and discounted with a USD rate built
as risk-free + beta x mature ERP + country risk premium.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

YEARS = 10
HIGH_GROWTH_YEARS = 5
G_TERMINAL = {"bear": 0.015, "base": 0.025, "bull": 0.035}
RATE_SHIFT = {"bear": 0.01, "base": 0.0, "bull": -0.01}
GROWTH_SHIFT = {"bear": -0.04, "base": 0.0, "bull": 0.04}
MARGIN_MULT = {"bear": 0.85, "base": 1.0, "bull": 1.10}
RONIC_SPREAD = 0.03          # return on new capital in perpetuity = WACC + 3pp
GRID_RATE_SHIFTS = np.round(np.arange(-0.02, 0.0201, 0.005), 4)   # 9 columns
GRID_G = np.round(np.arange(0.01, 0.0401, 0.005), 4)              # 7 rows


def clip(x, lo, hi):
    return float(min(max(x, lo), hi))


def debt_spread(debt_ratio: float) -> float:
    """Pre-tax credit spread over the risk-free rate from leverage D/(D+E)."""
    if debt_ratio < 0.10:
        return 0.010
    if debt_ratio < 0.30:
        return 0.015
    if debt_ratio < 0.50:
        return 0.025
    return 0.035


def blume(beta: float) -> float:
    return 0.67 * beta + 0.33


@dataclass
class Company:
    ticker: str
    name: str
    country: str
    region: str
    industry: str
    model: str
    currency: str
    fiscal_years: list
    fx: float                      # local currency units per USD
    mcap: float                    # USD
    rev: list = field(default_factory=list)
    ebit: list | None = None
    da: list | None = None
    capex: list | None = None
    dwc: list | None = None
    tax: list = field(default_factory=list)
    ni: list = field(default_factory=list)
    eq: list = field(default_factory=list)
    debt: float = 0.0
    cash: float = 0.0
    mi: float = 0.0
    note: str = ""


def load_market() -> dict:
    return json.loads((DATA / "market_inputs.json").read_text())


def load_universe() -> list[Company]:
    mkt = load_market()
    fx = mkt["fx_per_usd"]
    meta = {r["ticker"]: r for r in csv.DictReader(open(DATA / "companies.csv"))}
    out = []
    for line in open(DATA / "fundamentals.jsonl"):
        d = json.loads(line)
        m = meta[d["t"]]
        rate = fx[d["cur"]]
        conv = lambda v: None if v is None else [None if x is None else x / rate for x in v]
        c = Company(
            ticker=d["t"], name=m["name"], country=m["country"], region=m["region"],
            industry=m["industry"], model=m["model"], currency=d["cur"],
            fiscal_years=d["fy"], fx=rate,
            mcap=d["mcap"] / fx[d["mcap_cur"]],
            rev=conv(d["rev"]), ebit=conv(d.get("ebit")), da=conv(d.get("da")),
            capex=conv(d.get("capex")), dwc=conv(d.get("dwc")),
            tax=d["tax"], ni=conv(d["ni"]), eq=conv(d["eq"]),
            debt=(d.get("debt") or 0.0) / rate, cash=(d.get("cash") or 0.0) / rate,
            mi=(d.get("mi") or 0.0) / rate, note=d.get("note", ""),
        )
        out.append(c)
    return out


# ----------------------------------------------------------------------------
# Assumptions
# ----------------------------------------------------------------------------
def hist_growth(rev: list) -> float:
    n = len(rev) - 1
    if n < 1 or rev[0] <= 0:
        return 0.03
    return (rev[-1] / rev[0]) ** (1 / n) - 1


def base_growth(g_hist: float) -> float:
    """Shrink the historical CAGR toward 4% (60/40) and cap it: one or two strong
    years should not be extrapolated for five more."""
    return clip(0.6 * g_hist + 0.4 * 0.04, -0.03, 0.15)


def fcff_assumptions(c: Company, mkt: dict) -> dict:
    rf, erp = mkt["risk_free_rate"], mkt["mature_market_erp"]
    crp = mkt["country_risk_premium"][c.country]
    tax = clip(float(np.mean(c.tax)), 0.10, 0.35)
    margins = [e / r for e, r in zip(c.ebit[-2:], c.rev[-2:]) if e is not None]
    margin = clip(float(np.mean(margins)), -0.10, 0.60)
    capex = [abs(x) for x in c.capex]
    da = c.da if c.da is not None else capex
    reinv = [cx - d - w for cx, d, w in zip(capex, da, c.dwc)]   # dwc: cash-flow sign
    nopat = [None if e is None else e * (1 - tax) for e in c.ebit]
    rr = [ri / n for ri, n in zip(reinv[-2:], nopat[-2:]) if n is not None and n > 0]
    reinv_rate = clip(float(np.mean(rr)) if rr else 0.5, 0.0, 1.0)

    de = c.debt / c.mcap if c.mcap > 0 else 0.0
    bu = mkt["unlevered_beta"][c.industry]
    beta = blume(bu * (1 + (1 - tax) * de))
    ke = rf + beta * erp + crp
    dv = c.debt / (c.debt + c.mcap)
    kd = rf + crp + debt_spread(dv)
    wacc = (1 - dv) * ke + dv * kd * (1 - tax)
    return dict(
        model="fcff", rev0=c.rev[-1], g_hist=hist_growth(c.rev), g1=base_growth(hist_growth(c.rev)),
        margin=margin, tax=tax, reinv_rate=reinv_rate, unlevered_beta=bu,
        levered_beta=beta, de_ratio=de, cost_equity=ke, cost_debt_pre_tax=kd,
        debt_weight=dv, crp=crp, rate=wacc, net_debt=c.debt - c.cash, minority=c.mi,
    )


def equity_assumptions(c: Company, mkt: dict) -> dict:
    rf, erp = mkt["risk_free_rate"], mkt["mature_market_erp"]
    crp = mkt["country_risk_premium"][c.country]
    roes = [n / e for n, e in zip(c.ni[-2:], c.eq[-2:]) if e > 0]
    roe0 = clip(float(np.mean(roes)), -0.20, 0.40)
    beta = blume(mkt["levered_beta_bank"][c.industry])
    ke = rf + beta * erp + crp
    return dict(
        model="equity", book0=c.eq[-1], roe0=roe0, g1=clip(0.5 * roe0, 0.0, 0.10),
        levered_beta=beta, crp=crp, rate=ke, cost_equity=ke,
    )


def assumptions(c: Company, mkt: dict) -> dict:
    return fcff_assumptions(c, mkt) if c.model == "fcff" else equity_assumptions(c, mkt)


# ----------------------------------------------------------------------------
# Engines
# ----------------------------------------------------------------------------
def growth_path(g1: float, gT: float) -> np.ndarray:
    g = np.empty(YEARS)
    g[:HIGH_GROWTH_YEARS] = g1
    fade = YEARS - HIGH_GROWTH_YEARS
    for i in range(fade):
        g[HIGH_GROWTH_YEARS + i] = g1 + (gT - g1) * (i + 1) / fade
    return g


def fcff_projection(a: dict, g1: float, margin: float, rate: float, gT: float) -> dict:
    """Return the 10-year projection (FCFF stream does not depend on the rate,
    except through RONIC in the terminal reinvestment rate)."""
    ronic = rate + RONIC_SPREAD
    term_rr = gT / ronic
    g = growth_path(g1, gT)
    rev = a["rev0"] * np.cumprod(1 + g)
    nopat = rev * margin * (1 - a["tax"])
    rr = a["reinv_rate"] + (term_rr - a["reinv_rate"]) * np.arange(1, YEARS + 1) / YEARS
    fcff = nopat * (1 - rr)
    return dict(growth=g, revenue=rev, nopat=nopat, reinv_rate=rr, fcff=fcff,
                terminal_rr=term_rr)


def fcff_value(a: dict, g1: float, margin: float, rate: float, gT: float) -> dict:
    p = fcff_projection(a, g1, margin, rate, gT)
    t = np.arange(1, YEARS + 1)
    disc = (1 + rate) ** -t
    pv = float(np.sum(p["fcff"] * disc))
    fcff_next = p["nopat"][-1] * (1 + gT) * (1 - p["terminal_rr"])
    tv = fcff_next / (rate - gT)
    pv_tv = tv * disc[-1]
    ev = pv + pv_tv
    equity = ev - a["net_debt"] - a["minority"]
    return dict(ev=ev, equity=equity, pv_fcff=pv, pv_tv=pv_tv, tv_share=pv_tv / ev if ev else 0,
                projection={k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in p.items()})


def equity_value(a: dict, g1: float, roe_mult: float, rate: float, gT: float) -> dict:
    roe0 = a["roe0"] * roe_mult
    roeT = rate + 0.5 * (roe0 - rate)
    g = growth_path(g1, gT)
    t = np.arange(1, YEARS + 1)
    roe = roe0 + (roeT - roe0) * t / YEARS
    book_begin = a["book0"] * np.concatenate([[1.0], np.cumprod(1 + g)[:-1]])
    excess = (roe - rate) * book_begin
    disc = (1 + rate) ** -t
    pv = float(np.sum(excess * disc))
    book_end = book_begin[-1] * (1 + g[-1])
    tv = (roeT - rate) * book_end / (rate - gT)
    pv_tv = tv * disc[-1]
    equity = a["book0"] + pv + pv_tv
    return dict(equity=equity, pv_excess=pv, pv_tv=pv_tv, book0=a["book0"],
                projection=dict(growth=g.tolist(), roe=roe.tolist(),
                                book_begin=book_begin.tolist(), excess=excess.tolist()))


def value(a: dict, scenario: str = "base", rate: float | None = None, gT: float | None = None) -> dict:
    g1 = clip(a["g1"] + GROWTH_SHIFT[scenario], -0.20, 0.60)
    r = a["rate"] + RATE_SHIFT[scenario] if rate is None else rate
    g = G_TERMINAL[scenario] if gT is None else gT
    r = max(r, g + 0.01)
    if a["model"] == "fcff":
        m = MARGIN_MULT[scenario] - 1
        return fcff_value(a, g1, a["margin"] + abs(a["margin"]) * m, r, g)
    return equity_value(a, g1, 1 + (MARGIN_MULT[scenario] - 1) * (1 if a["roe0"] >= 0 else -1), r, g)


def sensitivity(a: dict, mcap: float) -> list[list[float | None]]:
    """Implied equity value / market cap - 1 over (terminal g rows) x (rate columns)."""
    grid = []
    for g in GRID_G:
        row = []
        for s in GRID_RATE_SHIFTS:
            r = a["rate"] + s
            if r - g < 0.01:
                row.append(None)
                continue
            v = value(a, "base", rate=r, gT=float(g))["equity"]
            row.append(max(v, 0.0) / mcap - 1)
        grid.append(row)
    return grid


def implied_growth(a: dict, mcap: float) -> float | None:
    """Reverse DCF: the 5-year growth rate that makes base-case value equal market cap."""
    lo, hi = -0.20, 0.60
    f = lambda g: value(dict(a, g1=g), "base")["equity"] - mcap
    flo, fhi = f(lo), f(hi)
    if flo > 0 or fhi < 0:
        return None
    for _ in range(60):
        mid = (lo + hi) / 2
        if f(mid) > 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def run() -> dict:
    mkt = load_market()
    rows = []
    for c in load_universe():
        a = assumptions(c, mkt)
        res = {s: value(a, s) for s in ("bear", "base", "bull")}
        up = {s: max(res[s]["equity"], 0.0) / c.mcap - 1 for s in res}
        rows.append(dict(
            ticker=c.ticker, name=c.name, country=c.country, region=c.region,
            industry=c.industry, model=c.model, currency=c.currency,
            fiscal_year=c.fiscal_years[-1], market_cap_usd=c.mcap, note=c.note,
            assumptions={k: v for k, v in a.items()},
            equity_value={s: res[s]["equity"] for s in res},
            upside=up,
            base_detail={k: v for k, v in res["base"].items() if k != "projection"},
            projection=res["base"]["projection"],
            grid=sensitivity(a, c.mcap),
            implied_growth=implied_growth(a, c.mcap) if c.model == "fcff" else None,
        ))
    return dict(market=mkt, rows=rows,
                grid_rate_shifts=GRID_RATE_SHIFTS.tolist(), grid_g=GRID_G.tolist())
