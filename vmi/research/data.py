"""Long-history monthly return data for the two-sleeve study (point-in-time clean, no look-ahead).

Sources (downloaded once, processed into data/research/monthly.csv, which is committed):
  Ken French data library: US market, RF, SMB/HML/RMW/CMA, momentum, beta-sorted portfolios (1926/1963 → 2026)
  Robert Shiller ie_data.xls: CPI, 10y Treasury total return (1871 → 2023-09)
Everything is converted to REAL monthly returns. The common sample ends 2023-09 (end of Shiller's file).
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pandas as pd
import requests

FRENCH = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/{}_CSV.zip"
SHILLER = "http://www.econ.yale.edu/~shiller/data/ie_data.xls"
OUT = Path(__file__).resolve().parents[2] / "data" / "research" / "monthly.csv"


def _french(name: str, block: str | None = None) -> pd.DataFrame:
    """First monthly block of a French CSV (or the block that follows the line containing `block`), as decimals."""
    raw = requests.get(FRENCH.format(name), timeout=60).content
    z = zipfile.ZipFile(io.BytesIO(raw))
    lines = z.read(z.namelist()[0]).decode("latin-1").splitlines()
    i = next(n for n, l in enumerate(lines) if block is None or block in l) + (0 if block is None else 1)
    while not (lines[i].split(",")[0].strip().isdigit() and len(lines[i].split(",")[0].strip()) == 6):
        i += 1
    header = lines[i - 1].split(",")
    rows = []
    while i < len(lines) and lines[i].split(",")[0].strip().isdigit() and len(lines[i].split(",")[0].strip()) == 6:
        rows.append(lines[i].split(","))
        i += 1
    df = pd.DataFrame(rows, columns=["ym"] + [h.strip() for h in header[1:]])
    df.index = pd.PeriodIndex(df.pop("ym").str.strip(), freq="M")
    return df.astype(float).replace([-99.99, -999.0], float("nan")) / 100.0


def _shiller() -> pd.DataFrame:
    x = pd.read_excel(SHILLER, sheet_name="Data", header=None, skiprows=8)
    x = x[pd.to_numeric(x[0], errors="coerce").notna()]
    d = pd.to_numeric(x[0])
    idx = pd.PeriodIndex([f"{int(v)}-{round((v - int(v)) * 100):02d}" for v in d], freq="M")
    out = pd.DataFrame({"cpi": pd.to_numeric(x[4]).values, "bond_gross": pd.to_numeric(x[17]).values}, index=idx)
    return out[~out.index.duplicated()]


def build() -> pd.DataFrame:
    f3 = _french("F-F_Research_Data_Factors")                      # 1926+: Mkt-RF, SMB, HML, RF
    f5 = _french("F-F_Research_Data_5_Factors_2x3")                # 1963+: RMW, CMA
    mom = _french("F-F_Momentum_Factor")
    beta = _french("Portfolios_Formed_on_Beta", block="Value Weighted Returns -- Monthly")[["Lo 20", "Qnt 2", "Hi 20"]]
    sh = _shiller()
    df = pd.DataFrame({"mkt": f3["Mkt-RF"] + f3["RF"], "rf": f3["RF"], "rmw": f5["RMW"], "cma": f5["CMA"],
                       "mom": mom.iloc[:, 0], "beta_lo": beta["Lo 20"], "beta_hi": beta["Hi 20"]})
    df["infl"] = sh["cpi"].pct_change()
    df["bond"] = sh["bond_gross"] - 1          # Shiller column "Monthly Bond Returns" is the gross monthly total return
    return df.loc["1926-07":"2023-09"]


def load() -> pd.DataFrame:
    """Nominal monthly returns + inflation (cached CSV; rebuilt from the sources when missing)."""
    if not OUT.exists():
        OUT.parent.mkdir(parents=True, exist_ok=True)
        build().to_csv(OUT)
    df = pd.read_csv(OUT, index_col=0)
    df.index = pd.PeriodIndex(df.index, freq="M")
    return df


def real(nominal: pd.Series, infl: pd.Series) -> pd.Series:
    return (1 + nominal) / (1 + infl) - 1
