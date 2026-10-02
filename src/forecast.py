"""持有期間的預估績效：某個調倉日買進的持股，到下一個調倉日之間「模型預期」會怎麼走，並和實際走勢對照。

預估方法（都只用調倉日當天以前的資料）：
- 預期超額報酬 = 持股的 AI 預測分數加權平均（模型預測的是「未來 10 個交易日比全體平均多賺多少」）
- 預期大盤報酬 = 加權指數過去一年的平均日報酬
- 預期路徑：第 t 天的累積報酬 = (1 + 大盤日均)^t − 1 ＋ 預期超額 × t / 持有天數
- 區間：該策略過去 60 個交易日的日報酬標準差 σ，第 t 天為 預期 ± z × σ × √t
  （z = 1 約 68% 機率落在內、z = 1.96 約 95%）
"""
from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd

from . import config

Z68, Z95 = 1.0, 1.96


def holding_window(rebalance_dates, latest_date: pd.Timestamp, d: pd.Timestamp,
                   trading_days: pd.DatetimeIndex, hold_days: int = config.HOLD_DAYS) -> pd.DatetimeIndex:
    """調倉日 d 之後的持有期間（不含 d）：到下一個調倉日為止；最後一期資料不夠時，往後補成「預估的交易日」（平日）。"""
    d = pd.Timestamp(d)
    later = [pd.Timestamp(x) for x in rebalance_dates if pd.Timestamp(x) > d]
    known = trading_days[trading_days > d]
    if later:
        return known[known <= later[0]]
    known = known[:hold_days]
    if len(known) >= hold_days:
        return known
    start = known[-1] if len(known) else d
    extra = pd.bdate_range(start + pd.Timedelta(days=1), periods=hold_days - len(known))
    return known.append(extra)


def expected_excess(holdings: pd.DataFrame, evaluation: pd.DataFrame, d: pd.Timestamp) -> Optional[float]:
    """持股的 AI 預測分數（相對全體的預期超額報酬）依權重平均。沒有預測時回傳 None。"""
    pred = evaluation[evaluation["date"] == d].set_index("ticker")["pred"]
    h = holdings.set_index("ticker")["weight"]
    p = pred.reindex(h.index)
    ok = p.notna()
    if not ok.any():
        return None
    w = h[ok] / h[ok].sum()
    return float((w * p[ok]).sum())


def market_drift(bench: pd.DataFrame, d: pd.Timestamp, index: str = config.MARKET_INDEX, lookback: int = 250) -> float:
    """加權指數到 d 為止、過去約一年的平均日報酬（沒有資料時用 0）。"""
    if bench is None or bench.empty or index not in set(bench["ticker"]):
        return 0.0
    px = bench[bench["ticker"] == index].set_index("date")["close"].sort_index()
    r = px[px.index <= d].pct_change().dropna().tail(lookback)
    return float(r.mean()) if len(r) >= 20 else 0.0


def strategy_vol(returns: pd.DataFrame, strategy: str, d: pd.Timestamp, lookback: int = 60,
                 fallback: Optional[float] = None) -> float:
    """策略到 d 為止最近 lookback 個交易日的日報酬標準差；資料不足時用 fallback（例如大盤波動）。"""
    r = returns[(returns["portfolio"] == strategy) & (returns["date"] <= d)].sort_values("date")["ret"].tail(lookback)
    if len(r) >= 20 and r.std() > 0:
        return float(r.std())
    return float(fallback) if fallback else 0.02


def holding_forecast(holdings: pd.DataFrame, evaluation: pd.DataFrame, returns: pd.DataFrame,
                     bench: pd.DataFrame, strategy: str, d: pd.Timestamp, window: pd.DatetimeIndex,
                     hold_days: int = config.HOLD_DAYS) -> Dict:
    """回傳 {'path': DataFrame(date, step, expected, lo68, hi68, lo95, hi95, actual, market),
            'excess': 預期超額, 'drift': 大盤日均, 'sigma': 日波動}；actual／market 只有已發生的日子才有值。"""
    d = pd.Timestamp(d)
    excess = expected_excess(holdings, evaluation, d)
    drift = market_drift(bench, d)
    mkt_r = returns[returns["portfolio"] == config.MARKET_INDEX].set_index("date")["ret"]
    mkt_sigma = float(mkt_r[mkt_r.index <= d].tail(60).std()) if len(mkt_r[mkt_r.index <= d]) >= 20 else None
    sigma = strategy_vol(returns, strategy, d, fallback=mkt_sigma * 1.3 if mkt_sigma else None)

    steps = np.arange(0, len(window) + 1)
    dates = [d] + list(window)
    base = (1 + drift) ** steps - 1
    exp = base + (excess or 0.0) * steps / max(hold_days, 1)
    spread = sigma * np.sqrt(steps)
    path = pd.DataFrame({"date": dates, "step": steps, "expected": exp,
                         "lo68": exp - Z68 * spread, "hi68": exp + Z68 * spread,
                         "lo95": exp - Z95 * spread, "hi95": exp + Z95 * spread})

    def realized(name: str) -> pd.Series:
        r = returns[(returns["portfolio"] == name) & (returns["date"] > d)].set_index("date")["ret"]
        r = r.reindex(window).dropna()
        cum = (1 + r).cumprod() - 1
        return pd.concat([pd.Series([0.0], index=[d]), cum])

    act, mkt = realized(strategy), realized(config.MARKET_INDEX)
    path["actual"] = path["date"].map(act) if len(act) > 1 else np.nan
    path["market"] = path["date"].map(mkt) if len(mkt) > 1 else np.nan
    return {"path": path, "excess": excess, "drift": drift, "sigma": sigma}
