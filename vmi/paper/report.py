"""Self-contained, printable reports from effective-date portfolio accounting."""
from datetime import date
from html import escape

from vmi.paper import journal


CSS = '''
:root{color-scheme:light;font:16px/1.55 system-ui,sans-serif;color:#19283c;background:#eaf0f6}
body{max-width:1000px;margin:1.5rem auto;padding:0 1rem}main{background:white;padding:clamp(1.1rem,4vw,3rem);border-radius:16px}
header{border-top:6px solid #155b80;padding-top:1.4rem}h1,h2,h3,p{margin:.35rem 0 .85rem}h1{font-size:2.5rem;line-height:1.08}
h2{border-top:1px solid #d7e1ec;padding-top:1rem;margin-top:1.7rem}.muted{color:#52637a}.tag{font-size:.78rem;letter-spacing:.13em;text-transform:uppercase;color:#155b80;font-weight:750}
.kpis,.stocks{display:grid;gap:.7rem;grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}.kpi,article{border:1px solid #d7e1ec;padding:.8rem;border-radius:8px}.kpi strong{display:block;font-size:1.3rem}.stocks{grid-template-columns:repeat(auto-fit,minmax(235px,1fr))}
figure{margin:1rem 0}.legend{display:flex;flex-wrap:wrap;gap:1rem;font-size:.9rem}.legend i{display:inline-block;width:.9rem;height:.2rem;margin-right:.35rem;vertical-align:middle}
svg{width:100%;height:auto;display:block}table{border-collapse:collapse;width:100%;margin-top:.7rem;font-size:.9rem}th,td{padding:.35rem .5rem;border-bottom:1px solid #d7e1ec;text-align:left}td:not(:first-child),th:not(:first-child){text-align:right}
.scroll{overflow:auto}a{color:#155b80}button,.save{font:inherit;font-weight:650;cursor:pointer;border:1px solid #b7c9dc;background:white;border-radius:8px;color:#155b80;padding:.45rem .75rem;text-decoration:none}.toolbar{display:flex;gap:.7rem;margin-bottom:.65rem}
@media print{body,main{background:white;margin:0;padding:0;max-width:none} .toolbar{display:none} h2,h3{break-after:avoid} figure,article,.kpis,tr{break-inside:avoid}thead{display:table-header-group}}
'''


def _money(value):
    return f"{'−' if value < 0 else ''}${abs(value):,.2f}"


def _pct(value):
    return f"{value:.2%}" if value is not None else "Not available"


