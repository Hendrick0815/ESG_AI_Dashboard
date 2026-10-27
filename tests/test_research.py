"""研究腳本（逐期股票池、含權息報酬、統計檢定、市場情境）的單元測試。"""
import numpy as np
import pandas as pd

from src.research import analysis as an, exchange as ex, stats as rs


def test_daily_returns_twse_and_tpex():
    q = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"] * 2),
        "market": ["TWSE"] * 3 + ["TPEx"] * 3, "code": ["1101"] * 3 + ["6488"] * 3,
        "ticker": ["1101.TW"] * 3 + ["6488.TWO"] * 3,
        "close": [100, 102, 97, 50, 51, 48],
        # 上市第 3 天除息 2 元：參考價 = 100（102 − 2），收盤 97 → 漲跌 −3
        "sign": ["", "+", "-", "", "+1.00", "-1.00"], "change": [0, 2, 3, 0, 1, 1],
        # 上櫃：次日參考價（第 2 天公布 49 → 第 3 天除息 2 元）
        "next_ref": [np.nan, np.nan, np.nan, 50, 49, 48]})
    r = ex.daily_returns(q).values
    assert abs(r[1] - 0.02) < 1e-9 and abs(r[2] - (97 / 100 - 1)) < 1e-9          # 除息日用參考價，不把股利算成虧損
    assert abs(r[4] - (51 / 50 - 1)) < 1e-9 and abs(r[5] - (48 / 49 - 1)) < 1e-9


def test_x_mark_returns_zero():
    q = pd.DataFrame({"date": pd.to_datetime(["2024-01-02", "2024-01-03"]), "market": "TWSE", "code": "2330",
                      "ticker": "2330.TW", "close": [600, 580], "sign": ["", "X"], "change": [0, 0], "next_ref": np.nan})
    assert ex.daily_returns(q).iloc[1] == 0.0


def test_common_stock_rule():
    s = pd.Series(["2330", "0050", "9103", "6488", "00878", "1101"])
    assert ex.is_common_stock(s).tolist() == [True, False, False, True, False, True]


def test_eligibility_top_n_uses_past_window_only():
    days = pd.bdate_range("2024-01-01", periods=30)
    rows = []
    for i, d in enumerate(days):
        for t, v in (("A", 100), ("B", 50), ("C", 10 if i < 25 else 1000)):
            rows.append({"date": d, "ticker": t, "value": v})
    elig = ex.eligibility(pd.DataFrame(rows), size=2, window=20, min_days=15)
    first = elig[elig["date"] == days[20]]
    assert set(first["ticker"]) == {"A", "B"}
    last = elig[elig["date"] == days[-1]]
    assert "C" in set(last["ticker"])             # C 成交金額暴增後才進入股票池


def test_hac_and_holm():
    x = pd.Series(np.random.default_rng(0).normal(0.001, 0.01, 2000))
    h = rs.hac_mean(x)
    assert h["ci_lo"] < h["est"] < h["ci_hi"] and h["n"] == 2000 and h["lags"] == rs.nw_lags(2000)
    adj = rs.holm([0.01, 0.04, 0.03])
    assert adj == sorted(adj, key=lambda v: v) or all(a >= p for a, p in zip(adj, [0.01, 0.04, 0.03]))
    assert max(adj) <= 1.0


def test_capm_recovers_beta():
    rng = np.random.default_rng(1)
    m = pd.Series(rng.normal(0.0005, 0.01, 3000))
    p = 0.0002 + 1.5 * m + pd.Series(rng.normal(0, 0.002, 3000))
    c = rs.capm(p, m, rf_annual=0.0)
    assert abs(c["beta"] - 1.5) < 0.05 and c["r2"] > 0.9


def test_regimes_use_previous_day():
    idx = pd.bdate_range("2023-01-02", periods=400)
    px = pd.Series(np.linspace(100, 200, 400), index=idx)
    reg = an.classify_regimes(px)
    assert reg["regime"].dropna().iloc[-1] in ("多頭", "盤整")
    assert pd.isna(reg["regime"].iloc[0])
