"""統一的績效計算（取代原本三套定義不同的函式）。

定義：
- 累積報酬 = 期末淨值 / 期初淨值 - 1
- 年化報酬 = 幾何年化 (1 + 累積報酬) ^ (252 / 天數) - 1
- 年化波動 = 日報酬標準差 × √252
- Sharpe   = (年化報酬 - 無風險利率) / 年化波動
- 最大回撤 = 淨值相對歷史高點（含起始淨值 1）的最大跌幅
"""
from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd

from . import config

METRIC_LABELS = {
    "cum_return": "累積報酬",
    "ann_return": "年化報酬",
    "ann_vol": "年化波動",
    "sharpe": "Sharpe",
    "max_drawdown": "最大回撤",
    "daily_mean": "日報酬平均",
    "daily_var": "日報酬變異數",
    "n_days": "交易日數",
}
PCT_METRICS = {"cum_return", "ann_return", "ann_vol", "max_drawdown", "daily_mean"}


def performance(returns: pd.Series, rf: float = config.RISK_FREE_RATE) -> Dict[str, float]:
    r = pd.Series(returns, dtype=float).dropna()
    if r.empty:
        return {k: np.nan for k in METRIC_LABELS}
    wealth = (1 + r).cumprod()
    cum = wealth.iloc[-1] - 1
    ann_ret = (1 + cum) ** (config.TRADING_DAYS / len(r)) - 1 if cum > -1 else -1.0
    ann_vol = r.std(ddof=1) * np.sqrt(config.TRADING_DAYS) if len(r) > 1 else np.nan
    sharpe = (ann_ret - rf) / ann_vol if ann_vol and ann_vol > 0 else np.nan
    peak = np.maximum(wealth.cummax(), 1.0)
    mdd = float(min((wealth / peak - 1).min(), 0.0))
    return {
        "cum_return": float(cum),
        "ann_return": float(ann_ret),
        "ann_vol": float(ann_vol) if pd.notna(ann_vol) else np.nan,
        "sharpe": float(sharpe) if pd.notna(sharpe) else np.nan,
        "max_drawdown": mdd,
        "daily_mean": float(r.mean()),
        "daily_var": float(r.var(ddof=1)) if len(r) > 1 else np.nan,
        "n_days": int(len(r)),
    }


def performance_table(panel: pd.DataFrame, rf: float = config.RISK_FREE_RATE) -> pd.DataFrame:
    """panel 欄位：date, portfolio, ret → 每個 portfolio 一列。"""
    rows = []
    for name, g in panel.groupby("portfolio", sort=False):
        m = performance(g.sort_values("date")["ret"], rf)
        m["portfolio"] = name
        rows.append(m)
    if not rows:
        return pd.DataFrame(columns=["portfolio", *METRIC_LABELS])
    return pd.DataFrame(rows)[["portfolio", *METRIC_LABELS]]


def price_metrics(close: pd.Series, rf: float = config.RISK_FREE_RATE) -> Dict[str, float]:
    """單一標的收盤價序列的績效（個股分析頁使用）。"""
    return performance(pd.Series(close, dtype=float).pct_change(), rf)


def drawdown_series(returns: pd.Series) -> pd.Series:
    wealth = (1 + pd.Series(returns, dtype=float).fillna(0)).cumprod()
    return wealth / np.maximum(wealth.cummax(), 1.0) - 1


def fmt_pct(x) -> str:
    return "-" if x is None or pd.isna(x) else f"{x:.2%}"


def fmt_num(x, digits: int = 2) -> str:
    return "-" if x is None or pd.isna(x) else f"{x:.{digits}f}"


def format_table(tbl: pd.DataFrame) -> pd.DataFrame:
    """把 performance_table 轉成中文欄名＋格式化字串，方便直接顯示。"""
    out = pd.DataFrame({"投組": tbl["portfolio"]})
    for k, label in METRIC_LABELS.items():
        if k in PCT_METRICS:
            out[label] = tbl[k].map(fmt_pct)
        elif k == "daily_var":
            out[label] = tbl[k].map(lambda v: fmt_num(v, 6))
        elif k == "n_days":
            out[label] = tbl[k].map(lambda v: "-" if pd.isna(v) else str(int(v)))
        else:
            out[label] = tbl[k].map(lambda v: fmt_num(v, 3))
    return out