def _plot(days, series, *, percentage=False, compact=False):
    """Inline SVG (no assets, JavaScript, or chart service required in exported files)."""
    vals = [v for _, _, ys in series for v in ys if v is not None]
    if not vals:
        return '<p class="muted">No eligible daily prices for this chart.</p>'
    width, height = (350, 132) if compact else (800, 218)
    left, top, right, bottom = 68, 12, width - 54, height - 33
    lo, hi = min(vals), max(vals)
    if hi == lo:
        padding = max(abs(lo) * .02, .005 if percentage else 1)
        lo, hi = lo - padding, hi + padding
    fmt = _pct if percentage else _money
    y = lambda v: bottom - (v - lo) / (hi - lo) * (bottom - top)
    x = lambda i: (right + left) / 2 if len(days) == 1 else left + i / (len(days) - 1) * (right - left)
    grid = []
    for i in range(3 if compact else 5):
        tick = lo + (hi - lo) * i / (2 if compact else 4)
        py = y(tick)
        grid.append(f'<path d="M{left} {py:.2f}H{right}" stroke="#d7e1ec"/><text x="{left-6}" y="{py+4:.2f}" text-anchor="end">{fmt(tick)}</text>')
    for i in sorted({0, len(days) - 1} | ({len(days) // 2} if not compact and len(days) > 2 else set())):
        grid.append(f'<text x="{x(i):.2f}" y="{height-10}" text-anchor="middle">{escape(days[i])}</text>')
    lines = []
    for _, color, ys in series:
        # Keep extrema and endpoints rather than dropping one-day drawdowns when reducing long charts.
        indexed = [(i, v) for i, v in enumerate(ys) if v is not None]
        if len(indexed) > 800:
            size = (len(indexed) + 399) // 400
            buckets = (indexed[i:i + size] for i in range(0, len(indexed), size))
            sample = {indexed[0], indexed[-1]}
            for bucket in buckets:
                sample.update((min(bucket, key=lambda p: p[1]), max(bucket, key=lambda p: p[1])))
            indexed = sorted(sample)
        if not indexed:
            continue
        if len(indexed) == 1:
            i, v = indexed[0]
            lines.append(f'<circle cx="{x(i):.2f}" cy="{y(v):.2f}" r="3" fill="{color}"/>')
        else:
            coords = ' '.join(f'{x(i):.2f},{y(v):.2f}' for i, v in indexed)
            lines.append(f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="2"/>')
    caption = ''.join(f'<span><i style="background:{color}"></i>{escape(label)}</span>' for label, color, _ in series)
    return (f'<figure><figcaption class="legend">{caption}</figcaption><svg role="img" aria-label="Time series chart" '
            f'viewBox="0 0 {width} {height}" fill="#52637a" font-size="11">{"".join(grid)}{"".join(lines)}</svg></figure>')


def build(pid: int, start: date | None, end: date | None, benchmark: str | None = None, *, save_url: str = "") -> str:
    report = journal.history(pid, start, end, include_performance=True, benchmark=benchmark)
    points, stocks = report["points"], report["stocks"]
    days = [p["day"] for p in points]
    name = escape(report["portfolio_name"])
    last, opening = points[-1], report["opening_equity"]
    delta = last["equity"] - opening
    change = "rose" if delta > 0 else "fell" if delta < 0 else "was unchanged"
    movement = f"{change} by {_money(abs(delta))}" if delta else change
    kpis = [("Ending equity", _money(last["equity"])), ("Change in equity", _money(delta)),
            ("Period return", _pct(report["period_return"])), ("Maximum drawdown", _pct(report["max_drawdown"]))]
    cards = ''.join(f'<div class="kpi">{label}<strong>{value}</strong></div>' for label, value in kpis)
    equity = [("Account equity", "#155b80", [p["equity"] for p in points])]
    returns = [("Portfolio return", "#155b80", [p["equity"] / opening - 1 if opening > 0 else None for p in points])]
    bm = report["benchmark"]
    benchmark_text = ""
    if bm:
        equity.append((f'100% {bm["symbol"]}', '#9c4518', bm["value"]))
        returns.append((f'{bm["symbol"]} price return', '#9c4518', bm["price_return"]))
        benchmark_text = (f'<p>The selected benchmark is {escape(bm["symbol"])}. Its price-only return was '
                          f'{_pct(bm["price_return"][-1])}; baseline close: {escape(bm["base_day"] or "unavailable")}. '
                          f'Investing the opening balance of {_money(bm["starting_value"])} entirely in it '
                          f'would end at {_money(bm["value"][-1])}, excluding dividends and fees.</p>')
    risk_chart = _plot(days, [("Drawdown from peak", "#9c4518", [-p["drawdown"] for p in points])], percentage=True)
    holdings = last["positions"]
    stock_exposure = sum(abs(p["market_value"]) for p in holdings if p["sec_type"] == "STK")
    option_exposure = last["gross_exposure"] - stock_exposure
    allocation_sentence = (f'Cash was {_money(last["cash"])} and net market value was {_money(last["market_value"])}. '
                           f'Gross exposure was {_money(last["gross_exposure"])}: {_money(stock_exposure)} in stocks and '
                           f'{_money(option_exposure)} in options, counting both long and short exposure as positive.')
    if holdings and last["gross_exposure"]:
        leading = holdings[:3]
        share = sum(abs(p["market_value"]) for p in leading) / last["gross_exposure"]
        allocation_sentence += f' The largest {len(leading)} positions accounted for {_pct(share)} of gross exposure.'
    hold_rows = ''.join(f'<tr><td>{escape(p["key"])}</td><td>{p["qty"]:,.4g}</td><td>{_money(p["market_value"])}</td>'
                        f'<td>{_pct(p["weight"])}</td><td>{escape(p["price_source"])}</td></tr>' for p in holdings)
    ordered = sorted(stocks, key=lambda s: s["pnl"][-1], reverse=True)
    movers = [s for s in ordered if s["pnl"][-1] != 0]
    contributors = ''
    if movers and movers[0]["pnl"][-1] > 0:
        contributors += f'{escape(movers[0]["symbol"])} added the most among stocks ({_money(movers[0]["pnl"][-1])}). '
    if movers and movers[-1]["pnl"][-1] < 0:
        contributors += f'{escape(movers[-1]["symbol"])} detracted the most ({_money(movers[-1]["pnl"][-1])}). '
    stock_panels = []
    for s in ordered:
        label = escape(s["symbol"])
        stock_panels.append(f'<article><h3>{label}</h3><p>Price return <b>{_pct(s["price_return"][-1])}</b> · '
                            f'Account contribution <b>{_money(s["pnl"][-1])}</b><br><small>Baseline close: {escape(s["base_day"] or "unavailable")}</small></p>'
                            + _plot(days, [("Price return", "#155b80", s["price_return"])], percentage=True, compact=True) + '</article>')
    amounts = [s["pnl"][-1] for s in ordered]
    stock_total = sum(amounts)
    residual = delta - stock_total
    toolbar = (f'<div class="toolbar"><button onclick="window.print()">Print / Save as PDF</button>'
               f'<a class="save" href="{escape(save_url, quote=True)}">Download HTML</a></div>') if save_url else ''
    return f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{name} · Portfolio report</title><style>{CSS}</style><body>{toolbar}<main><header>
<p class="tag">VMI Toolkit · Paper portfolio report</p><h1>{name}</h1><p class="muted">{days[0]} through {days[-1]} · New York time</p></header>
<section><h2>Executive summary</h2><div class="kpis">{cards}</div>
<p>Over this period, equity {movement}, from {_money(opening)} to {_money(last['equity'])}. There were {report['range_trades']} ledger transactions and {_money(report['range_fees'])} in recorded fees.</p></section>
<section><h2>Performance and risk</h2><p>Equity is your cash plus the net marked value of positions. The drawdown chart measures how far equity fell below its running peak in this period.</p>
{_plot(days, equity)}{_plot(days, returns, percentage=True)}{benchmark_text}{risk_chart}</section>
<section><h2>Exposure and holdings</h2><p>{allocation_sentence}</p>
{('<div class="scroll"><table><thead><tr><th>Holding</th><th>Quantity</th><th>Net value</th><th>Equity weight</th><th>Mark source</th></tr></thead><tbody>' + hold_rows + '</tbody></table></div>') if hold_rows else '<p>No open positions at the end of this range.</p>'}</section>
<section><h2>Stock performance and contribution</h2><p>{contributors}Stock positions contributed {_money(stock_total)} in total. The remaining {_money(residual)} of the account change is not in the stock lines; it can include option positions and associated cash flows.</p>
<p>Stock charts show price moves, not your investment returns. The dollar contribution includes position value changes and actual buy/sell cash flows and fees. It includes positions sold during the period.</p>
<div class="stocks">{''.join(stock_panels) or '<p>No stocks were held or traded during the range.</p>'}</div></section>
<section><h2>How to read this report</h2><p>Positions and cash are replayed from effective trade dates, including admin corrections and Backdater fills. Stock prices use eligible daily closes; recorded marks may be used where applicable. Where prices are unavailable, account valuations may use cost: {report['estimated_days']} day(s) in this range include a cost estimate.</p>
<p>Portfolio period return uses equity immediately before the range. Stocks and benchmarks use the last eligible close before the range, or the first available close in the range; dividends are not included in these comparison lines. A benchmark is context, not a recommended investment.</p></section>
</main></body></html>'''
