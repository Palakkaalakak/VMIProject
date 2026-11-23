

def test_volatility_profile_labels():
    import numpy as np
    import pandas as pd
    from vmi.analysis.technicals import volatility_profile
    idx = pd.bdate_range("2016-01-01", periods=2600)
    rng = np.random.default_rng(1)
    calm = pd.DataFrame({"close": 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.008, len(idx))))}, index=idx)
    wild = pd.DataFrame({"close": 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.03, len(idx))))}, index=idx)
    assert volatility_profile(calm)["label"] == "defensive"
    assert volatility_profile(wild)["label"] == "growth-like (high)"
    assert volatility_profile(calm.iloc[:100]) is None
