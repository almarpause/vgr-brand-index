"""No-network tests for the normalisation + combination maths."""

from __future__ import annotations

import numpy as np
import pandas as pd

from vgr_brand_index.normalize import (
    combine_sources,
    inverse_variance_weights,
    sqrt_ratio_to_top5,
    zscore,
)


def test_sqrt_ratio_top5_scales_to_elite():
    # five equal leaders at 100, one small at 0 -> leaders map to 1.0
    x = pd.Series([100, 100, 100, 100, 100, 0])
    r = sqrt_ratio_to_top5(x)
    assert abs(r.iloc[0] - 1.0) < 1e-9
    assert r.iloc[-1] == 0.0


def test_combine_drops_ineligible_and_renormalises():
    idx = ["a", "b"]
    scores = {
        "pv": pd.Series([1.0, 1.0], index=idx),
        "gdelt": pd.Series([0.0, 0.5], index=idx),
    }
    elig = {
        "pv": pd.Series([True, True], index=idx),
        # brand 'a' has no gdelt -> its composite must equal pv alone, not be
        # dragged down by a zero-filled gdelt
        "gdelt": pd.Series([False, True], index=idx),
    }
    out = combine_sources(scores, elig)
    assert abs(out.loc["a"] - 1.0) < 1e-9           # pv only
    assert abs(out.loc["b"] - 0.75) < 1e-9          # mean(1.0, 0.5)


def test_combine_no_eligible_source_is_nan():
    idx = ["a"]
    scores = {"pv": pd.Series([1.0], index=idx)}
    elig = {"pv": pd.Series([False], index=idx)}
    out = combine_sources(scores, elig)
    assert np.isnan(out.loc["a"])


def test_zscore_flags_a_spike():
    baseline = [10, 11, 9, 10, 12, 10]
    assert zscore(baseline + [10]) < 1.0            # steady -> low z
    assert zscore(baseline + [40]) > 3.0            # spike -> high z


def test_zscore_degenerate_returns_zero():
    assert zscore([5, 5, 5, 5, 5]) == 0.0           # zero variance
    assert zscore([1, 2]) == 0.0                    # too few points


def test_inverse_variance_downweights_noisy_source():
    hist = {
        "steady": pd.Series([100, 101, 99, 100, 102, 100, 99]),   # low variance
        "noisy": pd.Series([10, 200, 5, 300, 2, 250, 8]),          # high variance
    }
    w = inverse_variance_weights(hist, ["steady", "noisy"])
    assert w["steady"] > w["noisy"]
    assert abs(sum(w.values()) - 1.0) < 1e-9
