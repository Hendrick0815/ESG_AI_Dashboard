"""特徵工程：技術指標 + 依「公布日」對齊的財務與 ESG 資料。

對齊規則（避免前視偏差）：
    某天 d 的某檔股票，只會拿到 available_date <= d 的最新一筆 ESG / 財務資料。
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

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
RISK_COLS = ["above_ma_long", "vol_60"]     # 風險控制用（不給 AI 模型）


def _roll(g, window: int, how: str, min_periods: Optional[int] = None) -> pd.Series:
    r = g.rolling(window, min_periods=min_periods or window)
    return getattr(r, how)().reset_index(level=0, drop=True)


def add_technical(prices: pd.DataFrame, hold_days: int) -> pd.DataFrame:
    """技術面特徵＋風險控制用的欄位。只用當天（含）以前的資料。"""
    df = prices[["date", "ticker", "close"]].copy()
    df["date"] = pd.to_datetime(df["date"]).astype("datetime64[ns]")
    df = df.dropna().sort_values(["ticker", "date"]).drop_duplicates(["ticker", "date"]).reset_index(drop=True)
    g = df.groupby("ticker", group_keys=False)["close"]
    df["ret_1d"] = g.pct_change()
    for n in (5, 20, 60):
        df[f"mom_{n}"] = g.pct_change(n)
    rg = df.groupby("ticker")["ret_1d"]
    df["vol_20"] = _roll(rg, 20, "std") * np.sqrt(config.TRADING_DAYS)
    ma20, ma60 = _roll(g, 20, "mean"), _roll(g, 60, "mean")
    df["bias_20"] = df["close"] / ma20 - 1
    df["gap_ma60"] = df["close"] / ma60 - 1
    # ---- 風險控制 ----
    # 個股長期趨勢：收盤價在年線（200 日均線）之上；上市不滿約 150 天無法判斷 → NaN（不排除）
    ma_long = _roll(g, config.STOCK_TREND_MA, "mean", int(config.STOCK_TREND_MA * 0.75))
    df["above_ma_long"] = (df["close"] > ma_long).astype(float).where(ma_long.notna())
    # 近 60 日年化波動（用來排除全體最震盪的 20%）
    df["vol_60"] = _roll(rg, 60, "std", 40) * np.sqrt(config.TRADING_DAYS)
    # 標籤：從今天收盤買進、持有 hold_days 個交易日的報酬（只用於訓練與評估）
    df["fwd_ret"] = g.shift(-hold_days) / df["close"] - 1
    return df


def add_industry(panel: pd.DataFrame, industries: Optional[Dict[str, str]]) -> pd.DataFrame:
    """產業趨勢（僅供「產業與籌碼」頁參考，不影響選股）：同產業股票的等權指數。"""
    df = panel
    df["industry"] = df["ticker"].map(industries or {}) if industries else np.nan
    if df["industry"].isna().all():
        for c in ["ind_mom_20", "ind_gap_ma60", "ind_n", "ind_up"]:
            df[c] = np.nan
        return df
    ind = (df.dropna(subset=["industry", "ret_1d"])
             .groupby(["industry", "date"])["ret_1d"].agg(["mean", "size"]).reset_index()
             .sort_values(["industry", "date"]))
    ind["nav"] = (1 + ind["mean"]).groupby(ind["industry"]).cumprod()
    ig = ind.groupby("industry")["nav"]
    ind["ind_mom_20"] = ig.pct_change(20)
    ind["ind_gap_ma60"] = ind["nav"] / _roll(ig, 60, "mean") - 1
    ind = ind.rename(columns={"size": "ind_n"})[["industry", "date", "ind_mom_20", "ind_gap_ma60", "ind_n"]]
    df = df.merge(ind, on=["industry", "date"], how="left")
    df["ind_up"] = ((df["ind_gap_ma60"] > 0) & (df["ind_mom_20"] > 0)).astype(float).where(df["ind_gap_ma60"].notna())
    return df


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
