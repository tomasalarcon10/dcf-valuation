"""Run the valuation for the whole universe and write outputs/metrics.json."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from model import run, ROOT, GRID_G, GRID_RATE_SHIFTS

OUT = ROOT / "outputs"


def portfolio_surface(res: dict) -> list[list[float]]:
    """Market-cap weighted intrinsic value / market cap over the sensitivity grid
    (rate shift applied to every company, same terminal growth for all)."""
    rows = res["rows"]
    mc = np.array([r["market_cap_usd"] for r in rows])
    out = []
    for i in range(len(GRID_G)):
        line = []
        for j in range(len(GRID_RATE_SHIFTS)):
            vals = [(1 + r["grid"][i][j]) * r["market_cap_usd"] if r["grid"][i][j] is not None
                    else np.nan for r in rows]
            vals = np.array(vals)
            ok = ~np.isnan(vals)
            line.append(float(vals[ok].sum() / mc[ok].sum() - 1))
        out.append(line)
    return out


def summarize(res: dict) -> dict:
    rows = res["rows"]
    mc = np.array([r["market_cap_usd"] for r in rows])
    s = {}
    for sc in ("bear", "base", "bull"):
        eq = np.array([max(r["equity_value"][sc], 0.0) for r in rows])
        s[sc] = dict(
            weighted_upside=float(eq.sum() / mc.sum() - 1),
            median_upside=float(np.median([r["upside"][sc] for r in rows])),
            undervalued_count=int(sum(r["upside"][sc] > 0 for r in rows)),
        )
    ig = [r["implied_growth"] for r in rows if r["implied_growth"] is not None]
    hist = [r["assumptions"]["g_hist"] for r in rows if r["model"] == "fcff"]
    by_region = {}
    for reg in sorted({r["region"] for r in rows}):
        sub = [r for r in rows if r["region"] == reg]
        by_region[reg] = dict(
            count=len(sub),
            median_base_upside=float(np.median([r["upside"]["base"] for r in sub])),
            median_rate=float(np.median([r["assumptions"]["rate"] for r in sub])),
        )
    ranked = sorted(rows, key=lambda r: r["upside"]["base"], reverse=True)
    return dict(
        companies=len(rows),
        fcff_companies=sum(r["model"] == "fcff" for r in rows),
        equity_model_companies=sum(r["model"] == "equity" for r in rows),
        total_market_cap_usd=float(mc.sum()),
        scenarios=s,
        median_rate=float(np.median([r["assumptions"]["rate"] for r in rows])),
        median_implied_growth=float(np.median(ig)),
        median_hist_growth=float(np.median(hist)),
        implied_growth_count=len(ig),
        top5_base=[(r["ticker"], r["upside"]["base"]) for r in ranked[:5]],
        bottom5_base=[(r["ticker"], r["upside"]["base"]) for r in ranked[-5:]],
        by_region=by_region,
    )


def main() -> dict:
    res = run()
    res["portfolio_surface"] = portfolio_surface(res)
    res["summary"] = summarize(res)
    OUT.mkdir(exist_ok=True)
    (OUT / "metrics.json").write_text(json.dumps(res, indent=1, default=float))
    s = res["summary"]
    print(f"{s['companies']} companies | base weighted upside {s['scenarios']['base']['weighted_upside']:+.1%} "
          f"| median implied growth {s['median_implied_growth']:.1%}")
    return res


if __name__ == "__main__":
    main()
