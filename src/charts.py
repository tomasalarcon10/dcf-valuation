"""Static charts (PNG + HTML) and the interactive dashboard."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import plotly.graph_objects as go

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"

BG, CARD, TEXT, TEXT2, MUTED, GRID = "#1a1a19", "#222220", "#f0efec", "#c3c2b7", "#8a8980", "#3a3936"
BLUE, ORANGE, AQUA, AMBER, PINK, VIOLET, RED = "#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#9085e9", "#e66767"
REGION_COLORS = {"North America": BLUE, "Europe": AQUA, "Asia-Pacific": AMBER,
                 "Latin America": PINK, "Middle East": VIOLET}
DIVERGING = [[0, RED], [0.5, "#4a4945"], [1, AQUA]]
FEATURED = "AAPL"


def layout(fig, title, h=620, w=1100):
    fig.update_layout(
        title=dict(text=title, font=dict(size=20, color=TEXT), x=0.02),
        paper_bgcolor=BG, plot_bgcolor=CARD, font=dict(color=TEXT2, family="Inter, Arial"),
        height=h, width=w, margin=dict(l=70, r=40, t=80, b=60),
    )
    fig.update_xaxes(gridcolor=GRID, zerolinecolor=MUTED)
    fig.update_yaxes(gridcolor=GRID, zerolinecolor=MUTED)
    return fig


def save(fig, name):
    fig.write_html(OUT / f"{name}.html", include_plotlyjs="cdn")
    fig.write_image(OUT / f"{name}.png", scale=2)


def pct(v):
    return f"{v:+.0%}"


def chart_surface(m):
    z = np.array(m["portfolio_surface"]) * 100
    x = [s * 100 for s in m["grid_rate_shifts"]]
    y = [g * 100 for g in m["grid_g"]]
    fig = go.Figure(go.Surface(
        x=x, y=y, z=z, colorscale=[[0, RED], [0.6, AMBER], [1, AQUA]],
        colorbar=dict(title="Value vs<br>market (%)", tickfont=dict(color=TEXT2)),
        hovertemplate="Rate shift %{x:+.1f} pp<br>Terminal g %{y:.1f}%<br>Value vs market %{z:+.1f}%<extra></extra>",
        contours=dict(z=dict(show=True, usecolormap=True, project_z=True)),
    ))
    fig.update_layout(scene=dict(
        xaxis=dict(title="Discount-rate shift (pp)", backgroundcolor=CARD, gridcolor=GRID, color=TEXT2),
        yaxis=dict(title="Terminal growth (%)", backgroundcolor=CARD, gridcolor=GRID, color=TEXT2),
        zaxis=dict(title="Intrinsic vs market cap (%)", backgroundcolor=CARD, gridcolor=GRID, color=TEXT2),
        camera=dict(eye=dict(x=1.7, y=-1.5, z=0.9))))
    layout(fig, f"Portfolio sensitivity: {m['summary']['companies']} companies, "
                f"market-cap weighted intrinsic value vs price", h=700)
    save(fig, "sensitivity_surface_3d")


def chart_heatmap(m, ticker=FEATURED):
    r = next(r for r in m["rows"] if r["ticker"] == ticker)
    rate = r["assumptions"]["rate"]
    cols = [f"{(rate + s) * 100:.1f}%" for s in m["grid_rate_shifts"]]
    rows = [f"{g * 100:.1f}%" for g in m["grid_g"]]
    z = np.array([[np.nan if v is None else v * 100 for v in row] for row in r["grid"]])
    text = [["" if np.isnan(v) else f"{v:+.0f}%" for v in row] for row in z]
    lim = np.nanmax(np.abs(z))
    fig = go.Figure(go.Heatmap(
        z=z, x=cols, y=rows, text=text, texttemplate="%{text}", zmid=0, zmin=-lim, zmax=lim,
        colorscale=DIVERGING, xgap=2, ygap=2,
        colorbar=dict(title="Value vs<br>price (%)"),
        hovertemplate="WACC %{x}<br>Terminal g %{y}<br>%{z:+.1f}% vs market<extra></extra>"))
    layout(fig, f"{r['name']} ({ticker}): intrinsic value vs market cap, WACC x terminal growth", h=560)
    fig.update_xaxes(title="WACC")
    fig.update_yaxes(title="Terminal growth")
    save(fig, "sensitivity_heatmap_featured")


def chart_ranges(m):
    rows = sorted(m["rows"], key=lambda r: r["upside"]["base"])
    cap = lambda v: min(v, 3.0) * 100
    names = [r["ticker"] for r in rows]
    fig = go.Figure()
    for r in rows:
        fig.add_trace(go.Scatter(x=[cap(r["upside"]["bear"]), cap(r["upside"]["bull"])], y=[r["ticker"]] * 2,
                                 mode="lines", line=dict(color=REGION_COLORS[r["region"]], width=4),
                                 showlegend=False, hoverinfo="skip"))
    for reg, col in REGION_COLORS.items():
        sub = [r for r in rows if r["region"] == reg]
        fig.add_trace(go.Scatter(
            x=[cap(r["upside"]["base"]) for r in sub], y=[r["ticker"] for r in sub], mode="markers",
            marker=dict(color=TEXT, size=7, line=dict(color=col, width=2)), name=reg,
            customdata=[[r["name"], pct(r["upside"]["bear"]), pct(r["upside"]["base"]), pct(r["upside"]["bull"])] for r in sub],
            hovertemplate="%{customdata[0]}<br>Bear %{customdata[1]} | Base %{customdata[2]} | Bull %{customdata[3]}<extra></extra>"))
    fig.add_vline(x=0, line=dict(color=MUTED, dash="dot"))
    layout(fig, "Bear / base / bull: intrinsic equity value vs market cap (capped at +300%)", h=1500, w=1000)
    fig.update_yaxes(categoryorder="array", categoryarray=names, tickfont=dict(size=10))
    fig.update_xaxes(title="Value vs market cap (%)", ticksuffix="%")
    fig.update_layout(legend=dict(orientation="h", y=1.02, x=0))
    save(fig, "scenario_ranges")


def chart_implied_growth(m):
    rows = [r for r in m["rows"] if r["implied_growth"] is not None]
    fig = go.Figure()
    for reg, col in REGION_COLORS.items():
        sub = [r for r in rows if r["region"] == reg]
        if not sub:
            continue
        fig.add_trace(go.Scatter(
            x=[r["assumptions"]["g_hist"] * 100 for r in sub], y=[r["implied_growth"] * 100 for r in sub],
            mode="markers+text", text=[r["ticker"] for r in sub], textposition="top center",
            textfont=dict(size=9, color=TEXT2), marker=dict(size=10, color=col, line=dict(color=BG, width=2)),
            name=reg, hovertemplate="%{text}<br>Historical %{x:.1f}%<br>Implied %{y:.1f}%<extra></extra>"))
    lim = [-20, 45]
    fig.add_trace(go.Scatter(x=lim, y=lim, mode="lines", line=dict(color=MUTED, dash="dot"),
                             name="Implied = historical"))
    layout(fig, "Reverse DCF: 5-year revenue growth the price implies vs historical growth", h=700)
    fig.update_xaxes(title="Historical revenue CAGR (%)", range=lim)
    fig.update_yaxes(title="Market-implied growth, years 1-5 (%)", range=[-10, 45])
    save(fig, "implied_vs_historical_growth")


def chart_rate(m):
    fig = go.Figure()
    for reg, col in REGION_COLORS.items():
        sub = [r for r in m["rows"] if r["region"] == reg]
        fig.add_trace(go.Scatter(
            x=[r["assumptions"]["rate"] * 100 for r in sub], y=[min(r["upside"]["base"], 2.0) * 100 for r in sub],
            mode="markers", name=reg, text=[r["ticker"] for r in sub],
            marker=dict(size=[8 + 30 * (r["market_cap_usd"] / 5.2e12) ** 0.5 for r in sub], color=col,
                        line=dict(color=BG, width=2), opacity=0.9),
            hovertemplate="%{text}<br>Rate %{x:.1f}%<br>Base %{y:+.0f}%<extra></extra>"))
    fig.add_hline(y=0, line=dict(color=MUTED, dash="dot"))
    layout(fig, "Discount rate vs base-case value gap (bubble = market cap, capped at +200%)", h=620)
    fig.update_xaxes(title="WACC or cost of equity (%)")
    fig.update_yaxes(title="Base value vs market cap (%)", ticksuffix="%")
    save(fig, "rate_vs_upside")


DASH = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DCF with scenarios - interactive dashboard</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
:root{--bg:#1a1a19;--card:#222220;--text:#f0efec;--text2:#c3c2b7;--muted:#8a8980;--grid:#3a3936}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:Inter,Arial,sans-serif}
header{padding:22px 28px 6px}h1{margin:0;font-size:24px}header p{color:var(--muted);margin:6px 0 0;font-size:13px}
.bar{display:flex;gap:12px;flex-wrap:wrap;align-items:center;padding:12px 28px}
select,input{background:var(--card);color:var(--text);border:1px solid var(--grid);border-radius:8px;padding:8px 10px;font-size:14px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;padding:6px 28px}
.kpi{background:var(--card);border-radius:12px;padding:14px}.kpi .l{color:var(--muted);font-size:12px}.kpi .v{font-size:22px;margin-top:6px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;padding:14px 28px;align-content:start}
.card{background:var(--card);border-radius:12px;padding:10px}
.full{grid-column:1/-1}@media(max-width:900px){.grid{grid-template-columns:1fr}}
table{width:100%;border-collapse:collapse;font-size:12.5px}th,td{padding:6px 8px;border-bottom:1px solid var(--grid);text-align:right}
th{color:var(--muted);cursor:pointer;position:sticky;top:0;background:var(--card)}td:nth-child(-n+3),th:nth-child(-n+3){text-align:left}
tr:hover td{background:#2b2b28}.pos{color:#199e70}.neg{color:#e66767}.tbl{max-height:520px;overflow:auto}
.note{color:var(--muted);font-size:12px;padding:0 28px 24px}
</style></head><body>
<header><h1>DCF with scenarios: __N__ companies</h1>
<p>FCFF DCF for operating companies, excess-return model for banks, insurers and holding companies. All values in USD. Data as of __ASOF__.</p></header>
<div class="bar"><label>Company <select id="sel"></select></label>
<label>Region <select id="reg"><option value="">All</option></select></label></div>
<div class="kpis" id="kpis"></div>
<div class="grid">
<div class="card"><div id="heat" style="height:420px"></div></div>
<div class="card"><div id="surf" style="height:420px"></div></div>
<div class="card"><div id="proj" style="height:400px"></div></div>
<div class="card"><div id="scen" style="height:400px"></div></div>
<div class="card full"><div class="tbl"><table id="tbl"></table></div></div>
</div>
<p class="note">Value vs market = intrinsic equity value / market capitalisation - 1. Sensitivity grids move the discount rate by -2 to +2 pp and terminal growth from 1% to 4%. Not investment advice.</p>
<script>
const D=__DATA__;
const C={bg:'#1a1a19',card:'#222220',text:'#f0efec',text2:'#c3c2b7',muted:'#8a8980',grid:'#3a3936',red:'#e66767',aqua:'#199e70',blue:'#3987e5',amber:'#c98500',orange:'#d95926'};
const pc=v=>v==null?'n/a':(v>=0?'+':'')+(v*100).toFixed(0)+'%';
const p1=v=>v==null?'n/a':(v*100).toFixed(1)+'%';
const bn=v=>'$'+(v/1e9).toFixed(0)+'B';
const L=(t,x,y)=>({title:{text:t,font:{size:14,color:C.text}},paper_bgcolor:C.card,plot_bgcolor:C.card,font:{color:C.text2,size:11},margin:{l:55,r:20,t:40,b:45},xaxis:{title:x,gridcolor:C.grid},yaxis:{title:y,gridcolor:C.grid}});
const cfg={displayModeBar:false,responsive:true};
const sel=document.getElementById('sel'),reg=document.getElementById('reg');
[...new Set(D.rows.map(r=>r.region))].sort().forEach(r=>reg.add(new Option(r,r)));
function fill(){const cur=sel.value;sel.innerHTML='';D.rows.filter(r=>!reg.value||r.region===reg.value).sort((a,b)=>a.name.localeCompare(b.name)).forEach(r=>sel.add(new Option(r.name+' ('+r.ticker+')',r.ticker)));if([...sel.options].some(o=>o.value===cur))sel.value=cur;}
function draw(){const r=D.rows.find(x=>x.ticker===sel.value);if(!r)return;const a=r.assumptions,eq=r.model==='equity';
const k=[['Market cap',bn(r.market_cap_usd)],[eq?'Cost of equity':'WACC',p1(a.rate)],['Bear',pc(r.upside.bear)],['Base',pc(r.upside.base)],['Bull',pc(r.upside.bull)],
 eq?['ROE (latest 2y)',p1(a.roe0)]:['Price-implied growth',p1(r.implied_growth)],['Model',eq?'Excess return':'FCFF DCF']];
document.getElementById('kpis').innerHTML=k.map(([l,v])=>`<div class="kpi"><div class="l">${l}</div><div class="v ${v.startsWith('+')?'pos':v.startsWith('-')?'neg':''}">${v}</div></div>`).join('');
const xs=D.grid_rate_shifts.map(s=>((a.rate+s)*100).toFixed(1)+'%'),ys=D.grid_g.map(g=>(g*100).toFixed(1)+'%');
const z=r.grid.map(row=>row.map(v=>v==null?null:v*100));let m=Math.max(...z.flat().filter(v=>v!=null).map(Math.abs));
Plotly.react('heat',[{type:'heatmap',z,x:xs,y:ys,zmid:0,zmin:-m,zmax:m,xgap:2,ygap:2,colorscale:[[0,C.red],[0.5,'#4a4945'],[1,C.aqua]],
 text:z.map(row=>row.map(v=>v==null?'':(v>=0?'+':'')+v.toFixed(0)+'%')),texttemplate:'%{text}',hovertemplate:'Rate %{x}<br>g %{y}<br>%{z:+.1f}%<extra></extra>',colorbar:{ticksuffix:'%'}}],
 Object.assign(L('Sensitivity: '+(eq?'cost of equity':'WACC')+' x terminal growth',eq?'Cost of equity':'WACC','Terminal growth'),{xaxis:{type:'category',title:eq?'Cost of equity':'WACC'},yaxis:{type:'category',title:'Terminal growth'}}),cfg);
Plotly.react('surf',[{type:'surface',z,x:D.grid_rate_shifts.map(s=>(a.rate+s)*100),y:D.grid_g.map(g=>g*100),colorscale:[[0,C.red],[0.6,C.amber],[1,C.aqua]],showscale:false,
 hovertemplate:'Rate %{x:.1f}%<br>g %{y:.1f}%<br>%{z:+.1f}%<extra></extra>'}],
 Object.assign(L('3D value surface','',''),{scene:{xaxis:{title:'Rate %',color:C.text2,gridcolor:C.grid},yaxis:{title:'g %',color:C.text2,gridcolor:C.grid},zaxis:{title:'vs market %',color:C.text2,gridcolor:C.grid},camera:{eye:{x:1.9,y:-1.8,z:1.0}},aspectmode:'cube'},margin:{l:0,r:0,t:40,b:0}}),cfg);
const yrs=[...Array(10).keys()].map(i=>'Y'+(i+1));
if(eq){Plotly.react('proj',[{type:'bar',x:yrs,y:r.projection.excess.map(v=>v/1e9),marker:{color:C.blue},name:'Excess return',hovertemplate:'%{x}: $%{y:.1f}B<extra></extra>'},
 {type:'scatter',x:yrs,y:r.projection.roe.map(v=>v*100),yaxis:'y2',mode:'lines+markers',line:{color:C.amber,width:2},name:'ROE %'}],
 Object.assign(L('Base case: excess return on book (USD B) and ROE','','USD B'),{yaxis2:{overlaying:'y',side:'right',title:'ROE %',gridcolor:'rgba(0,0,0,0)'},legend:{orientation:'h',y:-0.12}}),cfg);}
else{Plotly.react('proj',[{type:'bar',x:yrs,y:r.projection.fcff.map(v=>v/1e9),marker:{color:C.blue},name:'FCFF',hovertemplate:'%{x}: $%{y:.1f}B<extra></extra>'},
 {type:'scatter',x:yrs,y:r.projection.growth.map(v=>v*100),yaxis:'y2',mode:'lines+markers',line:{color:C.amber,width:2},name:'Revenue growth %'}],
 Object.assign(L('Base case: free cash flow to the firm (USD B) and growth','','USD B'),{yaxis2:{overlaying:'y',side:'right',title:'Growth %',gridcolor:'rgba(0,0,0,0)'},legend:{orientation:'h',y:-0.12}}),cfg);}
const sc=['bear','base','bull'];
Plotly.react('scen',[{type:'bar',x:['Bear','Base','Bull','Market'],y:[...sc.map(s=>Math.max(r.equity_value[s],0)/1e9),r.market_cap_usd/1e9],
 marker:{color:[C.red,C.blue,C.aqua,C.muted]},text:[...sc.map(s=>pc(r.upside[s])),''],textposition:'outside',hovertemplate:'%{x}: $%{y:.0f}B<extra></extra>'}],
 L('Equity value by scenario vs market cap (USD B)','','USD B'),cfg);}
let sortK='base',dir=-1;
function table(){const rows=D.rows.filter(r=>!reg.value||r.region===reg.value).slice().sort((a,b)=>{const g=r=>sortK==='base'?r.upside.base:sortK==='rate'?r.assumptions.rate:sortK==='mc'?r.market_cap_usd:sortK==='ig'?(r.implied_growth??-9):r[sortK];const A=g(a),B=g(b);return (A>B?1:A<B?-1:0)*dir;});
const h=[['ticker','Ticker'],['name','Company'],['region','Region'],['mc','Market cap'],['rate','Rate'],['bear','Bear'],['base','Base'],['bull','Bull'],['ig','Implied g']];
document.getElementById('tbl').innerHTML='<tr>'+h.map(([k,t])=>`<th data-k="${k}">${t}</th>`).join('')+'</tr>'+rows.map(r=>`<tr data-t="${r.ticker}"><td>${r.ticker}</td><td>${r.name}</td><td>${r.region}</td><td>${bn(r.market_cap_usd)}</td><td>${p1(r.assumptions.rate)}</td>`+
 ['bear','base','bull'].map(s=>`<td class="${r.upside[s]>=0?'pos':'neg'}">${pc(r.upside[s])}</td>`).join('')+`<td>${p1(r.implied_growth)}</td></tr>`).join('');
document.querySelectorAll('#tbl th').forEach(th=>th.onclick=()=>{const k=th.dataset.k;dir=sortK===k?-dir:-1;sortK=k;table();});
document.querySelectorAll('#tbl tr[data-t]').forEach(tr=>tr.onclick=()=>{sel.value=tr.dataset.t;draw();window.scrollTo({top:0,behavior:'smooth'});});}
reg.onchange=()=>{fill();draw();table();};sel.onchange=draw;fill();sel.value='__FEAT__';draw();table();
</script></body></html>"""


def dashboard(m):
    slim = dict(grid_rate_shifts=m["grid_rate_shifts"], grid_g=m["grid_g"], rows=[
        {k: r[k] for k in ("ticker", "name", "region", "model", "market_cap_usd", "equity_value",
                           "upside", "grid", "projection", "implied_growth")}
        | {"assumptions": {k: r["assumptions"][k] for k in ("rate", "roe0") if k in r["assumptions"]}}
        for r in m["rows"]])
    html = (DASH.replace("__DATA__", json.dumps(slim, separators=(",", ":"), default=float))
            .replace("__N__", str(len(m["rows"]))).replace("__ASOF__", m["market"]["as_of"])
            .replace("__FEAT__", FEATURED))
    (ROOT / "dashboard.html").write_text(html)


def main():
    m = json.loads((OUT / "metrics.json").read_text())
    chart_surface(m)
    chart_heatmap(m)
    chart_ranges(m)
    chart_implied_growth(m)
    chart_rate(m)
    dashboard(m)
    print("charts + dashboard written")


if __name__ == "__main__":
    main()
