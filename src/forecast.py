"""持有期間的預估績效：某個調倉日買進的持股，到下一個調倉日之間「模型預期」會怎麼走，並和實際走勢對照。

預估方法（都只用調倉日當天以前的資料）：
- 預期超額報酬 = 持股的 AI 預測分數加權平均（模型預測的是「未來 10 個交易日比全體平均多賺多少」）
- 預期大盤報酬 = 長期平均（config.MARKET_DRIFT_ANNUAL，預設年化 7%），不追近一年漲跌——
  模型無法預測接下來是多頭還是空頭，用近期漲幅外推會在大漲後一律偏多、大跌後一律偏空
- 預期路徑：第 t 天的累積報酬 = (1 + 大盤日均)^t − 1 ＋ 預期超額 × t / 持有天數
- 區間：該策略過去 60 個交易日的日報酬標準差 σ，第 t 天為 預期 ± z × σ × √t
  （z = 1 約 68% 機率落在內、z = 1.96 約 95%）；市場轉為高波動時 σ 會變大、區間自動變寬
- 更新後預估：持有期間已經過 k 天時，從「今天的實際累積報酬」接著往後估剩下的天數
  （同樣的大盤預期與超額，區間只算剩下天數的 √(t−k)）；調倉日當天的原始預估保留，用來檢驗模型
- 市場情境：與論文相同的事前規則（60 日報酬、20 日波動、距 250 日高點回撤），只作參考，不進入預估
"""
from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd

from . import config

Z68, Z95 = 1.0, 1.96


def holding_window(rebalance_dates, latest_date: pd.Timestamp, d: pd.Timestamp,
                   trading_days: pd.DatetimeIndex, hold_days: int = config.HOLD_DAYS,
                   next_date: Optional[pd.Timestamp] = None) -> pd.DatetimeIndex:
    """調倉日 d 之後的持有期間（不含 d）：到下一個調倉日為止。最後一期還沒走完時，
    往後補「預估的交易日」（平日）到下一個預定調倉日 next_date；沒給 next_date 時補到 hold_days 天。"""
    d = pd.Timestamp(d)
    later = [pd.Timestamp(x) for x in rebalance_dates if pd.Timestamp(x) > d]
    known = trading_days[trading_days > d]
    if later:
        return known[known <= later[0]]
    if next_date is not None:
        end = pd.Timestamp(next_date)
        known = known[known <= end]
        start = known[-1] if len(known) else d
        return known.append(pd.bdate_range(start + pd.Timedelta(days=1), end))
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


def market_drift(bench: pd.DataFrame = None, d: pd.Timestamp = None, index: str = config.MARKET_INDEX) -> float:
    """大盤預期日報酬：長期平均（config.MARKET_DRIFT_ANNUAL 換成日報酬）。不使用近期漲跌。"""
    return (1 + config.MARKET_DRIFT_ANNUAL) ** (1 / 252) - 1


REGIME_RULES = {"lookback_return": 60, "vol_window": 20, "dd_window": 250, "bear_return": -0.10,
                "bear_drawdown": -0.15, "high_vol": 0.25, "bull_return": 0.05}   # 與論文表 3-10 相同


def _regime_frame(px: pd.Series) -> pd.DataFrame:
    """每天收盤後的情境（用當天為止的資料）。"""
    r = px.pct_change()
    f = pd.DataFrame({"ret60": px.pct_change(REGIME_RULES["lookback_return"]),
                      "vol20": r.rolling(REGIME_RULES["vol_window"]).std() * np.sqrt(252),
                      "dd": px / px.rolling(REGIME_RULES["dd_window"], min_periods=60).max() - 1})
    bear = (f["ret60"] <= REGIME_RULES["bear_return"]) | (f["dd"] <= REGIME_RULES["bear_drawdown"])
    hv = ~bear & (f["vol20"] >= REGIME_RULES["high_vol"])
    bull = ~bear & ~hv & (f["ret60"] >= REGIME_RULES["bull_return"])
    f["regime"] = np.where(f.isna().any(axis=1), None, np.select([bear, hv, bull], ["空頭", "高波動", "多頭"], "盤整"))
    return f


def market_regime(bench: pd.DataFrame, d: pd.Timestamp, hold_days: int = config.HOLD_DAYS,
                  index: str = config.MARKET_INDEX) -> Optional[Dict]:
    """d 收盤後的市場情境，以及「過去同一情境之後 hold_days 個交易日」加權指數的報酬分布（只用 d 以前已實現的資料）。"""
    if bench is None or bench.empty or index not in set(bench["ticker"]):
        return None
    px = bench[bench["ticker"] == index].set_index("date")["close"].sort_index().astype(float)
    px = px[px.index <= pd.Timestamp(d)]
    if len(px) < 260:
        return None
    f = _regime_frame(px)
    now = f.iloc[-1]
    if now["regime"] is None:
        return None
    fwd = px.shift(-hold_days) / px - 1                      # 已實現的未來報酬（最後 hold_days 天為 NaN）
    same = fwd[(f["regime"] == now["regime"]) & fwd.notna()]
    return {"regime": now["regime"], "ret60": float(now["ret60"]), "vol20": float(now["vol20"]),
            "dd": float(now["dd"]), "n": int(len(same)),
            "fwd_mean": float(same.mean()) if len(same) else np.nan,
            "fwd_up": float((same > 0).mean()) if len(same) else np.nan}


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

    # 更新後預估：從最新的實際值往後估剩下的天數
    for c in ["upd", "upd_lo68", "upd_hi68"]:
        path[c] = np.nan
    known = path["actual"].dropna()
    if 1 < len(known) < len(path):
        k = int(known.index[-1])
        a_k = float(known.iloc[-1])
        rest = path.index[path.index >= k]
        n = (path.loc[rest, "step"] - path.loc[k, "step"]).to_numpy()
        upd = (1 + a_k) * (1 + drift) ** n - 1 + (excess or 0.0) * n / max(hold_days, 1)
        path.loc[rest, "upd"] = upd
        path.loc[rest, "upd_lo68"] = upd - Z68 * sigma * np.sqrt(n)
        path.loc[rest, "upd_hi68"] = upd + Z68 * sigma * np.sqrt(n)
    return {"path": path, "excess": excess, "drift": drift, "sigma": sigma}
