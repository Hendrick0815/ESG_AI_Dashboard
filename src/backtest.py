"""選股規則與回測引擎（合併 app_v5 與 generate_backtest.py 的做法，並修正前視偏差）。

時間軸（每個調倉日 t）：
    t 收盤後用「t 以前」的資料算分數 → 以 t 收盤價換股（扣交易成本）
    → 報酬從 t 的下一個交易日開始計算 → 持有到下一個調倉日收盤（期間權重隨價格漂移）
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from . import config

STRATEGY_AI_ESG = "AI+ESG"
STRATEGY_AI = "單純 AI"
STRATEGY_ESG = "單純 ESG"
STRATEGIES = [STRATEGY_AI_ESG, STRATEGY_AI, STRATEGY_ESG]
STRATEGY_DESC = {
    STRATEGY_AI_ESG: "AI 預測排名與 ESG 排名加權",
    STRATEGY_AI: "只看 AI 預測，不用 ESG",
    STRATEGY_ESG: "只看 ESG 總分",
}


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


def apply_risk_filters(snap: pd.DataFrame) -> pd.DataFrame:
    """風險控制的個股濾網（缺資料時不排除）：
    ① 收盤價在年線之下的股票不買；② 剩下的股票中，近 60 日波動最高的 20% 不買。"""
    out = snap
    if "above_ma_long" in out.columns:
        out = out[out["above_ma_long"].fillna(1) == 1]
    if "vol_60" in out.columns and out["vol_60"].notna().any():
        cap = out["vol_60"].quantile(config.VOL_CAP_QUANTILE)      # 在剩下的股票裡，排除最震盪的 20%
        out = out[out["vol_60"].isna() | (out["vol_60"] <= cap)]
    return out


def score_strategies(snapshot: pd.DataFrame, esg_weight: float, risk_filters: bool = False) -> Dict[str, pd.Series]:
    """snapshot：某個調倉日所有股票（ticker, pred, esg_total...）。回傳各策略的分數（越高越好）。
    risk_filters=True：先排除跌破年線、波動最高 20% 的股票，再排序。"""
    snap = snapshot.set_index("ticker")
    if risk_filters:
        snap = apply_risk_filters(snap)
    scores: Dict[str, pd.Series] = {}
    if snap.empty:
        return scores
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


def slot_weights(top_n: int, scheme: str) -> np.ndarray:
    """Top N 每個名次的權重（總和 1）。"""
    if scheme == "集中加權":
        w = np.array(config.CONVICTION_WEIGHTS[:top_n], dtype=float)
        if top_n > len(w):   # 超過 20 檔的部分給最小權重
            w = np.concatenate([w, np.full(top_n - len(w), config.CONVICTION_WEIGHTS[-1])])
    else:
        w = np.ones(top_n)
    return w / w.sum()


def make_weights(score: pd.Series, top_n: int, scheme: str, fill_cash: bool = False) -> pd.Series:
    """fill_cash=True：合格股票不足 N 檔時，空下來的名額放現金（不把錢集中到少數幾檔）。"""
    top = score.dropna().sort_values(ascending=False).head(top_n)
    if top.empty:
        return pd.Series(dtype=float)
    w = slot_weights(top_n if fill_cash else len(top), scheme)[:len(top)]
    if not fill_cash:
        w = w / w.sum()
    return pd.Series(w, index=top.index)


# ------------------------------------------------------------------ 回測
def trading_cost(old: pd.Series, new: pd.Series) -> float:
    """買進付手續費；賣出付手續費 + 證交稅。old 是換股前（已漂移）的權重。"""
    idx = old.index.union(new.index)
    diff = new.reindex(idx, fill_value=0) - old.reindex(idx, fill_value=0)
    buys, sells = diff.clip(lower=0).sum(), (-diff).clip(lower=0).sum()
    return float(buys * config.COMMISSION + sells * (config.COMMISSION + config.SELL_TAX))


@dataclass
class RiskControl:
    """大盤濾網（每天收盤檢查；選股仍是每月一次）：
    market_exposure[d] = 當天收盤後應有的持股比例（加權指數在年線上 1.0，跌破年線 0.5）。
    只調整持股比例、不在月中換股；比例以 step 為單位調整。"""
    market_exposure: Optional[pd.Series] = None
    step: float = config.EXPOSURE_STEP

    def exposure(self, d) -> float:
        if self.market_exposure is None:
            return 1.0
        v = self.market_exposure.get(d, np.nan)
        return 1.0 if pd.isna(v) else _quantize(float(v), self.step)


def _quantize(x: float, step: float) -> float:
    return float(np.floor(x / step + 1e-9) * step) if step else x


def simulate(targets: Dict[pd.Timestamp, pd.Series], ret_wide: pd.DataFrame,
             risk: Optional[RiskControl] = None) -> pd.DataFrame:
    """targets：{調倉日: 目標權重（總和 ≤ 1，其餘為現金）}；ret_wide：日報酬寬表（index=date）。
    回傳 date, ret, nav, turnover, cost, exposure（持股比例）。"""
    cols = ["date", "ret", "nav", "turnover", "cost", "exposure"]
    if not targets:
        return pd.DataFrame(columns=cols)
    days = ret_wide.index[ret_wide.index >= min(targets)]
    w = pd.Series(dtype=float)          # 目前持股權重；1 - 總和 = 現金
    base = pd.Series(dtype=float)       # 這個月的目標名單（滿倉時的權重）
    nav, scale = 1.0, 1.0
    rows = []
    for d in days:
        r_day = 0.0
        if not w.empty:
            r = ret_wide.loc[d].reindex(w.index).astype(float).fillna(0.0)   # 停牌或無報價當天視為 0
            gross = float((w * (1 + r)).sum() + (1 - w.sum()))
            r_day = gross - 1
            if gross > 0:
                w = w * (1 + r) / gross          # 權重隨價格漂移（買入持有）
        new = None
        if d in targets:
            base = targets[d]
            new = base * (risk.exposure(d) if risk else 1.0)
        elif risk is not None and not base.empty:
            e = risk.exposure(d)
            if abs(e - scale) >= risk.step - 1e-9:   # 只調整比例，不換股
                cur = w / w.sum() * base.sum() if w.sum() > 0 else base
                new = cur * e
        turnover = cost = 0.0
        if new is not None:
            new = new[new > 0]
            if risk is not None:
                scale = risk.exposure(d)
            idx = w.index.union(new.index)
            turnover = float((new.reindex(idx, fill_value=0) - w.reindex(idx, fill_value=0)).abs().sum() / 2)
            cost = trading_cost(w, new)
            w = new.copy()
        ret = (1 + r_day) * (1 - cost) - 1
        nav *= 1 + ret
        rows.append({"date": d, "ret": ret, "nav": nav, "turnover": turnover, "cost": cost,
                     "exposure": float(w.sum())})
    return pd.DataFrame(rows, columns=cols)


def market_regime(bench: pd.DataFrame, index: str = config.MARKET_INDEX, ma: int = config.MARKET_MA,
                  weak: float = config.MARKET_WEAK_EXPOSURE, fallback: Optional[pd.DataFrame] = None) -> Optional[pd.Series]:
    """加權指數收盤價在 ma 日均線之上 → 1.0；之下 → weak。找不到指數就用股票池等權平均代替。只用當天以前的資料。"""
    px = None
    if bench is not None and not bench.empty and index in set(bench["ticker"]):
        px = bench[bench["ticker"] == index].set_index("date")["close"].sort_index()
        if fallback is not None:
            px = px.reindex(px.index.union(fallback.index)).ffill().reindex(fallback.index)
    elif fallback is not None and not fallback.empty:
        px = (1 + fallback.mean(axis=1).fillna(0)).cumprod()
    if px is None or px.notna().sum() < ma:
        return None
    m = px.rolling(ma).mean()
    out = pd.Series(np.where(px < m, weak, 1.0), index=px.index)
    out[m.isna()] = 1.0
    return out


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
