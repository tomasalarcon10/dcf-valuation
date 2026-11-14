"""Build one Excel workbook per company with live formulas.

Sheets: Summary, Inputs (raw data + assumptions + discount rate), Scenarios
(bear/base/bull 10-year projections) and Sensitivity (rate x terminal growth).
Colour code: blue = hard-coded input, black = formula, green = link to another
sheet, yellow fill = key assumption.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from openpyxl import Workbook
from openpyxl.formatting.rule import ColorScaleRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter as CL

from model import DATA, ROOT, G_TERMINAL, GRID_G, GRID_RATE_SHIFTS, GROWTH_SHIFT, MARGIN_MULT, RATE_SHIFT, RONIC_SPREAD

XL = ROOT / "excel"
F = "Arial"
BLUE = Font(name=F, color="0000FF")
BLACK = Font(name=F, color="000000")
GREEN = Font(name=F, color="008000")
BOLD = Font(name=F, bold=True)
TITLE = Font(name=F, bold=True, size=14)
HEAD = Font(name=F, bold=True, color="FFFFFF")
HEAD_FILL = PatternFill("solid", fgColor="1F3A5F")
SEC_FILL = PatternFill("solid", fgColor="D9E1F2")
YELLOW = PatternFill("solid", fgColor="FFF2CC")
THIN = Border(bottom=Side(style="thin", color="BFBFBF"))
PCT, PCT1, NUM, MULT = "0.0%;(0.0%);-", "0.00%", '#,##0;(#,##0);"-"', "0.00"
USDM = '#,##0,,;(#,##0,,);"-"'          # USD shown in millions


def put(ws, ref, value, font=BLACK, fmt=None, fill=None, bold=False):
    c = ws[ref]
    c.value = value
    c.font = Font(name=F, color=font.color, bold=bold or font.bold)
    if fmt:
        c.number_format = fmt
    if fill:
        c.fill = fill
    return c


def section(ws, row, text, width=13):
    for col in range(1, width + 1):
        ws.cell(row=row, column=col).fill = SEC_FILL
    ws.cell(row=row, column=1, value=text).font = BOLD


def header_row(ws, row, labels, start_col=1):
    for i, lab in enumerate(labels):
        c = ws.cell(row=row, column=start_col + i, value=lab)
        c.font, c.fill = HEAD, HEAD_FILL
        c.alignment = Alignment(horizontal="center")


def build(d: dict, meta: dict, mkt: dict, result: dict) -> Path:
    fcff = meta["model"] == "fcff"
    n = len(d["fy"])
    first, last, prev = "C", CL(2 + n), CL(2 + n - 1) if n > 1 else "C"
    wb = Workbook()
    summ = wb.active
    summ.title = "Summary"
    inp = wb.create_sheet("Inputs")
    sc = wb.create_sheet("Scenarios")
    sen = wb.create_sheet("Sensitivity")

    # ------------------------------------------------------------------ Inputs
    ws = inp
    ws.column_dimensions["A"].width = 44
    ws.column_dimensions["B"].width = 18
    for col in range(3, 8):
        ws.column_dimensions[CL(col)].width = 16
    put(ws, "A1", f"{meta['name']} ({d['t']}): inputs and assumptions", bold=True).font = TITLE
    put(ws, "A2", "Blue = hard-coded input, black = formula, green = link, yellow = key assumption. "
                  "Raw financials in reporting currency; valuation in USD.")
    info = [("Company", meta["name"], None), ("Ticker", d["t"], None), ("Country", meta["country"], None),
            ("Industry (Damodaran classification)", meta["industry"], None),
            ("Valuation model", "FCFF DCF" if fcff else "Excess-return (book value + PV of ROE - Ke)", None),
            ("Reporting currency", d["cur"], None),
            ("FX: reporting currency per USD", mkt["fx_per_usd"][d["cur"]], "0.0000"),
            (f"Market cap ({d['mcap_cur']}, {d['mcap_date']})", d["mcap"], USDM),
            (f"FX: {d['mcap_cur']} per USD", mkt["fx_per_usd"][d["mcap_cur"]], "0.0000")]
    for i, (lab, val, fmt) in enumerate(info):
        r = 4 + i
        put(ws, f"A{r}", lab)
        put(ws, f"B{r}", val, BLUE, fmt)
    put(ws, "A13", "Market cap (USD millions)")
    put(ws, "B13", "=B11/B12", BLACK, USDM)
    put(ws, "A14", "Source: Yahoo Finance fundamentals-timeseries; FX: " + mkt["fx_source"])

    section(ws, 16, "Historical financials (reporting currency, millions)")
    header_row(ws, 17, ["Line item"] + [""] + [f"FY {y[:7]}" for y in d["fy"]])
    items = [(18, "Revenue", d["rev"]), (19, "EBIT", d.get("ebit")), (20, "Depreciation & amortization", d.get("da")),
             (21, "Capital expenditure (cash flow sign)", d.get("capex")),
             (22, "Change in working capital (cash flow sign)", d.get("dwc")),
             (23, "Effective tax rate", d["tax"]), (24, "Net income to common", d["ni"]),
             (25, "Common equity (book)", d["eq"])]
    for r, lab, vals in items:
        put(ws, f"A{r}", lab)
        for j in range(n):
            v = None if vals is None else vals[j]
            if v is not None:
                put(ws, f"{CL(3 + j)}{r}", v, BLUE, PCT if r == 23 else USDM)
    put(ws, "A27", "Total debt (latest)")
    put(ws, "B27", d.get("debt") or 0, BLUE, USDM)
    put(ws, "A28", "Cash and short-term investments (latest)")
    put(ws, "B28", d.get("cash") or 0, BLUE, USDM)
    put(ws, "A29", "Minority interest (latest)")
    put(ws, "B29", d.get("mi") or 0, BLUE, USDM)

    section(ws, 31, "Derived history (USD millions unless %)")
    for j in range(n):
        c = CL(3 + j)
        put(ws, f"{c}32", f"={c}18/$B$10", BLACK, USDM)
        put(ws, f"{c}33", f'=IF(ISNUMBER({c}19),{c}19/{c}18,"")', BLACK, PCT)
        put(ws, f"{c}34", f'=IF(ISNUMBER({c}19),{c}19*(1-$B$45)/$B$10,"")', BLACK, USDM)
        da = f"{c}20" if d.get("da") else f"ABS({c}21)"
        if fcff:
            put(ws, f"{c}35", f"=(ABS({c}21)-{da}-{c}22)/$B$10", BLACK, USDM)
            put(ws, f"{c}36", f'=IF(ISNUMBER({c}34),IF({c}34>0,{c}35/{c}34,""),"")', BLACK, PCT)
        put(ws, f"{c}37", f'=IF({c}25>0,{c}24/{c}25,"")', BLACK, PCT)
    for r, lab in [(32, "Revenue"), (33, "EBIT margin"), (34, "NOPAT (at normalised tax rate)"),
                   (35, "Net reinvestment (capex - D&A - change in WC)"), (36, "Reinvestment / NOPAT"),
                   (37, "Return on equity")]:
        put(ws, f"A{r}", lab)

    section(ws, 40, "Assumptions")
    rf, erp = mkt["risk_free_rate"], mkt["mature_market_erp"]
    crp = mkt["country_risk_premium"][meta["country"]]
    beta = mkt["unlevered_beta"][meta["industry"]] if fcff else mkt["levered_beta_bank"][meta["industry"]]
    rows = [
        (41, "Risk-free rate (US 10Y Treasury)", rf, BLUE, PCT1, YELLOW, mkt["risk_free_source"]),
        (42, "Mature market equity risk premium", erp, BLUE, PCT1, YELLOW, mkt["erp_source"]),
        (43, f"Country risk premium ({meta['country']})", crp, BLUE, PCT1, YELLOW, mkt["erp_source"]),
        (44, "Industry unlevered beta" if fcff else "Industry levered beta", beta, BLUE, MULT, YELLOW, mkt["beta_source"]),
        (45, "Tax rate (average effective, bounded 10%-35%)", f"=MIN(MAX(AVERAGE({first}23:{last}23),0.1),0.35)", BLACK, PCT, None, ""),
        (46, "Historical revenue CAGR", f"=({last}18/{first}18)^(1/{max(n - 1, 1)})-1" if n > 1 else 0.03, BLACK, PCT, None, ""),
    ]
    if fcff:
        rows += [
            (47, "Base growth, years 1-5 (60% history + 40% x 4%, capped -3%/15%)", "=MIN(MAX(0.6*B46+0.4*0.04,-0.03),0.15)", BLACK, PCT, YELLOW, ""),
            (48, "EBIT margin (average of last two years, bounded)", f"=MIN(MAX(AVERAGE({prev}33:{last}33),-0.1),0.6)", BLACK, PCT, YELLOW, ""),
            (49, "Reinvestment / NOPAT, year 1 (average last two years)", f"=IFERROR(MIN(MAX(AVERAGE({prev}36:{last}36),0),1),0.5)", BLACK, PCT, YELLOW, ""),
        ]
    else:
        rows += [
            (50, "ROE (average of last two years, bounded)", f"=MIN(MAX(AVERAGE({prev}37:{last}37),-0.2),0.4)", BLACK, PCT, YELLOW, ""),
            (47, "Book growth, years 1-5 (50% retention x ROE, capped 10%)", "=MIN(MAX(0.5*B50,0),0.1)", BLACK, PCT, YELLOW, ""),
        ]
    rows += [
        (51, "RONIC spread over WACC (perpetuity)", RONIC_SPREAD, BLUE, PCT1, None, "Return on new invested capital = WACC + spread"),
        (52, "Total debt (USD millions)", "=B27/B10", BLACK, USDM, None, ""),
        (53, "Cash (USD millions)", "=B28/B10", BLACK, USDM, None, ""),
        (54, "Minority interest (USD millions)", "=B29/B10", BLACK, USDM, None, ""),
        (55, "Book equity, latest (USD millions)", f"={last}25/B10", BLACK, USDM, None, ""),
    ]
    for r, lab, val, font, fmt, fill, src in rows:
        put(ws, f"A{r}", lab)
        put(ws, f"B{r}", val, font, fmt, fill)
        if src:
            put(ws, f"C{r}", src)

    section(ws, 57, "Discount rate")
    dr = [
        (58, "Debt / equity (market)", "=B52/B13", MULT),
        (59, "Levered beta (Hamada)" if fcff else "Levered beta (industry)", "=B44*(1+(1-B45)*B58)" if fcff else "=B44", MULT),
        (60, "Adjusted beta (Blume: 0.67 x beta + 0.33)", "=0.67*B59+0.33", MULT),
        (61, "Cost of equity = Rf + beta x ERP + CRP", "=B41+B60*B42+B43", PCT1),
        (62, "Debt / (debt + equity)", "=B52/(B52+B13)", PCT),
        (63, "Credit spread (by leverage bucket)", "=IF(B62<0.1,0.01,IF(B62<0.3,0.015,IF(B62<0.5,0.025,0.035)))", PCT1),
        (64, "Pre-tax cost of debt = Rf + CRP + spread", "=B41+B43+B63", PCT1),
        (65, "WACC" if fcff else "Discount rate (cost of equity)",
         "=(1-B62)*B61+B62*B64*(1-B45)" if fcff else "=B61", PCT1),
    ]
    for r, lab, f, fmt in dr:
        put(ws, f"A{r}", lab)
        put(ws, f"B{r}", f, BLACK, fmt, YELLOW if r == 65 else None, bold=r == 65)

    section(ws, 67, "Scenario parameters")
    header_row(ws, 68, ["Parameter", "Bear", "Base", "Bull"])
    scen = ["bear", "base", "bull"]
    params = [(69, "Growth shift, years 1-5", GROWTH_SHIFT), (70, ("Margin" if fcff else "ROE") + " multiplier (applied to |level|)", MARGIN_MULT),
              (71, "Discount-rate shift", RATE_SHIFT), (72, "Terminal growth", G_TERMINAL)]
    for r, lab, dct in params:
        put(ws, f"A{r}", lab)
        for k, s in enumerate(scen):
            put(ws, f"{CL(2 + k)}{r}", dct[s], BLUE, MULT if r == 70 else PCT1, YELLOW)
    put(ws, "A73", "Growth, years 1-5")
    put(ws, "A74", "Discount rate (floored at terminal g + 1pp)")
    put(ws, "A75", "EBIT margin" if fcff else "Starting ROE")
    for k in range(3):
        c = CL(2 + k)
        put(ws, f"{c}73", f"=MIN(MAX($B$47+{c}69,-0.2),0.6)", BLACK, PCT)
        put(ws, f"{c}74", f"=MAX($B$65+{c}71,{c}72+0.01)", BLACK, PCT)
        b0 = f"$B${48 if fcff else 50}"
        put(ws, f"{c}75", f"={b0}+ABS({b0})*({c}70-1)", BLACK, PCT)

    # --------------------------------------------------------------- Scenarios
    ws = sc
    ws.column_dimensions["A"].width = 40
    ws.column_dimensions["B"].width = 16
    for col in range(3, 13):
        ws.column_dimensions[CL(col)].width = 12
    put(ws, "A1", f"{meta['name']}: 10-year projections by scenario (USD millions)").font = TITLE
    years = [CL(3 + i) for i in range(10)]
    out_cells = {}
    H = 23
    for k, s in enumerate(scen):
        p = CL(2 + k)                         # parameter column in Inputs
        g1, rate, gT, lev = (f"Inputs!${p}$73", f"Inputs!${p}$74", f"Inputs!${p}$72", f"Inputs!${p}$75")
        b = 3 + k * H
        section(ws, b, f"{s.capitalize()} case", 12)
        header_row(ws, b + 1, ["Year", ""] + [f"Y{i + 1}" for i in range(10)])
        put(ws, f"A{b + 2}", "t")
        for i, c in enumerate(years):
            put(ws, f"{c}{b + 2}", i + 1, BLUE, "0")
            t = f"{c}${b + 2}"
            put(ws, f"{c}{b + 3}", f"=IF({t}<=5,{g1},{g1}+({gT}-{g1})*({t}-5)/5)", GREEN, PCT)
        if fcff:
            labels = ["Revenue growth", "Revenue", "EBIT", "NOPAT", "Reinvestment / NOPAT", "FCFF",
                      "Discount factor", "PV of FCFF"]
            for j, lab in enumerate(labels):
                put(ws, f"A{b + 3 + j}", lab)
            for i, c in enumerate(years):
                t = f"{c}${b + 2}"
                prevrev = f"Inputs!${last}$32" if i == 0 else f"{years[i - 1]}{b + 4}"
                put(ws, f"{c}{b + 4}", f"={prevrev}*(1+{c}{b + 3})", GREEN if i == 0 else BLACK, USDM)
                put(ws, f"{c}{b + 5}", f"={c}{b + 4}*{lev}", GREEN, USDM)
                put(ws, f"{c}{b + 6}", f"={c}{b + 5}*(1-Inputs!$B$45)", GREEN, USDM)
                put(ws, f"{c}{b + 7}", f"=Inputs!$B$49+({gT}/({rate}+Inputs!$B$51)-Inputs!$B$49)*{t}/10", GREEN, PCT)
                put(ws, f"{c}{b + 8}", f"={c}{b + 6}*(1-{c}{b + 7})", BLACK, USDM)
                put(ws, f"{c}{b + 9}", f"=(1+{rate})^-{t}", GREEN, "0.0000")
                put(ws, f"{c}{b + 10}", f"={c}{b + 8}*{c}{b + 9}", BLACK, USDM)
            summary = [
                ("PV of FCFF, years 1-10", f"=SUM(C{b + 10}:L{b + 10})", USDM),
                ("FCFF year 11 = NOPAT x (1+g) x (1 - g / RONIC)", f"=L{b + 6}*(1+{gT})*(1-{gT}/({rate}+Inputs!$B$51))", USDM),
                ("Terminal value = FCFF11 / (WACC - g)", f"=B{b + 13}/({rate}-{gT})", USDM),
                ("PV of terminal value", f"=B{b + 14}*L{b + 9}", USDM),
                ("Enterprise value", f"=B{b + 12}+B{b + 15}", USDM),
                ("Less: total debt", "=-Inputs!B52", USDM),
                ("Plus: cash", "=Inputs!B53", USDM),
                ("Less: minority interest", "=-Inputs!B54", USDM),
                ("Equity value", f"=SUM(B{b + 16}:B{b + 19})", USDM),
                ("Equity value vs market cap", f"=MAX(B{b + 20},0)/Inputs!$B$13-1", PCT),
            ]
            for j, (lab, f, fmt) in enumerate(summary):
                r = b + 12 + j
                put(ws, f"A{r}", lab, bold=j in (8, 9))
                put(ws, f"B{r}", f, GREEN if "Inputs" in f else BLACK, fmt, bold=j in (8, 9))
            out_cells[s] = (f"Scenarios!B{b + 20}", f"Scenarios!B{b + 21}")
        else:
            labels = ["Book growth", "ROE", "Beginning book equity", "Excess return = (ROE - Ke) x book",
                      "Discount factor", "PV of excess return"]
            for j, lab in enumerate(labels):
                put(ws, f"A{b + 3 + j}", lab)
            roeT = f"$B${b + 12}"
            for i, c in enumerate(years):
                t = f"{c}${b + 2}"
                put(ws, f"{c}{b + 4}", f"={lev}+({roeT}-{lev})*{t}/10", GREEN, PCT)
                if i == 0:
                    put(ws, f"{c}{b + 5}", "=Inputs!$B$55", GREEN, USDM)
                else:
                    pc = years[i - 1]
                    put(ws, f"{c}{b + 5}", f"={pc}{b + 5}*(1+{pc}{b + 3})", BLACK, USDM)
                put(ws, f"{c}{b + 6}", f"=({c}{b + 4}-{rate})*{c}{b + 5}", GREEN, USDM)
                put(ws, f"{c}{b + 7}", f"=(1+{rate})^-{t}", GREEN, "0.0000")
                put(ws, f"{c}{b + 8}", f"={c}{b + 6}*{c}{b + 7}", BLACK, USDM)
            summary = [
                ("Book equity today", "=Inputs!B55", USDM),
                ("PV of excess returns, years 1-10", f"=SUM(C{b + 8}:L{b + 8})", USDM),
                ("Terminal ROE = Ke + 50% of starting spread", f"={rate}+0.5*({lev}-{rate})", PCT),
                ("Ending book equity, year 10", f"=L{b + 5}*(1+L{b + 3})", USDM),
                ("Terminal value = (ROE_T - Ke) x book / (Ke - g)", f"=(B{b + 12}-{rate})*B{b + 13}/({rate}-{gT})", USDM),
                ("PV of terminal value", f"=B{b + 14}*L{b + 7}", USDM),
                ("Equity value", f"=B{b + 10}+B{b + 11}+B{b + 15}", USDM),
                ("Equity value vs market cap", f"=MAX(B{b + 16},0)/Inputs!$B$13-1", PCT),
            ]
            for j, (lab, f, fmt) in enumerate(summary):
                r = b + 10 + j
                put(ws, f"A{r}", lab, bold=j in (6, 7))
                put(ws, f"B{r}", f, GREEN if "Inputs" in f else BLACK, fmt, bold=j in (6, 7))
            out_cells[s] = (f"Scenarios!B{b + 16}", f"Scenarios!B{b + 17}")

    # ------------------------------------------------------------- Sensitivity
    ws = sen
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 14
    for col in range(3, 13):
        ws.column_dimensions[CL(col)].width = 11
    rate_name = "WACC" if fcff else "cost of equity"
    put(ws, "A1", f"{meta['name']}: equity value vs market cap, {rate_name} x terminal growth (base case)").font = TITLE
    put(ws, "A2", "Each cell re-runs the 10-year base-case model with SUMPRODUCT over the helper rows below. "
                  "Blank = discount rate less than 1pp above terminal growth.")
    put(ws, "A4", "Rate shift (pp)")
    put(ws, "A5", f"Terminal g \\ {rate_name}")
    rc = [CL(3 + j) for j in range(len(GRID_RATE_SHIFTS))]
    for j, c in enumerate(rc):
        put(ws, f"{c}4", float(GRID_RATE_SHIFTS[j]), BLUE, PCT1)
        put(ws, f"{c}5", f"=Inputs!$B$65+{c}4", GREEN, PCT1, bold=True)
    hb = 16                                   # helper block start
    put(ws, f"A{hb}", "Helper rows (base case paths by terminal growth)", bold=True)
    put(ws, f"A{hb + 1}", "t")
    for i in range(10):
        put(ws, f"{CL(3 + i)}{hb + 1}", i + 1, BLUE, "0")
    T = f"$C${hb + 1}:$L${hb + 1}"
    for i, g in enumerate(GRID_G):
        r = 6 + i
        put(ws, f"B{r}", float(g), BLUE, PCT1, bold=True)
        gr, pr = hb + 2 + 2 * i, hb + 3 + 2 * i      # growth row, path row (NOPAT or book)
        put(ws, f"A{gr}", f"Growth path, g = {g:.1%}")
        put(ws, f"A{pr}", ("NOPAT" if fcff else "Beginning book") + f", g = {g:.1%}")
        for k in range(10):
            c = CL(3 + k)
            t = f"{c}${hb + 1}"
            put(ws, f"{c}{gr}", f"=IF({t}<=5,Inputs!$C$73,Inputs!$C$73+($B${r}-Inputs!$C$73)*({t}-5)/5)", GREEN, PCT)
            if fcff:
                if k == 0:
                    rev = f"Inputs!${last}$32*(1+{c}{gr})"
                    put(ws, f"{c}{pr}", f"={rev}*Inputs!$C$75*(1-Inputs!$B$45)", GREEN, USDM)
                else:
                    pcol = CL(2 + k)
                    put(ws, f"{c}{pr}", f"={pcol}{pr}*(1+{c}{gr})", BLACK, USDM)
            else:
                if k == 0:
                    put(ws, f"{c}{pr}", "=Inputs!$B$55", GREEN, USDM)
                else:
                    pcol = CL(2 + k)
                    put(ws, f"{c}{pr}", f"={pcol}{pr}*(1+{pcol}{gr})", BLACK, USDM)
        P = f"$C${pr}:$L${pr}"
        for j, c in enumerate(rc):
            rr, g_ = f"{c}$5", f"$B{r}"
            if fcff:
                R = "Inputs!$B$51"
                body = (f"SUMPRODUCT({P}*(1-(Inputs!$B$49+({g_}/({rr}+{R})-Inputs!$B$49)*{T}/10))/(1+{rr})^{T})"
                        f"+$L${pr}*(1+{g_})*(1-{g_}/({rr}+{R}))/({rr}-{g_})/(1+{rr})^10"
                        f"-Inputs!$B$52+Inputs!$B$53-Inputs!$B$54")
            else:
                roe0, roeT = "Inputs!$C$75", f"({rr}+0.5*(Inputs!$C$75-{rr}))"
                body = (f"Inputs!$B$55+SUMPRODUCT(({roe0}+({roeT}-{roe0})*{T}/10-{rr})*{P}/(1+{rr})^{T})"
                        f"+({roeT}-{rr})*$L${pr}*(1+$L${gr})/({rr}-{g_})/(1+{rr})^10")
            put(ws, f"{c}{r}", f'=IF({rr}-{g_}<0.01,"",MAX({body},0)/Inputs!$B$13-1)', BLACK, PCT)
    last_row = 6 + len(GRID_G) - 1
    ws.conditional_formatting.add(f"C6:{rc[-1]}{last_row}", ColorScaleRule(
        start_type="num", start_value=-1, start_color="E66767", mid_type="num", mid_value=0,
        mid_color="F2F2F2", end_type="num", end_value=1, end_color="199E70"))

    # ----------------------------------------------------------------- Summary
    ws = summ
    ws.column_dimensions["A"].width = 46
    for col in "BCD":
        ws.column_dimensions[col].width = 18
    put(ws, "A1", f"{meta['name']} ({d['t']}): DCF with scenarios").font = TITLE
    put(ws, "A2", f"{meta['country']} | {meta['industry']} | data as of {mkt['as_of']} | USD millions")
    header_row(ws, 4, ["Output", "Bear", "Base", "Bull"])
    put(ws, "A5", "Equity value (USD millions)")
    put(ws, "A6", "Market cap (USD millions)")
    put(ws, "A7", "Equity value vs market cap")
    put(ws, "A8", "Discount rate used")
    put(ws, "A9", "Terminal growth")
    put(ws, "A10", "Growth, years 1-5")
    for k, s in enumerate(scen):
        c = CL(2 + k)
        put(ws, f"{c}5", f"={out_cells[s][0]}", GREEN, USDM)
        put(ws, f"{c}6", "=Inputs!$B$13", GREEN, USDM)
        put(ws, f"{c}7", f"={out_cells[s][1]}", GREEN, PCT, bold=True)
        put(ws, f"{c}8", f"=Inputs!{c}74", GREEN, PCT1)
        put(ws, f"{c}9", f"=Inputs!{c}72", GREEN, PCT1)
        put(ws, f"{c}10", f"=Inputs!{c}73", GREEN, PCT1)
    put(ws, "A12", "Reverse DCF: growth the price implies (Python bisection)")
    ig = result.get("implied_growth")
    put(ws, "B12", ig if ig is not None else "n/a", BLUE, PCT1)
    put(ws, "A14", "Method", bold=True)
    method = ("FCFF = NOPAT x (1 - reinvestment rate). Reinvestment converges linearly to g / RONIC by year 10; "
              "terminal value with the Gordon formula; equity = EV - debt + cash - minority interest."
              if fcff else
              "Equity = book value + PV of (ROE - cost of equity) x beginning book. ROE fades linearly to "
              "Ke + 50% of today's spread; book grows at the retention-implied rate fading to terminal g.")
    put(ws, "A15", method)
    put(ws, "A16", "All financials converted to USD at spot FX; discount rate = US Rf + beta x mature ERP + country risk premium.")
    if d.get("note"):
        put(ws, "A17", "Data note: " + d["note"])
    put(ws, "A19", "Sources", bold=True)
    for i, s in enumerate([mkt["risk_free_source"], mkt["erp_source"], mkt["beta_source"], mkt["fx_source"],
                           "Financial statements: Yahoo Finance fundamentals-timeseries (annual)"]):
        put(ws, f"A{20 + i}", s)
    put(ws, "A26", "Not investment advice. Educational valuation model.")

    for w in wb.worksheets:
        w.sheet_view.showGridLines = False
        w.freeze_panes = None
    XL.mkdir(exist_ok=True)
    path = XL / f"DCF_{d['t'].replace('.', '_')}.xlsx"
    wb.save(path)
    return path


def main():
    mkt = json.loads((DATA / "market_inputs.json").read_text())
    meta = {r["ticker"]: r for r in csv.DictReader(open(DATA / "companies.csv"))}
    res = {r["ticker"]: r for r in json.loads((ROOT / "outputs" / "metrics.json").read_text())["rows"]}
    paths = []
    for line in open(DATA / "fundamentals.jsonl"):
        d = json.loads(line)
        paths.append(build(d, meta[d["t"]], mkt, res[d["t"]]))
    print(f"{len(paths)} workbooks written to {XL}")


if __name__ == "__main__":
    main()
