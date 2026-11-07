"""Two-sleeve study runner. Writes data/research/results.json and prints the top plans per configuration.
Run: PYTHONPATH=. python tools/two_sleeve_study.py"""
import itertools
import json
import sys

import numpy as np

from vmi.research import data, strategies as S
from vmi.research.two_sleeve import (MONTHS, Plan, bootstrap_paths, required_real_return, rolling_paths, simulate,
                                     summarise)

CONFIGS = {"growth": (0.04, 0.05), "balanced": (0.055, 0.03), "withdrawal_max": (0.075, 0.01)}
YEARS = 30
N_BOOT = 2000


def grid(w):
    out = [Plan(w)]
    for k, cs, dd in itertools.product((1, 2, 3, 4, 5), (1.0, 0.5), (0.10, 0.20)):
        out.append(Plan(w, k, cs, dd))
    return out


def run(real_df, bond, cash, paths_fn, label):
    names = list(real_df.columns)
    arr = np.column_stack([real_df[names].values, bond.values, cash.values])
    P = paths_fn(arr)
    res = {}
    for ci, (cname, (w, g)) in enumerate(CONFIGS.items()):
        for si, sname in enumerate(names):
            for plan in grid(w):
                r = simulate(P[:, :, si], P[:, :, -2], P[:, :, -1], plan)
                res[f"{cname}|{sname}|{plan.reserve_years}|{plan.cash_share}|{plan.dd_trigger}"] = summarise(r, g, YEARS)
        print(label, cname, "done", file=sys.stderr)
    return res


def main():
    df = data.load()
    df["bond"] = df["bond"].fillna(0)
    df["mom"] = df["mom"].fillna(0)
    sub = df.loc["1963-07":].dropna(subset=["rmw", "beta_lo"])
    real63 = S.strategies(sub)
    bond63 = data.real(sub["bond"], sub["infl"])
    cash63 = data.real(sub["rf"], sub["infl"])
    out = {"required_real_return": {k: required_real_return(w, g, YEARS) for k, (w, g) in CONFIGS.items()}}
    months = YEARS * MONTHS
    boot = lambda a: bootstrap_paths(a, months, N_BOOT)
    roll = lambda a: rolling_paths(a, months)
    out["boot_raw"] = run(real63, bond63, cash63, boot, "boot_raw")
    out["boot_decay"] = run(S.decay(real63), bond63, cash63, boot, "boot_decay")
    out["hist63_raw"] = run(real63, bond63, cash63, roll, "hist63")
    full = df.copy()
    real26 = S.strategies(full, factors=False)
    out["hist26"] = run(real26, data.real(full["bond"], full["infl"]), data.real(full["rf"], full["infl"]), roll, "hist26")
    json.dump(out, open("data/research/results.json", "w"), indent=1)


if __name__ == "__main__":
    main()
