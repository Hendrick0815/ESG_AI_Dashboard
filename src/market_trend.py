"""大盤趨勢預測：加權指數未來的「方向」（牛／熊）與「風險」（高波動、大回檔）的機率。

資料：data/processed/macro.csv（Yahoo，1997 起）— 加權指數、S&P 500、費城半導體、VIX、美國 10 年期殖利率。
美股收盤在台股收盤之後，所以台股第 t 天只用「t 之前」已收盤的美股資料。

預測目標（每天收盤後預測）：
- 方向：未來 20 個交易日（約 1 個月）／60 個交易日（約 1 季）加權指數是否上漲
- 風險：未來 20 個交易日的年化波動是否 ≥ 25%（高波動）；未來 60 個交易日內是否從今天跌 ≥ 10%（大回檔）

方法：標準化 ＋ 羅吉斯迴歸，滾動式訓練（每 60 個交易日重訓；只用到訓練日為止已知結果的樣本），
2008 年起的每一天都是樣本外預測，用來計算準確率、AUC、Brier 分數，並和「一律猜歷史平均」比較。

結論先講：方向（牛／熊）在樣本外幾乎無法預測（AUC 約 0.4～0.5，不比一律猜漲好）；
風險中「高波動」有明顯預測力（AUC 約 0.85），因為波動有群聚性；「大回檔」只有弱預測力（AUC 約 0.6）。頁面會同時顯示兩者的樣本外成績。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from . import config

EVAL_START = "2008-01-01"
RETRAIN_EVERY = 60
MIN_TRAIN = 1000
BULL, BEAR = 0.60, 0.40

TW_LABELS = {
    "r5": "近 5 日報酬", "r20": "近 20 日報酬", "r60": "近 60 日報酬", "r120": "近 120 日報酬", "r250": "近 250 日報酬",
    "gap20": "距 20 日均線", "gap60": "距 60 日均線", "gap200": "距年線（200 日）", "slope200": "年線斜率",
    "vol20": "20 日波動", "vol60": "60 日波動", "vol_ratio": "波動比（20÷60 日）", "dd250": "距一年高點回撤",
    "rsi14": "RSI(14)", "up20": "近 20 日上漲天數比例",
}
US_LABELS = {
    "spx_r20": "S&P 500 近 20 日報酬", "spx_gap200": "S&P 500 距年線", "sox_r20": "費城半導體近 20 日報酬",
    "sox_gap200": "費城半導體距年線", "vix": "VIX 恐慌指數", "vix_z": "VIX 相對一年平均", "tnx_chg60": "美債 10 年殖利率 60 日變化",
}
FEATURE_LABELS = {**TW_LABELS, **US_LABELS}
RISK_FEATURES = ["vol20", "vol60", "vol_ratio", "dd250", "gap200", "r20", "vix", "vix_z"]

TARGETS = {
    "up20": {"name": "未來 20 日上漲", "H": 20, "kind": "direction", "features": list(FEATURE_LABELS)},
    "up60": {"name": "未來 60 日上漲", "H": 60, "kind": "direction", "features": list(FEATURE_LABELS)},
    "hivol20": {"name": "未來 20 日高波動（年化 ≥ 25%）", "H": 20, "kind": "risk", "features": RISK_FEATURES},
    "dd60": {"name": "未來 60 日內回檔 ≥ 10%", "H": 60, "kind": "risk", "features": ["vol20"]},
}


def load_macro(path=config.MACRO_FILE) -> Optional[pd.DataFrame]:
    try:
        m = pd.read_csv(path, parse_dates=["date"], encoding="utf-8-sig")
    except FileNotFoundError:
        return None
    return m.pivot_table(index="date", columns="ticker", values="close").sort_index()


def build_features(wide: pd.DataFrame) -> pd.DataFrame:
    px = wide["^TWII"].dropna()
    px = px[px > 0]
    days = px.index
    r = px.pct_change()
    f = pd.DataFrame(index=days)
    for n in (5, 20, 60, 120, 250):
        f[f"r{n}"] = px.pct_change(n)
    for n in (20, 60, 200):
        f[f"gap{n}"] = px / px.rolling(n).mean() - 1
    ma200 = px.rolling(200).mean()
    f["slope200"] = ma200 / ma200.shift(20) - 1
    f["vol20"] = r.rolling(20).std() * np.sqrt(252)
    f["vol60"] = r.rolling(60).std() * np.sqrt(252)
    f["vol_ratio"] = f["vol20"] / f["vol60"]
    f["dd250"] = px / px.rolling(250, min_periods=120).max() - 1
    gain, loss = r.clip(lower=0).rolling(14).mean(), (-r.clip(upper=0)).rolling(14).mean()
    f["rsi14"] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    f["up20"] = (r > 0).rolling(20).mean()

    def lagged(col):            # 台股第 t 天只能用 t 之前已收盤的美股資料
        if col not in wide:
            return pd.Series(np.nan, index=days)
        s = wide[col].dropna().rename("v").rename_axis("d").reset_index()
        x = pd.merge_asof(pd.DataFrame({"d": days}), s, on="d", allow_exact_matches=False)
        return pd.Series(x["v"].to_numpy(), index=days)

    spx, sox, vix, tnx = lagged("^GSPC"), lagged("^SOX"), lagged("^VIX"), lagged("^TNX")
    f["spx_r20"] = spx.pct_change(20)
    f["spx_gap200"] = spx / spx.rolling(200).mean() - 1
    f["sox_r20"] = sox.pct_change(20)
    f["sox_gap200"] = sox / sox.rolling(200).mean() - 1
    f["vix"] = vix
    f["vix_z"] = (vix - vix.rolling(250).mean()) / vix.rolling(250).std()
    f["tnx_chg60"] = tnx - tnx.shift(60)
    f["close"] = px
    return f


def build_targets(px: pd.Series) -> pd.DataFrame:
    r = px.pct_change()
    t = pd.DataFrame(index=px.index)
    for H in (20, 60):
        fwd = px.shift(-H) / px - 1
        t[f"fwd{H}"] = fwd
        t[f"up{H}"] = (fwd > 0).astype(float).where(fwd.notna())
    fvol = r[::-1].rolling(20).std()[::-1].shift(-1) * np.sqrt(252)          # 未來 20 日實現波動
    t["fvol20"] = fvol
    t["hivol20"] = (fvol >= 0.25).astype(float).where(px.shift(-20).notna())
    fmin = pd.concat([px.shift(-k) for k in range(1, 61)], axis=1).min(axis=1) / px - 1
    t["fmin60"] = fmin.where(px.shift(-60).notna())
    t["dd60"] = (fmin <= -0.10).astype(float).where(px.shift(-60).notna())
    return t


def _model():
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    return make_pipeline(StandardScaler(), LogisticRegression(C=0.3, max_iter=3000))


def auc(y: np.ndarray, p: np.ndarray) -> float:
    pos, neg = p[y == 1], p[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return np.nan
    ranks = pd.Series(np.concatenate([pos, neg])).rank().to_numpy()
    return float((ranks[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def walk_forward(F: pd.DataFrame, y: pd.Series, cols: List[str], H: int, start: str = EVAL_START):
    """回傳（樣本外機率序列, 最後一個模型）。每 RETRAIN_EVERY 天重訓，預測整段區間一次算完。"""
    days = F.index
    ok = F[cols].notna().all(axis=1)
    pred_days = days[ok & (days >= pd.Timestamp(start))]
    P = pd.Series(np.nan, index=days)
    model = None
    for k in range(0, len(pred_days), RETRAIN_EVERY):
        block = pred_days[k:k + RETRAIN_EVERY]
        pos = days.get_loc(block[0])
        if pos - H < 0:
            continue
        cutoff = days[pos - H]
        tr = ok & (days <= cutoff) & y.notna()
        if tr.sum() < MIN_TRAIN or y[tr].nunique() < 2:
            continue
        model = _model().fit(F.loc[tr, cols], y[tr])
        P[block] = model.predict_proba(F.loc[block, cols])[:, 1]
    # 最新幾天：用到今天為止已知結果的樣本重訓一次（預測未來，不影響樣本外成績）
    last = days[ok][-1]
    tr = ok & (days <= days[days.get_loc(last) - H]) & y.notna()
    final = _model().fit(F.loc[tr, cols], y[tr])
    return P, final


@dataclass
class TrendResult:
    data: pd.DataFrame                   # date, close, 各目標機率 p_<key>、實際 <key>、fwd20/fwd60…
    metrics: Dict[str, Dict]
    latest: Dict[str, Dict]
    asof: pd.Timestamp
    notes: List[str] = field(default_factory=list)


def state_of(p: float) -> str:
    if pd.isna(p):
        return "—"
    return "偏多" if p >= BULL else ("偏空" if p <= BEAR else "中性")


def run(wide: Optional[pd.DataFrame] = None) -> Optional[TrendResult]:
    wide = load_macro() if wide is None else wide
    if wide is None or "^TWII" not in wide or wide["^TWII"].notna().sum() < 1500:
        return None
    F = build_features(wide)
    T = build_targets(F["close"])
    data = pd.concat([F[["close"]], T], axis=1)
    metrics, latest = {}, {}
    for key, spec in TARGETS.items():
        cols = spec["features"]
        P, final = walk_forward(F, T[key], cols, spec["H"])
        data[f"p_{key}"] = P
        ev = pd.DataFrame({"p": P, "y": T[key], "fwd": T.get(f"fwd{spec['H']}")}).dropna(subset=["p", "y"])
        yy, pp = ev["y"].to_numpy(), ev["p"].to_numpy()
        base = float(yy.mean()) if len(yy) else np.nan
        m = {"n": int(len(ev)), "start": ev.index[0] if len(ev) else None, "end": ev.index[-1] if len(ev) else None,
             "auc": auc(yy, pp), "brier": float(((pp - yy) ** 2).mean()) if len(yy) else np.nan,
             "brier_base": float(((base - yy) ** 2).mean()) if len(yy) else np.nan, "base": base}
        rec = ev[ev.index >= "2020-01-01"]
        m["auc_recent"] = auc(rec["y"].to_numpy(), rec["p"].to_numpy())
        if spec["kind"] == "direction":
            m["acc"] = float(((pp >= 0.5) == (yy == 1)).mean())
            stt = np.array([state_of(v) for v in pp])
            for s_ in ("偏多", "中性", "偏空"):
                msk = stt == s_
                m[s_] = {"n": int(msk.sum()), "up": float(yy[msk].mean()) if msk.any() else np.nan,
                         "ret": float(ev["fwd"][msk].mean()) if msk.any() else np.nan}
        else:
            q = pd.qcut(pp, 5, labels=False, duplicates="drop")      # 機率分五組，看實際發生率是否遞增
            m["by_quintile"] = [float(yy[q == g].mean()) for g in sorted(set(q))]
        metrics[key] = m
        # 最新一天的預測與各特徵貢獻（對 log-odds，正值＝提高機率）
        ok = F[cols].notna().all(axis=1)
        d = F.index[ok][-1]
        sc, lr = final.named_steps["standardscaler"], final.named_steps["logisticregression"]
        z = (F.loc[d, cols].to_numpy(dtype=float) - sc.mean_) / sc.scale_
        latest[key] = {"date": d, "p": float(final.predict_proba(F.loc[[d], cols])[0, 1]),
                       "contrib": pd.Series(lr.coef_[0] * z, index=cols).sort_values()}
    asof = F.index[-1]
    return TrendResult(data=data.rename_axis("date").reset_index(), metrics=metrics, latest=latest, asof=asof)


def risk_level(p_vol: float, base_vol: float) -> str:
    """風險燈號：未來 1 個月高波動機率相對歷史平均的倍數。≥ 2 倍為高、≤ 0.75 倍為低，其餘中。"""
    ratio = p_vol / base_vol if base_vol else 1.0
    return "高" if ratio >= 2 else ("低" if ratio <= 0.75 else "中")


# ------------------------------------------------------------------ 目前趨勢（描述現在，不是預測）
TREND_ORDER = ["牛市", "偏多", "盤整", "偏空", "熊市"]


def trend_series(wide: pd.DataFrame) -> pd.DataFrame:
    """每天收盤後的趨勢判斷（只用當天為止的資料）：7 項常見指標各給 多(+1)／中性(0)／空(−1)，加總後分級。
    距一年高點跌超過 20% 依慣例直接判為熊市。"""
    px = wide["^TWII"].dropna()
    px = px[px > 0]
    days = px.index
    ma60, ma200 = px.rolling(60).mean(), px.rolling(200).mean()
    t = pd.DataFrame(index=days)
    t["close"], t["ma60"], t["ma200"] = px, ma60, ma200
    t["gap200"] = px / ma200 - 1
    t["slope200"] = ma200 / ma200.shift(20) - 1
    t["dd250"] = px / px.rolling(250, min_periods=120).max() - 1
    t["r60"] = px.pct_change(60)

    def lag(col):
        if col not in wide:
            return pd.Series(np.nan, index=days)
        s = wide[col].dropna().rename("v").rename_axis("d").reset_index()
        x = pd.merge_asof(pd.DataFrame({"d": days}), s, on="d", allow_exact_matches=False)
        return pd.Series(x["v"].to_numpy(), index=days)

    spx = lag("^GSPC")
    t["spx_gap200"] = spx / spx.rolling(200).mean() - 1
    t["vix"] = lag("^VIX")
    sig = pd.DataFrame(index=days)
    sig["年線位置"] = np.sign(t["gap200"])
    sig["年線方向"] = np.where(t["slope200"] > 0.002, 1, np.where(t["slope200"] < -0.002, -1, 0))
    sig["均線排列"] = np.sign(t["ma60"] - t["ma200"])
    sig["距一年高點"] = np.where(t["dd250"] >= -0.10, 1, np.where(t["dd250"] <= -0.20, -1, 0))
    sig["近 60 日漲跌"] = np.where(t["r60"] >= 0.05, 1, np.where(t["r60"] <= -0.10, -1, 0))
    sig["美股趨勢"] = np.sign(t["spx_gap200"])
    sig["VIX 恐慌指數"] = np.where(t["vix"] < 20, 1, np.where(t["vix"] > 30, -1, 0))
    valid = t[["gap200", "slope200", "dd250", "r60"]].notna().all(axis=1)
    score = sig.fillna(0).sum(axis=1)
    verdict = pd.Series(np.select([t["dd250"] <= -0.20, score >= 4, score >= 2, score >= -1],
                                  ["熊市", "牛市", "偏多", "盤整"], "偏空"), index=days)
    t["score"] = score
    t["verdict"] = verdict.where(valid)
    return pd.concat([t, sig.add_prefix("sig_")], axis=1)


def current_trend(wide: pd.DataFrame) -> Dict:
    """最新一天的趨勢表（指標、目前數值、判斷、說明）與總結。"""
    ts = trend_series(wide)
    ts = ts[ts["verdict"].notna()]
    now = ts.iloc[-1]
    v = now["verdict"]
    since = ts.index[(ts["verdict"] != v)].max()
    start = ts.index[ts.index > since][0] if pd.notna(since) else ts.index[0]
    lab = {1: "🟢 多", 0: "⚪ 中性", -1: "🔴 空"}
    rows = [
        ("年線位置", f"加權指數 {now['close']:,.0f}，年線 {now['ma200']:,.0f}（{now['gap200']:+.1%}）",
         "站上年線（200 日均線）為多，跌破為空"),
        ("年線方向", f"年線近 20 日 {now['slope200']:+.2%}", "年線上揚為多、下彎為空，持平為中性"),
        ("均線排列", f"季線 {now['ma60']:,.0f} {'＞' if now['ma60'] > now['ma200'] else '＜'} 年線 {now['ma200']:,.0f}",
         "季線（60 日）在年線之上為多頭排列"),
        ("距一年高點", f"{now['dd250']:+.1%}", "跌幅 10% 以內為多；10～20% 為修正（中性）；超過 20% 為熊市"),
        ("近 60 日漲跌", f"{now['r60']:+.1%}", "漲 ≥ 5% 為多、跌 ≥ 10% 為空"),
        ("美股趨勢", f"S&P 500 距年線 {now['spx_gap200']:+.1%}" if pd.notna(now["spx_gap200"]) else "—",
         "前一晚 S&P 500 在年線之上為多"),
        ("VIX 恐慌指數", f"{now['vix']:.1f}" if pd.notna(now["vix"]) else "—", "低於 20 市場平靜為多、高於 30 恐慌為空"),
    ]
    table = pd.DataFrame([{"指標": n, "目前數值": val, "判斷": lab[int(now[f"sig_{n}"]) if pd.notna(now[f"sig_{n}"]) else 0],
                           "判斷標準": rule} for n, val, rule in rows])
    return {"date": ts.index[-1], "verdict": v, "score": int(now["score"]), "since": start,
            "days": int((ts.index >= start).sum()), "table": table, "series": ts,
            "n_bull": int((table["判斷"] == lab[1]).sum()), "n_bear": int((table["判斷"] == lab[-1]).sum())}
