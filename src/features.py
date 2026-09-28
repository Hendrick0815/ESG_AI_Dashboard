"""特徵工程：技術指標 + 依「公布日」對齊的財務與 ESG 資料。

對齊規則（避免前視偏差）：
    某天 d 的某檔股票，只會拿到 available_date <= d 的最新一筆 ESG / 財務資料。
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from . import config

TECH_FEATURES = ["mom_5", "mom_20", "mom_60", "vol_20", "bias_20", "gap_ma60",
                 "ma_align", "range_width", "dist_high"]
VOLUME_FEATURES = ["vol_ratio", "vol_trend"]          # 需要成交量（Yahoo 有；示範資料沒有）
INDUSTRY_FEATURES = ["ind_mom_20", "ind_gap_ma60"]     # 需要產業分類（listing.csv）
FLOW_FEATURES = ["inst_net_20", "foreign_net_20", "trust_net_20"]   # 需要三大法人資料（證交所 T86）

# ---- 選股條件（可在 config 調整門檻）----
MA_WINDOWS = (5, 10, 20, 60)     # 均線全上：收盤價站上這幾條均線
RANGE_DAYS = 40                  # 區間整理：看過去 40 個交易日（約兩個月）的高低點
TECH_LABELS = {
    "mom_5": "近 5 日報酬（動能）", "mom_20": "近 1 月報酬（動能）", "mom_60": "近 3 月報酬（動能）",
    "vol_20": "20 日年化波動率", "bias_20": "月線乖離率", "gap_ma60": "季線乖離率",
    "ma_align": "站上均線比例（5/10/20/60 日）", "range_width": "近 40 日區間寬度",
    "dist_high": "距離區間高點", "vol_ratio": "5 日均量 / 20 日均量", "vol_trend": "20 日均量 / 60 日均量",
    "ind_mom_20": "產業近 1 月報酬", "ind_gap_ma60": "產業指數季線乖離",
    "inst_net_20": "法人（外資＋投信）20 日買超占成交量", "foreign_net_20": "外資 20 日買超占成交量",
    "trust_net_20": "投信 20 日買超占成交量",
    "pe": "本益比", "pb": "股價淨值比", "dividend_yield": "殖利率",
    "roe": "ROE", "roa": "ROA", "eps": "EPS", "debt_ratio": "負債比",
    "esg_total": "ESG 總分", "e_score": "E 分數", "s_score": "S 分數", "g_score": "G 分數",
    "controversy_score": "爭議分數", "carbon_intensity": "碳排強度", "event_score": "事件雷達分數",
}
NON_FEATURE = {"ticker", "available_date", "name", "industry", "sasb_industry", "esg_grade",
               "period", "source_file", "code", "market", "date"}
SCREEN_COLS = ["liquid", "ma_all_up", "near_breakout", "mild_volume", "ind_up", "inst_buy"]


def _roll(g, window: int, how: str, min_periods: Optional[int] = None) -> pd.Series:
    r = g.rolling(window, min_periods=min_periods or window)
    return getattr(r, how)().reset_index(level=0, drop=True)


def add_technical(prices: pd.DataFrame, hold_days: int) -> pd.DataFrame:
    """技術面特徵＋選股條件用的欄位。只用當天（含）以前的資料。"""
    keep = [c for c in ["date", "ticker", "open", "high", "low", "close", "volume"] if c in prices.columns]
    df = prices[keep].copy()
    df["date"] = pd.to_datetime(df["date"]).astype("datetime64[ns]")
    for c in ["high", "low", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce") if c in df.columns else np.nan
    df = df.dropna(subset=["close"]).sort_values(["ticker", "date"]).drop_duplicates(["ticker", "date"])
    df = df.reset_index(drop=True)
    g = df.groupby("ticker", group_keys=False)["close"]
    df["ret_1d"] = g.pct_change()
    for n in (5, 20, 60):
        df[f"mom_{n}"] = g.pct_change(n)
    df["vol_20"] = _roll(df.groupby("ticker")["ret_1d"], 20, "std") * np.sqrt(config.TRADING_DAYS)
    for n in MA_WINDOWS:
        df[f"ma{n}"] = _roll(g, n, "mean")
    df["bias_20"] = df["close"] / df["ma20"] - 1
    df["gap_ma60"] = df["close"] / df["ma60"] - 1

    # 均線全上：站上 5/10/20/60 日均線，且月線、季線都在上揚（和 5 天前比）
    above = np.column_stack([(df["close"] >= df[f"ma{n}"]).to_numpy() for n in MA_WINDOWS])
    df["ma_align"] = above.mean(axis=1)
    df.loc[df["ma60"].isna(), "ma_align"] = np.nan
    mg = df.groupby("ticker")
    rising = (df["ma20"] > mg["ma20"].shift(5)) & (df["ma60"] > mg["ma60"].shift(5))
    df["ma_all_up"] = ((df["ma_align"] == 1) & rising).astype(float).where(df["ma60"].notna())

    # 區間整理：過去 40 天（不含今天）的最高、最低；沒有高低價就用收盤價
    hi = df["high"].fillna(df["close"])
    lo = df["low"].fillna(df["close"])
    prev_hi = hi.groupby(df["ticker"]).shift(1)
    prev_lo = lo.groupby(df["ticker"]).shift(1)
    df["range_high"] = _roll(prev_hi.groupby(df["ticker"]), RANGE_DAYS, "max")
    df["range_low"] = _roll(prev_lo.groupby(df["ticker"]), RANGE_DAYS, "min")
    df["range_width"] = df["range_high"] / df["range_low"] - 1       # 區間越窄＝整理越久越紮實
    df["dist_high"] = df["close"] / df["range_high"] - 1              # 負＝還在區間內；正＝已突破
    df["near_breakout"] = ((df["range_width"] <= config.RANGE_MAX_WIDTH)
                           & (df["dist_high"] >= -config.BREAKOUT_BAND)
                           & (df["dist_high"] <= config.BREAKOUT_MAX_ABOVE)).astype(float).where(df["range_high"].notna())

    # 成交量（股數）：0 視為缺資料（Yahoo 在停市日偶爾會給 0）
    vol = df["volume"].where(df["volume"] > 0)
    vg = vol.groupby(df["ticker"])
    v5, v20, v60 = _roll(vg, 5, "mean", 3), _roll(vg, 20, "mean", 10), _roll(vg, 60, "mean", 30)
    df["vol_ratio"] = v5 / v20                                        # 稍微出量：約 1.1～2 倍
    df["vol_trend"] = v20 / v60
    df["vol_min_20"] = _roll(vg, 20, "min", 10)
    df["avg_vol_20"] = v20
    df["mild_volume"] = ((df["vol_ratio"] >= config.VOLUME_RATIO_MIN)
                         & (df["vol_ratio"] <= config.VOLUME_RATIO_MAX)).astype(float).where(df["vol_ratio"].notna())
    # 流動性：近 20 天每天都至少 100 張（1 張 = 1,000 股）；沒有成交量資料時無法判斷 → 不排除
    df["liquid"] = ((df["vol_min_20"] >= config.MIN_DAILY_LOTS * 1000) | df["vol_min_20"].isna()).astype(float)

    # 標籤：從今天收盤買進、持有 hold_days 個交易日的報酬（只用於訓練與評估）
    df["fwd_ret"] = g.shift(-hold_days) / df["close"] - 1
    return df


def add_industry(panel: pd.DataFrame, industries: Optional[Dict[str, str]]) -> pd.DataFrame:
    """產業趨勢：同產業股票的等權指數。指數在季線之上、且近 1 月上漲 → 產業趨勢向上。"""
    df = panel
    df["industry"] = df["ticker"].map(industries or {}) if industries else np.nan
    if df["industry"].isna().all():
        for c in ["ind_mom_20", "ind_gap_ma60", "ind_n"]:
            df[c] = np.nan
        df["ind_up"] = np.nan
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
    df["ind_up"] = ((df["ind_gap_ma60"] > 0) & (df["ind_mom_20"] > 0)).astype(float)
    df.loc[df["ind_gap_ma60"].isna(), "ind_up"] = np.nan
    return df


def add_flows(panel: pd.DataFrame, flows: Optional[pd.DataFrame]) -> pd.DataFrame:
    """三大法人買賣超（股數）→ 近 20 日買超占同期成交量的比例。
    T86 在收盤後才公布，所以一律「延後一天」使用，避免用到當天收盤時還不知道的資訊。"""
    df = panel
    if flows is None or flows.empty or df["volume"].isna().all():
        for c in FLOW_FEATURES:
            df[c] = np.nan
        df["inst_buy"] = np.nan
        return df
    f = flows[["date", "ticker", "foreign_net", "trust_net"]].copy()
    f["date"] = pd.to_datetime(f["date"]).astype("datetime64[ns]")
    df = df.merge(f, on=["date", "ticker"], how="left")
    has = df.groupby("ticker")["foreign_net"].transform(lambda s: s.notna().any())
    tg = df.groupby("ticker")
    vol20 = _roll(df["volume"].where(df["volume"] > 0).groupby(df["ticker"]), 20, "sum", 10)
    for src, out in [("foreign_net", "foreign_net_20"), ("trust_net", "trust_net_20")]:
        s = _roll(df[src].fillna(0).groupby(df["ticker"]), 20, "sum", 10)
        df[out] = (s / vol20).groupby(df["ticker"]).shift(1)   # 延後一天
    df["inst_net_20"] = df["foreign_net_20"] + df["trust_net_20"]
    for c in FLOW_FEATURES:
        df.loc[~has, c] = np.nan
    df["inst_buy"] = (df["inst_net_20"] > 0).astype(float)
    df.loc[df["inst_net_20"].isna(), "inst_buy"] = np.nan
    return df.drop(columns=["foreign_net", "trust_net"])


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


def _covered(panel: pd.DataFrame, cols: List[str], min_share: float = 0.5) -> List[str]:
    return [c for c in cols if c in panel.columns and panel[c].notna().mean() >= min_share]


def build_panel(prices: pd.DataFrame, esg: Optional[pd.DataFrame], financials: Optional[pd.DataFrame],
                hold_days: int, static_esg: bool = False, industries: Optional[Dict[str, str]] = None,
                flows: Optional[pd.DataFrame] = None) -> Tuple[pd.DataFrame, dict]:
    """回傳 (panel, info)。info 裡有各類特徵名稱與資料涵蓋率。"""
    panel = add_technical(prices, hold_days)
    panel = add_industry(panel, industries)
    panel = add_flows(panel, flows)
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
        "extra_features": (_covered(panel, VOLUME_FEATURES) + _covered(panel, INDUSTRY_FEATURES)
                           + _covered(panel, FLOW_FEATURES, 0.2)),
        "has_volume": bool(panel["vol_ratio"].notna().any()),
        "has_industry": bool(panel["ind_up"].notna().any()),
        "has_flows": bool(panel["inst_net_20"].notna().any()),
        "fin_features": fin_cols,
        "esg_features": esg_cols,
        "esg_static": bool(esg_static),
        "fin_static": bool(fin_static),
        "esg_coverage": cov,
        "esg_first_date": (panel.loc[panel["esg_total"].notna(), "date"].min()
                           if "esg_total" in panel.columns and cov > 0 else None),
    }
    return panel, info
