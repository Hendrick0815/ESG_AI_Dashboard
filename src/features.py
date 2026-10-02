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
# 見頂訊號（區分「還在噴」和「已經見頂」的飆股）；缺值用訓練集中位數補，不會讓股票被排除
PEAK_FEATURES = ["dd_high20", "days_since_high20", "down_streak", "vol_ratio", "reversal"]
# 產業：產業本身的趨勢＋個股在產業裡的相對強弱
INDUSTRY_FEATURES = ["ind_mom_20", "ind_gap_ma60", "rel_ind_mom_20"]
TECH_LABELS = {
    "mom_5": "近 5 日報酬（動能）", "mom_20": "近 1 月報酬（動能）", "mom_60": "近 3 月報酬（動能）",
    "vol_20": "20 日年化波動率", "bias_20": "月線乖離率", "gap_ma60": "季線乖離率",
    "dd_high20": "距 20 日最高價跌幅", "days_since_high20": "距 20 日最高價天數", "down_streak": "連續下跌天數",
    "vol_ratio": "量能比（5 日均量 ÷ 60 日均量）", "reversal": "短期反轉（5 日 × 60 日報酬）",
    "ind_mom_20": "產業近 1 月報酬", "ind_gap_ma60": "產業季線乖離", "rel_ind_mom_20": "個股相對產業近 1 月報酬",
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


def _days_since_high(df: pd.DataFrame, window: int, min_periods: int) -> pd.Series:
    """每檔股票：近 window 日最高收盤價是幾個交易日前（同價取最近一次）。向量化計算，比 rolling.apply 快很多。"""
    out = np.full(len(df), np.nan)
    close = df["close"].to_numpy(dtype=float)
    starts = np.flatnonzero(np.r_[True, df["ticker"].to_numpy()[1:] != df["ticker"].to_numpy()[:-1]])
    ends = np.r_[starts[1:], len(df)]
    for s, e in zip(starts, ends):
        c = close[s:e]
        n = len(c)
        if n < min_periods:
            continue
        pad = np.r_[np.full(window - 1, -np.inf), c]
        win = np.lib.stride_tricks.sliding_window_view(pad, window)[:, ::-1]   # 每列：今天、昨天、…
        res = np.argmax(win, axis=1).astype(float)
        res[: min_periods - 1] = np.nan
        out[s:e] = res
    return pd.Series(out, index=df.index)


def add_technical(prices: pd.DataFrame, hold_days: int) -> pd.DataFrame:
    """技術面特徵＋風險控制用的欄位。只用當天（含）以前的資料。"""
    cols = ["date", "ticker", "close"] + (["volume"] if "volume" in prices.columns else [])
    df = prices[cols].copy()
    df["date"] = pd.to_datetime(df["date"]).astype("datetime64[ns]")
    df = df.dropna(subset=["date", "ticker", "close"]).sort_values(["ticker", "date"]) \
           .drop_duplicates(["ticker", "date"]).reset_index(drop=True)
    g = df.groupby("ticker", group_keys=False)["close"]
    df["ret_1d"] = g.pct_change()
    for n in (5, 20, 60):
        df[f"mom_{n}"] = g.pct_change(n)
    rg = df.groupby("ticker")["ret_1d"]
    df["vol_20"] = _roll(rg, 20, "std") * np.sqrt(config.TRADING_DAYS)
    ma20, ma60 = _roll(g, 20, "mean"), _roll(g, 60, "mean")
    df["bias_20"] = df["close"] / ma20 - 1
    df["gap_ma60"] = df["close"] / ma60 - 1
    # ---- 見頂訊號 ----
    hi20 = _roll(g, 20, "max", 10)
    df["dd_high20"] = df["close"] / hi20 - 1                       # 從近 20 日最高價回落多少（0 = 正在創高）
    df["days_since_high20"] = _days_since_high(df, 20, 10)          # 高點是幾天前（越大代表漲勢停了越久）
    down = (df["ret_1d"] < 0).astype(int)
    grp = (down != down.groupby(df["ticker"]).shift()).cumsum()
    df["down_streak"] = down.groupby([df["ticker"], grp]).cumsum().where(down == 1, 0)   # 連續下跌天數
    if "volume" in df.columns:
        vg = df.groupby("ticker")["volume"]
        v60 = _roll(vg, 60, "mean", 40)
        df["vol_ratio"] = (_roll(vg, 5, "mean") / v60.where(v60 > 0))  # >1 放量、<1 量縮
    else:
        df["vol_ratio"] = np.nan
    df["reversal"] = df["mom_5"] * df["mom_60"]                     # 大漲後短線轉弱 → 負值
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
                hold_days: int, static_esg: bool = False,
                industries: Optional[Dict[str, str]] = None) -> Tuple[pd.DataFrame, dict]:
    """回傳 (panel, info)。info 裡有各類特徵名稱與資料涵蓋率。industries：代號 → 產業（選股考慮產業時用）。"""
    panel = add_technical(prices, hold_days)
    ind_features: List[str] = []
    if industries:
        panel = add_industry(panel, industries)
        panel["rel_ind_mom_20"] = panel["mom_20"] - panel["ind_mom_20"]
        if panel["ind_mom_20"].notna().any():
            ind_features = list(INDUSTRY_FEATURES)
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
        "extra_features": [f for f in PEAK_FEATURES if f in panel.columns and panel[f].notna().any()] + ind_features,
        "fin_features": fin_cols,
        "esg_features": esg_cols,
        "esg_static": bool(esg_static),
        "fin_static": bool(fin_static),
        "esg_coverage": cov,
        "esg_first_date": (panel.loc[panel["esg_total"].notna(), "date"].min()
                           if "esg_total" in panel.columns and cov > 0 else None),
    }
    return panel, info
