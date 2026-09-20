"""特徵工程：技術指標 + 依「公布日」對齊的財務與 ESG 資料。

對齊規則（避免前視偏差）：
    某天 d 的某檔股票，只會拿到 available_date <= d 的最新一筆 ESG / 財務資料。
"""
from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

from . import config

TECH_FEATURES = ["mom_5", "mom_20", "mom_60", "vol_20", "bias_20", "gap_ma60"]
TECH_LABELS = {
    "mom_5": "近 5 日報酬（動能）", "mom_20": "近 1 月報酬（動能）", "mom_60": "近 3 月報酬（動能）",
    "vol_20": "20 日年化波動率", "bias_20": "月線乖離率", "gap_ma60": "季線乖離率",
    "pe": "本益比", "pb": "股價淨值比", "dividend_yield": "殖利率",
    "roe": "ROE", "roa": "ROA", "eps": "EPS", "debt_ratio": "負債比",
    "esg_total": "ESG 總分", "e_score": "E 分數", "s_score": "S 分數", "g_score": "G 分數",
    "controversy_score": "爭議分數", "carbon_intensity": "碳排強度", "event_score": "事件雷達分數",
}
NON_FEATURE = {"ticker", "available_date", "name", "industry", "sasb_industry", "esg_grade",
               "period", "source_file", "code", "market", "date"}


def add_technical(prices: pd.DataFrame, hold_days: int) -> pd.DataFrame:
    df = prices[["date", "ticker", "close"]].copy()
    df["date"] = pd.to_datetime(df["date"]).astype("datetime64[ns]")
    df = df.dropna().sort_values(["ticker", "date"]).drop_duplicates(["ticker", "date"])
    g = df.groupby("ticker", group_keys=False)["close"]
    df["ret_1d"] = g.pct_change()
    for n in (5, 20, 60):
        df[f"mom_{n}"] = g.pct_change(n)
    df["vol_20"] = (df.groupby("ticker")["ret_1d"].rolling(20).std()
                      .reset_index(level=0, drop=True) * np.sqrt(config.TRADING_DAYS))
    ma20 = g.rolling(20).mean().reset_index(level=0, drop=True)
    ma60 = g.rolling(60).mean().reset_index(level=0, drop=True)
    df["bias_20"] = df["close"] / ma20 - 1
    df["gap_ma60"] = df["close"] / ma60 - 1
    # 標籤：從今天收盤買進、持有 hold_days 個交易日的報酬（只用於訓練與評估）
    df["fwd_ret"] = g.shift(-hold_days) / df["close"] - 1
    return df.reset_index(drop=True)


def numeric_cols(df: Optional[pd.DataFrame]) -> List[str]:
    if df is None or df.empty:
        return []
    return [c for c in df.columns if c not in NON_FEATURE and pd.api.types.is_numeric_dtype(df[c])
            and df[c].notna().any()]


def asof_merge(panel: pd.DataFrame, other: Optional[pd.DataFrame], cols: List[str],
               static: bool = False) -> pd.DataFrame:
    """把 other（ticker, available_date, cols...）依公布日對齊到 panel（date, ticker）。
    static=True：每檔一律用最新一筆（會有前視偏差，只在歷史資料不足時作為對照）。"""
    if other is None or other.empty or not cols:
        return panel
    o = other[["ticker", "available_date", *cols]].copy()
    o["available_date"] = pd.to_datetime(o["available_date"]).astype("datetime64[ns]")
    if static:
        latest = o.sort_values("available_date").groupby("ticker")[cols].last()
        return panel.merge(latest, left_on="ticker", right_index=True, how="left")
    o = o.dropna(subset=["available_date"]).sort_values("available_date")
    # 每一欄各自取「最新的非空值」，避免某欄這期沒填把舊值蓋掉
    left = panel.copy()
    left["date"] = pd.to_datetime(left["date"]).astype("datetime64[ns]")
    left = left.sort_values("date")
    for c in cols:
        oc = o.dropna(subset=[c])[["ticker", "available_date", c]]
        if oc.empty:
            left[c] = np.nan
            continue
        left = pd.merge_asof(left, oc, left_on="date", right_on="available_date", by="ticker",
                             direction="backward").drop(columns=["available_date"])
    return left.sort_values(["ticker", "date"]).reset_index(drop=True)


def build_panel(prices: pd.DataFrame, esg: Optional[pd.DataFrame], financials: Optional[pd.DataFrame],
                hold_days: int, static_esg: bool = False) -> Tuple[pd.DataFrame, dict]:
    """回傳 (panel, info)。info 裡有各類特徵名稱與資料涵蓋率。"""
    panel = add_technical(prices, hold_days)
    fin_cols = numeric_cols(financials)
    esg_cols = [c for c in numeric_cols(esg) if c in config.ESG_COLS]

    # 沒有日期的 ESG 資料只能當靜態資料使用
    esg_static = static_esg or (esg is not None and not esg.empty and esg["available_date"].isna().all())
    fin_static = financials is not None and not financials.empty and financials["available_date"].isna().all()

    panel = asof_merge(panel, financials, fin_cols, static=fin_static)
    panel = asof_merge(panel, esg, esg_cols, static=esg_static)

    cov = float(panel["esg_total"].notna().mean()) if "esg_total" in panel.columns else 0.0
    info = {
        "tech_features": TECH_FEATURES,
        "fin_features": fin_cols,
        "esg_features": esg_cols,
        "esg_static": bool(esg_static),
        "fin_static": bool(fin_static),
        "esg_coverage": cov,
        "esg_first_date": (panel.loc[panel["esg_total"].notna(), "date"].min()
                           if "esg_total" in panel.columns and cov > 0 else None),
    }
    return panel, info
