"""第三章表 3-5：主要變數之敘述統計量。
樣本 = 逐期股票池（每個交易日當時的成交金額前 300 大、含之後下市的股票），期間為訓練資料起點至資料截點；
特徵為模型實際使用之原始值（中位數補值之前），被解釋變數為未來 10 個交易日相對報酬（減同日股票池平均）。
輸出：outputs/research/<run_id>/tables/table_3_5_descriptive.csv
執行：python scripts/research/descriptive_stats.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_research as rr  # noqa: E402
from src.features import build_panel  # noqa: E402

# (欄位, 名稱, 單位, 乘數)；百分比變數以 % 呈現
VARS = [
    ("y_rel", "未來 10 日相對報酬", "%", 100),
    ("mom_5", "近 5 日報酬", "%", 100), ("mom_20", "近 20 日報酬", "%", 100), ("mom_60", "近 60 日報酬", "%", 100),
    ("vol_20", "20 日年化波動率", "%", 100), ("bias_20", "月線乖離率", "%", 100), ("gap_ma60", "季線乖離率", "%", 100),
    ("dd_high20", "距 20 日最高價跌幅", "%", 100), ("days_since_high20", "高點距今天數", "日", 1),
    ("down_streak", "連續下跌天數", "日", 1), ("vol_ratio", "量能比", "倍", 1), ("reversal", "短期反轉", "—", 1),
    ("pe", "本益比", "倍", 1), ("pb", "股價淨值比", "倍", 1), ("dividend_yield", "殖利率", "%", 100),
    ("esg_total", "TESG 總分", "分", 1),
]


def main():
    cfg = json.loads((ROOT / "research_config.json").read_text(encoding="utf-8"))
    rr.apply_config(cfg)
    run_dir = ROOT / "outputs" / "research" / cfg["run_id"]
    out = run_dir / "descriptive"
    out.mkdir(parents=True, exist_ok=True)
    ds, px, elig, base = rr.build_dataset(cfg, out)
    prices = ds.prices[(ds.prices["date"] >= pd.Timestamp(cfg["history_start"]))
                       & (ds.prices["date"] <= pd.Timestamp(cfg["data_cutoff"]))]
    panel, _ = build_panel(prices, ds.esg, ds.financials, 10)
    panel = panel.merge(ds.eligible.assign(_in=1), on=["date", "ticker"], how="inner").drop(columns="_in")
    panel["y_rel"] = panel["fwd_ret"] - panel.groupby("date")["fwd_ret"].transform("mean")
    rows = []
    for col, name, unit, k in VARS:
        if col not in panel.columns:
            print("缺少欄位", col)
            continue
        s = panel[col].dropna() * k
        rows.append({"變數": name, "單位": unit, "樣本數": int(s.size), "平均數": s.mean(), "標準差": s.std(),
                     "最小值": s.min(), "第 25 百分位": s.quantile(.25), "中位數": s.median(),
                     "第 75 百分位": s.quantile(.75), "最大值": s.max(),
                     "起始日": panel.loc[panel[col].notna(), "date"].min().date()})
    t = pd.DataFrame(rows)
    t.to_csv(run_dir / "tables" / "table_3_5_descriptive.csv", index=False, encoding="utf-8-sig")
    meta = {"n_obs": int(len(panel)), "n_days": int(panel["date"].nunique()), "n_tickers": int(panel["ticker"].nunique()),
            "start": str(panel["date"].min().date()), "end": str(panel["date"].max().date())}
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    print(meta)
    print(t.to_string(index=False))


if __name__ == "__main__":
    main()
