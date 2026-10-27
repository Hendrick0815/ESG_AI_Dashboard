"""論文用的統計檢定：Newey-West（HAC）標準誤、CAPM、差異檢定、多重比較、效果量。"""
from __future__ import annotations

import math
from typing import Dict, List

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats as st

TD = 252


def nw_lags(n: int) -> int:
    """Newey & West (1994) 自動落後期數：floor(4 (T/100)^(2/9))。"""
    return int(math.floor(4 * (n / 100) ** (2 / 9)))


def hac_mean(x: pd.Series) -> Dict:
    """平均數的 HAC 檢定（對常數迴歸）。回傳估計、HAC 標準誤、t、p、95% 信賴區間、樣本數、落後期數。"""
    x = pd.Series(x).dropna().astype(float)
    n = len(x)
    L = nw_lags(n)
    m = sm.OLS(x.values, np.ones(n)).fit(cov_type="HAC", cov_kwds={"maxlags": L})
    est, se = float(m.params[0]), float(m.bse[0])
    ci = m.conf_int(0.05)[0]
    return {"n": n, "lags": L, "est": est, "se": se, "t": est / se if se else np.nan,
            "p": float(m.pvalues[0]), "ci_lo": float(ci[0]), "ci_hi": float(ci[1])}


def capm(rp: pd.Series, rm: pd.Series, rf_annual: float = 0.01) -> Dict:
    """日頻 CAPM：(rp − rf) = α + β (rm − rf) + ε，HAC 標準誤。"""
    df = pd.concat([rp, rm], axis=1, keys=["p", "m"]).dropna()
    rf = (1 + rf_annual) ** (1 / TD) - 1
    y, x = df["p"] - rf, df["m"] - rf
    n = len(df)
    L = nw_lags(n)
    m = sm.OLS(y.values, sm.add_constant(x.values)).fit(cov_type="HAC", cov_kwds={"maxlags": L})
    a, b = m.params
    sa, sb = m.bse
    ci = m.conf_int(0.05)
    return {"n": n, "lags": L, "alpha_d": float(a), "alpha_se": float(sa), "alpha_t": float(a / sa),
            "alpha_p": float(m.pvalues[0]), "alpha_ci_lo": float(ci[0][0]), "alpha_ci_hi": float(ci[0][1]),
            "alpha_ann": float((1 + a) ** TD - 1), "beta": float(b), "beta_se": float(sb),
            "beta_ci_lo": float(ci[1][0]), "beta_ci_hi": float(ci[1][1]), "r2": float(m.rsquared)}


def diff_test(rp: pd.Series, rb: pd.Series) -> Dict:
    """策略與比較基準的日報酬差：HAC 平均差檢定＋效果量（年化差、日差 ÷ 日差標準差）。"""
    d = (pd.concat([rp, rb], axis=1, keys=["p", "b"]).dropna().pipe(lambda x: x["p"] - x["b"]))
    out = hac_mean(d)
    out["ann_diff"] = out["est"] * TD
    out["effect_d"] = float(d.mean() / d.std(ddof=1)) if d.std(ddof=1) > 0 else np.nan
    out["ir_ann"] = out["effect_d"] * math.sqrt(TD)      # 年化資訊比率
    return out


def holm(pvals: List[float]) -> List[float]:
    """Holm-Bonferroni 調整後 p 值（控制整體型一錯誤率）。"""
    p = np.asarray(pvals, float)
    order = np.argsort(p)
    m = len(p)
    adj = np.empty(m)
    run = 0.0
    for k, i in enumerate(order):
        run = max(run, min(1.0, (m - k) * p[i]))
        adj[i] = run
    return adj.tolist()


def bootstrap_ci_ann(r: pd.Series, block: int = 20, n_boot: int = 2000, seed: int = 42) -> tuple:
    """移動區塊 bootstrap 的年化幾何報酬 95% 信賴區間（保留短期自我相關）。"""
    x = pd.Series(r).dropna().values
    n = len(x)
    rng = np.random.default_rng(seed)
    nb = int(np.ceil(n / block))
    out = []
    for _ in range(n_boot):
        starts = rng.integers(0, n - block + 1, nb)
        s = np.concatenate([x[i:i + block] for i in starts])[:n]
        out.append(np.prod(1 + s) ** (TD / n) - 1)
    return float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))
