"""更新本機資料（不用開網頁也能執行）。

用法（在專案根目錄）：
    python scripts/update_data.py                   # 市值前 50 大 + 比較基準，回看 3 年
    python scripts/update_data.py --universe tej    # 所有有 TEJ ESG 評等的上市櫃股票
    python scripts/update_data.py --universe all --max 300
    python scripts/update_data.py --skip-valuation  # 不抓本益比等估值（比較快）
第二次以後執行只會補抓缺少的日期。
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    sys.stdout.reconfigure(encoding="utf-8")   # Windows PowerShell 印中文不閃退
except Exception:
    pass

from src import config, store  # noqa: E402


def main() -> None:
    today = pd.Timestamp.today().normalize()
    ap = argparse.ArgumentParser(description="更新股價、比較基準、股票清單與估值資料")
    ap.add_argument("--start", default=(today - pd.DateOffset(years=3)).strftime("%Y-%m-%d"))
    ap.add_argument("--end", default=today.strftime("%Y-%m-%d"))
    ap.add_argument("--universe", choices=["core", "tej", "all"], default="core")
    ap.add_argument("--max", type=int, default=None, help="最多抓幾檔")
    ap.add_argument("--skip-listing", action="store_true")
    ap.add_argument("--skip-valuation", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    record = {"start": args.start, "end": args.end, "universe": args.universe}

    listing = pd.DataFrame(columns=["ticker", "code", "name", "market", "industry"])
    if not args.skip_listing:
        print("① 更新上市櫃股票清單 ...")
        try:
            listing = store.update_listing()
            print(f"   共 {len(listing)} 檔普通股")
        except Exception as e:
            print(f"   失敗（沿用舊清單）：{e}")
    if listing.empty and config.LISTING_FILE.exists():
        listing = store._read(config.LISTING_FILE, date_cols=())

    tickers = store.pick_universe(args.universe, listing, args.max)
    print(f"② 更新 {len(tickers)} 檔股價（Yahoo Finance，增量）...")
    r = store.update_prices(tickers, args.start, args.end,
                            progress=lambda i, n, phase: print(f"   {phase} {i}/{n}      ", end="\r"))
    print(f"\n   下載 {r['rows_downloaded']} 筆；失敗 {len(r['failed'])} 檔 {r['failed'][:10]}"
          + (f"；略過 {r['skipped_recent_failures']} 檔（7 天內抓不到過）" if r["skipped_recent_failures"] else ""))
    record.update(prices_rows=r["rows_downloaded"], prices_failed=len(r["failed"]))

    print("③ 更新比較基準 ...")
    b = store.update_benchmarks(args.start, args.end)
    print(f"   下載 {b['rows_downloaded']} 筆；失敗 {b['failed']}")

    if not args.skip_valuation:
        print("④ 更新本益比 / 股價淨值比 / 殖利率（每月底一筆，約 3 秒一個月）...")
        v = store.update_valuation(args.start, progress=lambda i, n, d: print(f"   {i}/{n} {d.date()}", end="\r"))
        print(f"\n   {v}")
        record.update(valuation=v)

    store.append_update_log(record)
    print("完成。資料在 data/processed/")


if __name__ == "__main__":
    main()
