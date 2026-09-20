"""AI 模型：Random Forest / XGBoost / 兩者平均（Ensemble），以滾動（walk-forward）方式訓練。

做法
- 每個調倉日 t 才訓練／預測，訓練資料只用「標籤在 t 以前就已經確定」的樣本：
  樣本日期 <= t 往前 hold_days 個交易日（其未來報酬在 t 當天收盤前已實現）。
- 預測目標：未來 hold_days 日報酬「減去當天全部股票的平均」（相對報酬），
  讓模型專心排序股票，而不是猜大盤漲跌。
- 缺值用訓練集的中位數補，不會用到測試期的資訊。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

try:
    from sklearn.ensemble import RandomForestRegressor
    SKLEARN_AVAILABLE = True
except Exception:  # pragma: no cover
    SKLEARN_AVAILABLE = False

try:
    import xgboost as xgb
    XGBOOST_AVAILABLE = True
except Exception:  # pragma: no cover
    XGBOOST_AVAILABLE = False


def available_models() -> List[str]:
    out = []
    if SKLEARN_AVAILABLE:
        out.append("Random Forest")
    if XGBOOST_AVAILABLE:
        out.append("XGBoost")
    if SKLEARN_AVAILABLE and XGBOOST_AVAILABLE:
        out.append("Ensemble (RF+XGB)")
    return out


def _rf(n):
    # 資料量小（數千筆），執行緒開太多反而花時間在協調上，最多用 4 核
    return RandomForestRegressor(n_estimators=n, max_depth=6, min_samples_leaf=20, max_features=0.7,
                                 max_samples=0.5, random_state=42, n_jobs=min(4, os.cpu_count() or 1))


def _xgb(n):
    return xgb.XGBRegressor(n_estimators=n, max_depth=3, learning_rate=0.05, subsample=0.8,
                            colsample_bytree=0.8, min_child_weight=20, objective="reg:squarederror",
                            random_state=42, n_jobs=min(4, os.cpu_count() or 1), verbosity=0)


class Model:
    """統一介面：fit / predict / feature_importances_"""

    def __init__(self, name: str, n_estimators: int):
        if name == "Random Forest":
            if not SKLEARN_AVAILABLE:
                raise ImportError("請安裝 scikit-learn")
            self.models = [_rf(n_estimators)]
        elif name == "XGBoost":
            if not XGBOOST_AVAILABLE:
                raise ImportError("請安裝 xgboost")
            self.models = [_xgb(n_estimators)]
        elif name.startswith("Ensemble"):
            if not (SKLEARN_AVAILABLE and XGBOOST_AVAILABLE):
                raise ImportError("Ensemble 需要 scikit-learn 與 xgboost")
            self.models = [_rf(n_estimators), _xgb(n_estimators)]
        else:
            raise ValueError(f"不支援的模型：{name}")
        self.name = name

    def fit(self, X, y):
        for m in self.models:
            m.fit(X, y)
        return self

    def predict(self, X):
        return np.mean([m.predict(X) for m in self.models], axis=0)

    @property
    def feature_importances_(self):
        imps = [m.feature_importances_ for m in self.models]
        imps = [i / i.sum() if i.sum() > 0 else i for i in imps]
        return np.mean(imps, axis=0)


@dataclass
class WalkForwardResult:
    predictions: pd.DataFrame            # date, ticker, pred（每個調倉日）
    model: Optional[Model]               # 最後一次訓練的模型
    features: List[str]                  # 最後一次訓練實際使用的特徵
    last_X: Optional[pd.DataFrame]       # 最後一次預測的特徵矩陣（SHAP 用）
    train_log: List[Dict] = field(default_factory=list)


def walk_forward(panel: pd.DataFrame, features: List[str], rebalance_dates: List[pd.Timestamp],
                 trading_days: pd.DatetimeIndex, hold_days: int, model_name: str, n_estimators: int,
                 retrain_every: int = 1, required: Optional[List[str]] = None,
                 min_train_rows: int = 100, sample_every: int = 5, progress=None) -> WalkForwardResult:
    """sample_every：訓練樣本每隔幾個交易日取一天。相鄰幾天的未來報酬高度重疊，
    全取只會變慢、不會多學到東西；每 5 天取一次速度快約 5 倍。"""
    required = required or []
    sampled_days = set(trading_days[::max(1, sample_every)])
    day_pos = {d: i for i, d in enumerate(trading_days)}
    preds, train_log = [], []
    model, used, medians, last_X = None, [], None, None

    for k, t in enumerate(rebalance_dates):
        if progress:
            progress(k, len(rebalance_dates), t)
        pos = day_pos[t]
        cutoff = trading_days[pos - hold_days] if pos - hold_days >= 0 else None
        if cutoff is None:
            continue
        if model is None or k % retrain_every == 0:
            train = panel[(panel["date"] <= cutoff) & panel["date"].isin(sampled_days)] \
                .dropna(subset=["fwd_ret", *required])
            cols = [c for c in features if c in train.columns and train[c].notna().any()]
            if len(train) < min_train_rows or not cols:
                continue
            medians = train[cols].median()
            X = train[cols].fillna(medians)
            y = train["fwd_ret"] - train.groupby("date")["fwd_ret"].transform("mean")
            model = Model(model_name, n_estimators).fit(X, y)
            used = cols
            train_log.append({"rebalance_date": t, "train_end": cutoff, "n_samples": len(train),
                              "n_features": len(cols)})
        today = panel[panel["date"] == t].dropna(subset=required)
        if today.empty:
            continue
        X_t = today[used].fillna(medians)
        preds.append(pd.DataFrame({"date": t, "ticker": today["ticker"].values,
                                   "pred": model.predict(X_t)}))
        last_X = X_t

    pred_df = pd.concat(preds, ignore_index=True) if preds else pd.DataFrame(columns=["date", "ticker", "pred"])
    return WalkForwardResult(pred_df, model, used, last_X, train_log)
