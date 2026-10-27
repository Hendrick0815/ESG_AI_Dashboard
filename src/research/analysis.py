"""論文補充分析：投組 ESG 品質、事前定義的市場情境、上漲／下跌參與率、年度報酬。"""
from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd

TD = 252

# ---------------------------------------------------------------- 市場情境（事前規則，與策略績效無關）
REGIME_RULES = {
    "lookback_return": 60,       # 加權指數 60 日報酬
    "vol_window": 20,            # 20 日年化波動率
    "dd_window": 250,            # 距 250 日高點回撤
    "bear_return": -0.10,        # 空頭：60 日報酬 ≤ −10% 或 回撤 ≤ −15%
    "bear_drawdown": -0.15,
    "high_vol": 0.25,            # 高波動：非空頭且 20 日年化波動 ≥ 25%
    "bull_return": 0.05,         # 多頭：60 日報酬 ≥ +5% 且波動 < 25%
}
REGIME_ORDER = ["多頭", "盤整", "高波動", "空頭"]


def classify_regimes(index_close: pd.Series, rules: Dict = REGIME_RULES) -> pd.DataFrame:
    """以前一交易日收盤為止的資料分類當天情境（避免用到當天資訊）。回傳 date, ret60, vol20, dd, regime。"""
    px = index_close.sort_index().astype(float)
    r = px.pct_change()
    ret60 = px.pct_change(rules["lookback_return"])
    vol20 = r.rolling(rules["vol_window"]).std() * np.sqrt(TD)
    dd = px / px.rolling(rules["dd_window"], min_periods=60).max() - 1
    f = pd.DataFrame({"ret60": ret60, "vol20": vol20, "dd": dd}).shift(1)
    bear = (f["ret60"] <= rules["bear_return"]) | (f["dd"] <= rules["bear_drawdown"])
    hv = ~bear & (f["vol20"] >= rules["high_vol"])
    bull = ~bear & ~hv & (f["ret60"] >= rules["bull_return"])
    reg = np.select([bear, hv, bull], ["空頭", "高波動", "多頭"], default="盤整")
    out = f.copy()
    out["regime"] = np.where(f.isna().any(axis=1), None, reg)
    return out.reset_index().rename(columns={"index": "date"})


def regime_table(ret_wide: pd.DataFrame, regimes: pd.DataFrame) -> pd.DataFrame:
    """各情境：交易日數、各投組平均日報酬（年化，算術）與累積報酬。"""
    df = ret_wide.join(regimes.set_index("date")["regime"], how="inner").dropna(subset=["regime"])
    rows = []
    for reg in REGIME_ORDER:
        g = df[df["regime"] == reg].drop(columns="regime")
        row = {"regime": reg, "days": len(g)}
        for c in g.columns:
            row[c + "|ann_mean"] = g[c].mean() * TD if len(g) else np.nan
            row[c + "|cum"] = (1 + g[c]).prod() - 1 if len(g) else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def capture(ret_wide: pd.DataFrame, market: str) -> pd.DataFrame:
    m = ret_wide[market]
    up, dn = m > 0, m < 0
    rows = []
    for c in ret_wide.columns:
        if c == market:
            continue
        rows.append({"portfolio": c, "up_capture": ret_wide.loc[up, c].mean() / m[up].mean(),
                     "down_capture": ret_wide.loc[dn, c].mean() / m[dn].mean(), "up_days": int(up.sum()), "down_days": int(dn.sum())})
    return pd.DataFrame(rows)


def yearly(ret_wide: pd.DataFrame) -> pd.DataFrame:
    return ret_wide.groupby(ret_wide.index.year).apply(lambda g: (1 + g).prod() - 1)


# ---------------------------------------------------------------- 投組 ESG 品質
def esg_asof(esg: pd.DataFrame, dates: List[pd.Timestamp]) -> pd.DataFrame:
    """每個日期 d：每檔股票在 d 當天（含）以前已公告的最新一期 TESG。"""
    e = esg.dropna(subset=["available_date"]).sort_values("available_date")
    out = []
    for d in dates:
        x = e[e["available_date"] <= d].drop_duplicates("ticker", keep="last").copy()
        x["date"] = d
        out.append(x)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def esg_quality(holdings: pd.DataFrame, esg_pit: pd.DataFrame, universe: pd.DataFrame,
                industries: Dict[str, str]) -> pd.DataFrame:
    """每個調倉日 × 投組：持股加權 TESG／E／S／G／事件雷達分數、ESG 資料涵蓋率、
    低 ESG 持股比例（TESG 位於當期股票池後 1/3）、產業 HHI 與最大產業比重。
    另加「股票池等權」作為市場代理（ETF 成分股與權重的歷史資料取不到，無法直接比較）。"""
    cols = ["esg_total", "e_score", "s_score", "g_score", "event_score"]
    rows = []
    uni_groups = dict(tuple(universe.groupby("date")))
    for d, hd in holdings.groupby("date"):
        epit = esg_pit[esg_pit["date"] == d].set_index("ticker")
        uni = uni_groups.get(d)
        if uni is None:
            continue
        uni_esg = epit.reindex(uni["ticker"])["esg_total"]
        cut = uni_esg.quantile(1 / 3)
        port = list(hd.groupby("portfolio"))
        port.append(("股票池等權", pd.DataFrame({"ticker": uni["ticker"].values,
                                               "weight": 1.0 / len(uni)})))
        for name, g in port:
            w = g.set_index("ticker")["weight"]
            w = w[w > 0]
            if w.empty:
                continue
            w = w / w.sum()
            e = epit.reindex(w.index)
            have = e["esg_total"].notna()
            row = {"date": d, "portfolio": name, "n": len(w), "esg_coverage": float(w[have].sum())}
            for c in cols:
                ok = e[c].notna()
                row[c] = float((w[ok] * e.loc[ok, c]).sum() / w[ok].sum()) if ok.any() else np.nan
            row["low_esg_share"] = float(w[have & (e["esg_total"] <= cut)].sum() / w[have].sum()) if have.any() else np.nan
            ind = pd.Series(w.values, index=[industries.get(t, "未分類") for t in w.index]).groupby(level=0).sum()
            row["industry_hhi"] = float((ind ** 2).sum())
            row["top_industry"] = ind.idxmax()
            row["top_industry_share"] = float(ind.max())
            rows.append(row)
    return pd.DataFrame(rows)
