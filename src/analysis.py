"""「產業與籌碼」頁用的彙整：產業趨勢、三大法人（主力）買賣超排行。只用當天以前的資料。僅供參考，不影響選股。"""
from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd

from .features import add_industry, add_technical


def industry_trend(prices: pd.DataFrame, industries: Dict[str, str], lookback_days: int = 260) -> pd.DataFrame:
    """每個產業最新一天的：檔數、近 5 日／近 1 月報酬、季線乖離、趨勢是否向上。"""
    if prices.empty or not industries:
        return pd.DataFrame()
    days = np.sort(prices["date"].unique())[-lookback_days:]
    tech = add_technical(prices[prices["date"].isin(days)], hold_days=1)
    panel = add_industry(tech, industries)
    last = panel["date"].max()
    p5 = panel.dropna(subset=["industry"]).copy()
    # 產業近 5 日報酬：用等權日報酬連乘
    recent = p5[p5["date"] > np.sort(p5["date"].unique())[-6]]
    r5 = recent.groupby(["industry", "date"])["ret_1d"].mean().groupby(level=0).apply(lambda s: (1 + s).prod() - 1)
    snap = panel[(panel["date"] == last) & panel["industry"].notna()]
    out = snap.groupby("industry").agg(檔數=("ticker", "nunique"), 近1月=("ind_mom_20", "first"),
                                      季線乖離=("ind_gap_ma60", "first"), 趨勢向上=("ind_up", "first"))
    out["近5日"] = r5.reindex(out.index)
    out["趨勢向上"] = out["趨勢向上"] == 1
    out = out.reset_index().rename(columns={"industry": "產業"})
    return out[["產業", "檔數", "近5日", "近1月", "季線乖離", "趨勢向上"]].sort_values("近1月", ascending=False)


def flow_leaders(flows: pd.DataFrame, prices: pd.DataFrame, names: Dict[str, str],
                 industries: Dict[str, str], days: int = 5) -> pd.DataFrame:
    """最近 days 個交易日的三大法人買賣超（張、估計金額億元）。金額 = 股數 × 最新收盤價，僅供排序參考。"""
    if flows is None or flows.empty:
        return pd.DataFrame()
    f = flows.copy()
    f["date"] = pd.to_datetime(f["date"])
    recent_days = np.sort(f["date"].unique())[-days:]
    f = f[f["date"].isin(recent_days)]
    agg = f.groupby("ticker")[["foreign_net", "trust_net", "dealer_net", "total_net"]].sum()
    close = (prices.sort_values("date").groupby("ticker")["close"].last() if not prices.empty
             else pd.Series(dtype=float))
    out = pd.DataFrame({
        "代號": agg.index,
        "公司": [names.get(t, "") for t in agg.index],
        "產業": [industries.get(t, "") for t in agg.index],
        "外資(張)": (agg["foreign_net"] / 1000).round(0).values,
        "投信(張)": (agg["trust_net"] / 1000).round(0).values,
        "自營商(張)": (agg["dealer_net"] / 1000).round(0).values,
        "合計(張)": (agg["total_net"] / 1000).round(0).values,
    })
    out["估計金額(億)"] = (agg["total_net"].values * close.reindex(agg.index).values / 1e8)
    out.attrs["period"] = (pd.Timestamp(recent_days[0]), pd.Timestamp(recent_days[-1]))
    return out


def flow_by_industry(leaders: pd.DataFrame) -> pd.DataFrame:
    if leaders.empty:
        return leaders
    d = leaders[leaders["產業"] != ""]
    return (d.groupby("產業")["估計金額(億)"].sum().reset_index()
              .sort_values("估計金額(億)", ascending=False))
