"""Prints the tables used in docs/TWO_SLEEVE_RESEARCH.md. Run the two study scripts first.
PYTHONPATH=. python tools/two_sleeve_report.py"""
import json

import numpy as np

from tools.two_sleeve_study import CONFIGS, YEARS
from vmi.research import data, strategies as S
from vmi.research.two_sleeve import MONTHS, Plan, bootstrap_paths, rolling_paths, simulate, summarise, required_real_return

TOL = {"growth": 0.03, "balanced": 0.05, "withdrawal_max": 0.08}      # P(target) we may give up for lower risk
RUIN_CAP = {"growth": 0.03, "balanced": 0.05, "withdrawal_max": 0.10}
R = json.load(open("data/research/results.json"))
W = json.load(open("data/research/reserve_sweep.json"))


def pool(cfg, ds="boot_decay"):
    rows = []
    for k, v in R[ds].items():
        c, s, ky, cs, dd = k.split("|")
        if c == cfg:
            rows.append((s, float(ky), float(cs), float(dd), 0.25, v))
    for k, v in W[ds].items():
        c, s, ky, cs, dd, cap = k.split("|")
        if c == cfg and float(ky) > 0:
            rows.append((s, float(ky), float(cs), float(dd), float(cap), v))
    return rows


def pick(cfg):
    rows = pool(cfg)
    ok = [r for r in rows if r[5]["p_ruin"] <= RUIN_CAP[cfg]] or sorted(rows, key=lambda r: r[5]["p_ruin"])[:50]
    best = max(r[5]["p_target"] for r in ok)
    near = [r for r in ok if r[5]["p_target"] >= best - TOL[cfg]]
    near.sort(key=lambda r: (r[5]["capital_mdd_p50"] + 0.01 * r[5]["underwater_years_p90"], r[1]))
    return best, near[:3]


def line(r):
    s, k, cs, dd, cap, v = r
    return (f"{s:24} reserve={k:g}y cash={cs:.1f} trig={dd:.2f} | P(target)={v['p_target']:.2f} ruin={v['p_ruin']:.3f} "
            f"real-growth={v['p_real_growth']:.2f} CAGR p10/50/90={v['cagr_p10']:.3f}/{v['cagr_p50']:.3f}/{v['cagr_p90']:.3f} "
            f"MDD p50/90={v['mdd_p50']:.2f}/{v['mdd_p90']:.2f} capMDD={v['capital_mdd_p50']:.2f} underwater90={v['underwater_years_p90']:.1f}y "
            f"reserve-use={v['reserve_use']:.2f} neg-years={v['neg_years']:.2f}")


for cfg in CONFIGS:
    best, near = pick(cfg)
    print(f"\n### {cfg}: best feasible P(target)={best:.2f}; tolerance {TOL[cfg]}")
    for r in near:
        print("  ", line(r))
    for ds in ("hist63_raw",):
        for r in near[:1]:
            s, k, cs, dd, cap, v = r
            key = f"{cfg}|{s}|{k:g}|{cs}|{dd}" if k else f"{cfg}|{s}|0.0|1.0|0.1"
            h = R[ds].get(key) or R[ds].get(f"{cfg}|{s}|{int(k)}|{cs}|{dd}")
            if h:
                print(f"   cross-check {ds}: P(target)={h['p_target']:.2f} ruin={h['p_ruin']:.3f} CAGR p10/50={h['cagr_p10']:.3f}/{h['cagr_p50']:.3f} MDD90={h['mdd_p90']:.2f}")
    print("   no-reserve market:", {k: round(v, 3) for k, v in R['boot_decay'][f'{cfg}|market|0.0|1.0|0.1'].items() if k in ('p_target', 'p_ruin', 'p_real_growth', 'cagr_p50', 'mdd_p90', 'capital_mdd_p50')})

