"""Gives the reserve sleeve a fair chance: wider trigger/size/composition sweep on the leading growth sleeves.
Run: PYTHONPATH=. python tools/two_sleeve_reserve_sweep.py  → data/research/reserve_sweep.json"""
import itertools
import json

import numpy as np

from vmi.research import data, strategies as S
from vmi.research.two_sleeve import MONTHS, Plan, bootstrap_paths, rolling_paths, simulate, summarise
from tools.two_sleeve_study import CONFIGS, YEARS, N_BOOT

STRATS = ["market", "trend", "momentum", "quality_momentum", "quality_momentum_trend", "lowbeta_trend"]


def plans(w):
    yield Plan(w)
    for k, cs, dd, cap in itertools.product((1, 2, 3, 5), (1.0, 0.5, 0.0), (0.15, 0.25, 0.35), (0.25, 0.5)):
        yield Plan(w, k, cs, dd, replenish_cap=cap)


def main():
    df = data.load()
    df["bond"] = df["bond"].fillna(0)
    df["mom"] = df["mom"].fillna(0)
    sub = df.loc["1963-07":].dropna(subset=["rmw", "beta_lo"])
    out = {}
    for label, real, paths_fn in (("boot_decay", S.decay(S.strategies(sub)), lambda a: bootstrap_paths(a, YEARS * MONTHS, N_BOOT)),
                                  ("hist63_raw", S.strategies(sub), lambda a: rolling_paths(a, YEARS * MONTHS))):
        real = real[STRATS]
        arr = np.column_stack([real.values, data.real(sub["bond"], sub["infl"]).values, data.real(sub["rf"], sub["infl"]).values])
        P = paths_fn(arr)
        res = {}
        for cname, (w, g) in CONFIGS.items():
            for si, sname in enumerate(STRATS):
                for plan in plans(w):
                    r = simulate(P[:, :, si], P[:, :, -2], P[:, :, -1], plan)
                    key = f"{cname}|{sname}|{plan.reserve_years}|{plan.cash_share}|{plan.dd_trigger}|{plan.replenish_cap}"
                    res[key] = summarise(r, g, YEARS)
        out[label] = res
    json.dump(out, open("data/research/reserve_sweep.json", "w"), indent=1)


if __name__ == "__main__":
    main()
