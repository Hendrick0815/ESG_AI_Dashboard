"""在指令列跑回測並輸出 CSV（取代舊的 generate_backtest.py）。

    python scripts/run_backtest.py
    python scripts/run_backtest.py --demo sample_1y --top-n 3
    python scripts/run_backtest.py --model XGBoost --weighting 集中加權
（固定每月調倉、扣交易成本）
輸出在 outputs/：strategy_returns.csv、performance.csv、holdings.csv、latest_picks.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from src import cache, config, store  # noqa: E402
from src.metrics import format_table  # noqa: E402
from src.models import available_models  # noqa: E402
from src.pipeline import Params, run  # noqa: E402
from src.utils import write_csv  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="ESG-AI 選股回測")
    ap.add_argument("--demo", default=None, help="使用示範資料集（例如 sample_1y）")
    ap.add_argument("--model", default=(available_models() or ["Random Forest"])[0])
    ap.add_argument("--top-n", type=int, default=config.DEFAULT_TOP_N)
    ap.add_argument("--trees", type=int, default=config.DEFAULT_N_ESTIMATORS)
    ap.add_argument("--esg-weight", type=float, default=config.DEFAULT_ESG_WEIGHT)
    ap.add_argument("--weighting", choices=["等權", "集中加權"], default=config.DEFAULT_WEIGHTING)
    ap.add_argument("--static-esg", action="store_true", help="用最新 ESG 回填歷史（有前視偏差）")
    args = ap.parse_args()

    ds = store.load_dataset("demo", args.demo) if args.demo else store.load_dataset("real")
    p = Params(model_name=args.model, top_n=args.top_n, n_estimators=args.trees,
               esg_weight=args.esg_weight, weighting=args.weighting,
               static_esg=args.static_esg)
    r, cached = cache.get_or_run("demo" if args.demo else "real", args.demo, p, lambda: ds, run,
                                 progress=lambda i, n, d: print(f"   訓練 {i + 1}/{n}", end="\r"))
    print("（使用存檔結果）" if cached else "\n（已存檔，網頁用同一組設定打開會直接顯示）")

    out = config.OUTPUT_DIR
    write_csv(r.returns, out / "strategy_returns.csv")
    write_csv(r.perf, out / "performance.csv")
    write_csv(r.holdings, out / "holdings.csv")
    write_csv(r.latest, out / "latest_picks.csv")
    for n in r.notes:
        print("•", n)
    print(f"\n回測期間：{r.test_start.date()} ～ {r.latest_date.date()}（{len(r.rebalance_dates)} 次調倉）")
    print(format_table(r.perf).to_string(index=False))
    print(f"\n結果已存到 {out}")


if __name__ == "__main__":
    main()
