"""論文補充測試（第四章第四節（四））：在正式版本的逐期股票池與相同設定下，比較
    base：正式版本（重現第四章結果）
    mkt ：模型加入大盤狀態特徵（src/config.py USE_MARKET_FEATURES）
    pull：短期轉弱減碼（加權指數距 20 日高點跌逾 5% 時持股減半，Params.pullback_control）
輸出：outputs/research/<run_id>/tables/table_4_15_market_state_tests.csv（各版本 × 策略的績效、風險與模型能力）
      outputs/research/<run_id>/market_state_tests/strategy_returns_<版本>.csv
執行（需先備妥 run_research.py 所需的原始資料）：python scripts/research/run_market_state_tests.py
這些測試只作為穩健性補充，不改變正式結果。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_research as rr  # noqa: E402
from src import config, pipeline  # noqa: E402
from src.research import stats as rs  # noqa: E402

VERSIONS = {"base": "正式版本", "mkt": "加入大盤狀態特徵", "pull": "短期轉弱減碼"}
STRATS = ["單純 AI", "AI+ESG", "規則式 ESG 篩選"]
EPISODES = {"2024 年 7～8 月": ("2024-07-11", "2024-08-05"), "2025 年 3～4 月": ("2025-03-01", "2025-04-21")}


def run(name: str, cfg: dict, ds) -> pipeline.Result:
    rr.apply_config(cfg)
    config.USE_MARKET_FEATURES = name == "mkt"
    p = pipeline.Params(model_name=cfg["model"], top_n=cfg["top_n"], n_estimators=cfg["n_estimators"],
                        esg_weight=cfg["esg_weight"], weighting=cfg["weighting"], risk_control=cfg["risk_control"],
                        start=cfg["history_start"], end=cfg["data_cutoff"], pullback_control=name == "pull")
    t0 = time.time()
    res = pipeline.run(ds, p)
    config.USE_MARKET_FEATURES = False
    print(f"{name}：{time.time() - t0:.0f} 秒", flush=True)
    return res


def summarize(name: str, res, cfg: dict) -> list[dict]:
    start, cut = cfg["backtest_start"], cfg["data_cutoff"]
    w = rr.ret_wide_of(res, start, cut)
    mkt = w["加權指數"]
    ic = pipeline.rank_ic(res.evaluation)
    ic = ic[(ic["date"] >= pd.Timestamp(start)) & (ic["date"] <= pd.Timestamp(cut))]
    rows = []
    for s in STRATS:
        r = w[s].dropna()
        nav = (1 + r).cumprod()
        ann = nav.iloc[-1] ** (252 / len(r)) - 1
        vol = r.std() * np.sqrt(252)
        cp = rs.capm(r, mkt, cfg["risk_free_annual"])
        d = rs.diff_test(r, w["00850"])
        expo = res.risk_log[res.risk_log["portfolio"] == {"規則式 ESG 篩選": "單純 ESG"}.get(s, s)] if len(res.risk_log) else pd.DataFrame()
        row = {"version": name, "版本": VERSIONS[name], "投組": s, "年化報酬": ann, "年化波動": vol,
               "Sharpe": (ann - cfg["risk_free_annual"]) / vol, "最大回撤": float((nav / nav.cummax() - 1).min()),
               "Beta": cp["beta"], "相對00850年化差": d["ann_diff"], "相對00850_p": d["p"],
               "下跌日參與率": float(r[mkt < 0].mean() / mkt[mkt < 0].mean()),
               "平均持股比例": float(expo[(expo["date"] >= pd.Timestamp(start))]["exposure"].mean()) if len(expo) else 1.0,
               "Rank_IC": float(ic["rank_ic"].mean()) if len(ic) else np.nan}
        for k, (a, b) in EPISODES.items():
            row[k] = float((1 + r.loc[a:b]).prod() - 1)
        rows.append(row)
    return rows


def main():
    cfg = json.loads((ROOT / "research_config.json").read_text(encoding="utf-8"))
    rr.apply_config(cfg)
    run_dir = ROOT / "outputs" / "research" / cfg["run_id"]
    out = run_dir / "market_state_tests"
    out.mkdir(parents=True, exist_ok=True)
    ds, px, elig, base = rr.build_dataset(cfg, out)
    rows = []
    for name in VERSIONS:
        res = run(name, cfg, ds)
        rr.ret_wide_of(res, cfg["history_start"], cfg["data_cutoff"]).to_csv(out / f"strategy_returns_{name}.csv")
        rows += summarize(name, res, cfg)
    t = pd.DataFrame(rows)
    t.to_csv(run_dir / "tables" / "table_4_15_market_state_tests.csv", index=False)
    print(t[["版本", "投組", "年化報酬", "最大回撤", "Beta", "Rank_IC"]].to_string(index=False))


if __name__ == "__main__":
    main()
