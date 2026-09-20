"""選股規則與回測引擎（合併 app_v5 與 generate_backtest.py 的做法，並修正前視偏差）。

時間軸（每個調倉日 t）：
    t 收盤後用「t 以前」的資料算分數 → 以 t 收盤價換股（扣交易成本）
    → 報酬從 t 的下一個交易日開始計算 → 持有到下一個調倉日收盤（期間權重隨價格漂移）
"""
from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd

from . import config

STRATEGY_AI_ESG = "AI+ESG"
STRATEGY_AI = "單純 AI"
STRATEGY_ESG = "單純 ESG"
STRATEGIES = [STRATEGY_AI_ESG, STRATEGY_AI, STRATEGY_ESG]


# ------------------------------------------------------------------ 調倉日
def rebalance_schedule(trading_days: pd.DatetimeIndex, first_allowed: pd.Timestamp) -> List[pd.Timestamp]:
    """每月調倉：每個月最後一個交易日。"""
    days = trading_days[trading_days >= first_allowed]
    if len(days) == 0:
        return []
    s = pd.Series(days, index=days)
    last_in_month = s.groupby(days.to_period("M")).max()
    # 資料的最後一個月通常還沒結束，不當作調倉日
    out = [pd.Timestamp(x) for x in last_in_month.values]
    last = pd.Timestamp(trading_days[-1])
    month_finished = (last + pd.offsets.BDay(1)).month != last.month
    if out and out[-1] == last and not month_finished:
        out = out[:-1]
    return out


# ------------------------------------------------------------------ 選股分數
def _pct_rank(s: pd.Series) -> pd.Series:
    return s.rank(pct=True)


def apply_esg_rules(df: pd.DataFrame) -> pd.DataFrame:
    """排除爭議分數 > 3 與 EPS 為負的公司（欄位存在時才套用）。"""
    out = df
    if "controversy_score" in out.columns:
        out = out[out["controversy_score"].isna() | (out["controversy_score"] <= 3)]
    if "eps" in out.columns:
        out = out[out["eps"].isna() | (out["eps"] >= 0)]
    return out


def score_strategies(snapshot: pd.DataFrame, esg_weight: float) -> Dict[str, pd.Series]:
    """snapshot：某個調倉日所有股票（ticker, pred, esg_total...）。回傳各策略的分數（越高越好）。"""
    snap = snapshot.set_index("ticker")
    scores: Dict[str, pd.Series] = {}
    if "pred" in snap.columns and snap["pred"].notna().any():
        scores[STRATEGY_AI] = snap["pred"].dropna()
        filt = apply_esg_rules(snap.dropna(subset=["pred"]))
        ai_rank = _pct_rank(filt["pred"])
        if "esg_total" in filt.columns and filt["esg_total"].notna().any():
            esg_rank = _pct_rank(filt["esg_total"]).fillna(0.5)   # 沒有評等 → 視為中間值
            scores[STRATEGY_AI_ESG] = (1 - esg_weight) * ai_rank + esg_weight * esg_rank
        else:
            scores[STRATEGY_AI_ESG] = ai_rank
    if "esg_total" in snap.columns:
        e = apply_esg_rules(snap)["esg_total"].dropna()
        if not e.empty:
            scores[STRATEGY_ESG] = e
    return scores


def make_weights(score: pd.Series, top_n: int, scheme: str) -> pd.Series:
    top = score.sort_values(ascending=False).head(top_n)
    if top.empty:
        return pd.Series(dtype=float)
    if scheme == "集中加權":
        w = np.array(config.CONVICTION_WEIGHTS[:len(top)], dtype=float)
        if len(top) > len(w):   # 超過 20 檔的部分給最小權重
            w = np.concatenate([w, np.full(len(top) - len(w), config.CONVICTION_WEIGHTS[-1])])
    else:
        w = np.ones(len(top))
    return pd.Series(w / w.sum(), index=top.index)


# ------------------------------------------------------------------ 回測
def trading_cost(old: pd.Series, new: pd.Series) -> float:
    """買進付手續費；賣出付手續費 + 證交稅。old 是換股前（已漂移）的權重。"""
    idx = old.index.union(new.index)
    diff = new.reindex(idx, fill_value=0) - old.reindex(idx, fill_value=0)
    buys, sells = diff.clip(lower=0).sum(), (-diff).clip(lower=0).sum()
    return float(buys * config.COMMISSION + sells * (config.COMMISSION + config.SELL_TAX))


def simulate(targets: Dict[pd.Timestamp, pd.Series], ret_wide: pd.DataFrame) -> pd.DataFrame:
    """targets：{調倉日: 目標權重}；ret_wide：日報酬寬表（index=date）。
    回傳 date, ret, nav, turnover, cost。"""
    if not targets:
        return pd.DataFrame(columns=["date", "ret", "nav", "turnover", "cost"])
    days = ret_wide.index[ret_wide.index >= min(targets)]
    w = pd.Series(dtype=float)          # 目前持股權重（總和 1；空的代表全部現金）
    nav, rows = 1.0, []
    for d in days:
        r_day = 0.0
        if not w.empty:
            r = ret_wide.loc[d].reindex(w.index).astype(float).fillna(0.0)   # 停牌或無報價當天視為 0
            gross = float((w * (1 + r)).sum())
            r_day = gross - 1
            if gross > 0:
                w = w * (1 + r) / gross          # 權重隨價格漂移（買入持有）
        turnover = cost = 0.0
        if d in targets:
            new = targets[d]
            idx = w.index.union(new.index)
            turnover = float((new.reindex(idx, fill_value=0) - w.reindex(idx, fill_value=0)).abs().sum() / 2)
            cost = trading_cost(w, new)
            w = new.copy()
        ret = (1 + r_day) * (1 - cost) - 1
        nav *= 1 + ret
        rows.append({"date": d, "ret": ret, "nav": nav, "turnover": turnover, "cost": cost})
    return pd.DataFrame(rows)


def benchmark_returns(bench: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    if bench is None or bench.empty:
        return pd.DataFrame(columns=["date", "portfolio", "ret", "nav"])
    rows = []
    for t, g in bench.groupby("ticker"):
        g = g.sort_values("date")
        g = g[(g["date"] >= start) & (g["date"] <= end)]
        if len(g) < 2:
            continue
        ret = g["close"].pct_change().fillna(0.0)
        rows.append(pd.DataFrame({"date": g["date"].values, "portfolio": t, "ret": ret.values,
                                  "nav": (1 + ret).cumprod().values}))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=["date", "portfolio", "ret", "nav"])