# --- strategy table (k=0, 100% growth sleeve)
df = data.load(); df["bond"] = df["bond"].fillna(0); df["mom"] = df["mom"].fillna(0)
sub = df.loc["1963-07":].dropna(subset=["rmw", "beta_lo"])
raw, dec = S.strategies(sub), S.decay(S.strategies(sub))
print("\nstrategy stats 1963-2023 (real): raw CAGR | decayed CAGR | vol | worst drawdown")
for c in raw.columns:
    idx = (1 + dec[c]).cumprod()
    print(f"{c:24} {((1+raw[c]).prod()**(12/len(raw))-1):.3f} | {((1+dec[c]).prod()**(12/len(dec))-1):.3f} | {raw[c].std()*12**.5:.3f} | {(1-idx/idx.cummax()).max():.2f}")

# --- alpha sweep on the market series (bootstrap), no reserve
bond = data.real(sub["bond"], sub["infl"]).values; cash = data.real(sub["rf"], sub["infl"]).values
mkt = real = raw["market"].values
print("\nalpha sweep (market + constant real alpha, 100% growth sleeve, no reserve): P(target) / ruin")
for a in (0.0, 0.01, 0.02, 0.03, 0.04):
    arr = np.column_stack([mkt + a / 12, bond, cash])
    P = bootstrap_paths(arr, YEARS * MONTHS, 3000)
    out = []
    for cfg, (w, g) in CONFIGS.items():
        r = simulate(P[:, :, 0], P[:, :, 1], P[:, :, 2], Plan(w))
        s = summarise(r, g, YEARS)
        out.append(f"{cfg}: {s['p_target']:.2f}/{s['p_ruin']:.2f}")
    print(f"alpha {a:.0%}: " + "  ".join(out))
print("\nrequired constant real return:", {k: round(v, 4) for k, v in R['required_real_return'].items()})

# --- decay sensitivity for quality_momentum_trend and trend
print("\ndecay sensitivity (keep fraction of historical excess), no reserve, P(target)/ruin per config")
for keep in (0.0, 0.25, 0.5, 1.0):
    d = S.decay(S.strategies(sub), keep)
    for s in ("quality_momentum_trend", "quality_momentum", "lowbeta_trend"):
        arr = np.column_stack([d[s].values, bond, cash])
        P = bootstrap_paths(arr, YEARS * MONTHS, 3000)
        out = []
        for cfg, (w, g) in CONFIGS.items():
            sm = summarise(simulate(P[:, :, 0], P[:, :, 1], P[:, :, 2], Plan(w)), g, YEARS)
            out.append(f"{cfg}: {sm['p_target']:.2f}/{sm['p_ruin']:.2f}")
        print(f"keep={keep:.2f} {s:24} " + "  ".join(out))

# --- horizon sensitivity (20/40y) for baseline market vs quality_momentum_trend decayed
print("\nhorizon sensitivity P(target)/ruin, no reserve, decayed strategies")
for yrs in (20, 40):
    for s in ("market", "quality_momentum_trend"):
        arr = np.column_stack([dec[s].values, bond, cash])
        P = bootstrap_paths(arr, yrs * MONTHS, 3000)
        out = []
        for cfg, (w, g) in CONFIGS.items():
            sm = summarise(simulate(P[:, :, 0], P[:, :, 1], P[:, :, 2], Plan(w)), g, yrs)
            out.append(f"{cfg}: {sm['p_target']:.2f}/{sm['p_ruin']:.2f}")
        print(f"{yrs}y {s:24} " + "  ".join(out))

# --- historical stress starts (raw, 1963 sample), worst cohorts
print("\nhistorical stress starts, final real value (start 1.0), plan = no reserve")
arr_cols = {s: raw[s].values for s in ("market", "trend", "quality_momentum_trend", "lowbeta_trend")}
for s, x in arr_cols.items():
    arr = np.column_stack([x, bond, cash])
    P = rolling_paths(arr, 360)
    yrs = [1963 + i for i in range(P.shape[0])]
    row = []
    for cfg, (w, g) in CONFIGS.items():
        r = simulate(P[:, :, 0], P[:, :, 1], P[:, :, 2], Plan(w))
        worst = int(np.argmin(r["final"]))
        row.append(f"{cfg}: worst start {yrs[worst]} final {r['final'][worst]:.2f}, ruined starts {int(r['ruined'].sum())}/{len(yrs)}")
    print(f"{s:24} " + " | ".join(row))
