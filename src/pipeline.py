"""把資料 → 特徵 → 模型 → 選股 → 回測串起來。畫面（Streamlit）和指令列都呼叫這裡。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd

from . import backtest as bt
from . import config
from .features import build_panel
from .metrics import performance_table
from .models import walk_forward
from .store import Dataset


@dataclass(frozen=True)
class Params:
    model_name: str = "Random Forest"
    top_n: int = config.DEFAULT_TOP_N
    n_estimators: int = config.DEFAULT_N_ESTIMATORS
    esg_weight: float = config.DEFAULT_ESG_WEIGHT
    weighting: str = "等權"                  # 等權 / 集中加權
    static_esg: bool = False                 # True = 用最新 ESG 回填過去（有前視偏差，僅供對照）
    start: Optional[str] = None
    end: Optional[str] = None
    tickers: Optional[tuple] = None          # None = 使用資料裡全部股票
    risk_control: bool = True                # 不買跌破年線／最震盪的股票＋大盤跌破年線持股減半

    @property
    def hold_days(self) -> int:
        return config.HOLD_DAYS            # 固定每月調倉


@dataclass
class Result:
    params: Params
    panel_info: Dict
    test_start: pd.Timestamp
    rebalance_dates: List[pd.Timestamp]
    latest_date: pd.Timestamp
    returns: pd.DataFrame           # date, portfolio, ret, nav（策略＋基準）
    perf: pd.DataFrame              # performance_table
    holdings: pd.DataFrame          # date, portfolio, ticker, weight, score
    latest: pd.DataFrame            # 最新一天的選股（同上欄位）
    trades: pd.DataFrame            # date, portfolio, turnover, cost
    evaluation: pd.DataFrame        # date, ticker, pred, fwd_ret（已實現的才有）
    importance: pd.DataFrame        # feature, importance
    train_log: pd.DataFrame
    model: object = None
    last_X: Optional[pd.DataFrame] = None
    notes: List[str] = field(default_factory=list)
    risk_log: pd.DataFrame = field(default_factory=pd.DataFrame)   # date, portfolio, exposure（持股比例）


def _first_test_day(trading_days: pd.DatetimeIndex, hold_days: int) -> pd.Timestamp:
    """測試期起點：預留「60 日指標暖機 + 至少一年訓練」；資料不夠長時改用前 40%。"""
    n = len(trading_days)
    min_train = min(config.MIN_TRAIN_DAYS + 60, int(n * 0.4))
    idx = min(min_train + hold_days, n - 1)
    return pd.Timestamp(trading_days[idx])


def run(ds: Dataset, p: Params, progress=None) -> Result:
    """progress(完成數, 總數, 目前調倉日)：訓練進度回報（網頁的進度條用）。"""
    notes: List[str] = list(ds.notes)
    prices = ds.prices
    if p.tickers:
        prices = prices[prices["ticker"].isin(p.tickers)]
    if p.start:
        prices = prices[prices["date"] >= pd.Timestamp(p.start)]
    if p.end:
        prices = prices[prices["date"] <= pd.Timestamp(p.end)]
    if prices.empty:
        raise ValueError("選定的期間／股票沒有價格資料。")
    n_tickers = prices["ticker"].nunique()
    if n_tickers <= p.top_n:
        notes.append(f"股票池只有 {n_tickers} 檔，不多於 Top N（{p.top_n}），各策略會持有幾乎相同的股票。")

    panel, info = build_panel(prices, ds.esg, ds.financials, p.hold_days, static_esg=p.static_esg)
    if info["esg_static"]:
        notes.append("⚠️ ESG 以「最新一期」回填到所有歷史日期，回測含前視偏差，只能當對照組。")

    trading_days = pd.DatetimeIndex(sorted(panel["date"].unique()))
    if len(trading_days) < 120:
        raise ValueError(f"只有 {len(trading_days)} 個交易日，資料太短，建議至少 1 年。")
    test_start = _first_test_day(trading_days, p.hold_days)
    schedule = bt.rebalance_schedule(trading_days, test_start)
    last_day = pd.Timestamp(trading_days[-1])
    pred_dates = schedule + ([last_day] if last_day not in schedule else [])

    features = info["tech_features"] + info["fin_features"]      # 模型不使用 ESG（ESG 另外融合）
    wf = walk_forward(panel, features, pred_dates, trading_days, p.hold_days, p.model_name,
                      p.n_estimators, retrain_every=config.RETRAIN_EVERY, required=info["tech_features"],
                      progress=progress)
    if wf.predictions.empty:
        raise ValueError("訓練樣本不足，模型無法產生預測。請拉長資料期間或擴大股票池。")

    from .features import RISK_COLS
    snap_cols = ["date", "ticker"] + [c for c in ["esg_total", "controversy_score", "eps", *RISK_COLS]
                                      if c in panel.columns]
    # 單純 ESG 不需要模型：沒有預測的股票也要納入
    snaps = panel[panel["date"].isin(pred_dates)][snap_cols].merge(wf.predictions, on=["date", "ticker"], how="left")

    targets: Dict[str, Dict[pd.Timestamp, pd.Series]] = {s: {} for s in bt.STRATEGIES}
    hold_rows = []
    for d, snap in snaps.groupby("date"):
        scores = bt.score_strategies(snap, p.esg_weight, risk_filters=p.risk_control)
        for strat, sc in scores.items():
            w = bt.make_weights(sc, p.top_n, p.weighting)
            if d in schedule:
                targets[strat][d] = w
            hold_rows.append(pd.DataFrame({"date": d, "portfolio": strat, "ticker": w.index,
                                           "weight": w.values, "score": sc.reindex(w.index).values}))
    # 某調倉日沒有分數（例如 ESG 尚未公告）→ 該期持有現金，讓三個策略的比較期間一致
    for strat, tg in targets.items():
        if tg:
            for d in schedule:
                tg.setdefault(d, pd.Series(dtype=float))
            targets[strat] = dict(sorted(tg.items()))
    holdings = pd.concat(hold_rows, ignore_index=True) if hold_rows else \
        pd.DataFrame(columns=["date", "portfolio", "ticker", "weight", "score"])

    ret_wide = panel.pivot_table(index="date", columns="ticker", values="ret_1d").sort_index()
    risk = None
    if p.risk_control:
        if ds.benchmarks.empty or config.MARKET_INDEX not in set(ds.benchmarks["ticker"]):
            notes.append("找不到加權指數（^TWII），大盤年線改用股票池等權平均計算。")
        risk = bt.RiskControl(market_exposure=bt.market_regime(ds.benchmarks, fallback=ret_wide))
    series, trades, risk_rows = [], [], []
    for strat in bt.STRATEGIES:
        if not targets[strat]:
            why = "模型無預測" if strat == bt.STRATEGY_AI else "缺少 ESG 資料"
            notes.append(f"「{strat}」沒有可用的選股（{why}）。")
            continue
        sim = bt.simulate(targets[strat], ret_wide, risk)
        sim["portfolio"] = strat
        series.append(sim[["date", "portfolio", "ret", "nav"]])
        trades.append(sim.loc[sim["turnover"] > 0, ["date", "portfolio", "turnover", "cost"]])
        risk_rows.append(sim[["date", "portfolio", "exposure"]])

    bt_start = min(min(t) for t in targets.values() if t)
    bench = bt.benchmark_returns(ds.benchmarks, bt_start, last_day)
    returns = pd.concat(series + [bench], ignore_index=True)
    returns["date"] = pd.to_datetime(returns["date"])

    evaluation = wf.predictions.merge(panel[["date", "ticker", "fwd_ret"]], on=["date", "ticker"], how="left")
    importance = pd.DataFrame(columns=["feature", "importance"])
    if wf.model is not None and wf.features:
        importance = (pd.DataFrame({"feature": wf.features, "importance": wf.model.feature_importances_})
                        .sort_values("importance", ascending=False).reset_index(drop=True))

    if info["esg_coverage"] == 0:
        notes.append("目前沒有任何 ESG 資料對得上回測期間：AI+ESG 會等於單純 AI，單純 ESG 無法計算。")
    elif info["esg_first_date"] is not None and info["esg_first_date"] > bt_start and not info["esg_static"]:
        notes.append(f"ESG 資料最早從 {pd.Timestamp(info['esg_first_date']).date()} 才有，"
                     f"在那之前 AI+ESG 等同單純 AI、單純 ESG 為空手。補齊 TEJ 歷史各期評等即可改善。")

    latest = holdings[holdings["date"] == last_day] if not holdings.empty else holdings
    return Result(
        params=p, panel_info=info, test_start=bt_start, rebalance_dates=schedule, latest_date=last_day,
        returns=returns, perf=performance_table(returns), holdings=holdings, latest=latest,
        trades=pd.concat(trades, ignore_index=True) if trades else pd.DataFrame(columns=["date", "portfolio", "turnover", "cost"]),
        evaluation=evaluation, importance=importance, train_log=pd.DataFrame(wf.train_log),
        model=wf.model, last_X=wf.last_X, notes=notes,
        risk_log=pd.concat(risk_rows, ignore_index=True) if risk_rows else pd.DataFrame(),
    )


def rank_ic(evaluation: pd.DataFrame) -> pd.DataFrame:
    """每個調倉日：預測分數與實際報酬的 Spearman 相關（Rank IC）。"""
    ev = evaluation.dropna(subset=["pred", "fwd_ret"])
    rows = []
    for d, g in ev.groupby("date"):
        if len(g) >= 3:
            rows.append({"date": d, "rank_ic": g["pred"].rank().corr(g["fwd_ret"].rank())})
    return pd.DataFrame(rows, columns=["date", "rank_ic"])
