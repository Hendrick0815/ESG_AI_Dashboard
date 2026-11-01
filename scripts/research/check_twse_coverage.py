"""上市股票（含已下市）涵蓋率檢查與代號清單。

證交所逐日全市場行情在雲端主機被限流，上市股票改以 Yahoo（現存股票）＋ FinMind（Yahoo 未收錄，多為已下市）逐檔下載。
本程式：
1. 建立研究使用的上市普通股代號清單 data/raw/twse_codes.csv（代號、來源）：
   - 目前上市清單（data/processed/listing.csv，證交所 ISIN）
   - 手上證交所全市場行情樣本日（data/raw/daily_quotes/*_twse.csv 與 YYYYMMDD.csv）出現過的上市普通股
   - FinMind 補抓的代號（data/raw/finmind_twse/）
2. 檢查每個樣本日的上市普通股，是否都有 Yahoo 或 FinMind 日資料；輸出 outputs/research/<run_id>/twse_coverage_check.csv
執行：python scripts/research/check_twse_coverage.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CFG = json.loads((ROOT / "research_config.json").read_text(encoding="utf-8"))
RUN = ROOT / "outputs" / "research" / CFG["run_id"]
RAW = ROOT / "data" / "raw"


def is_common(c: str) -> bool:
    return bool(re.fullmatch(r"[1-9]\d{3}", str(c))) and not str(c).startswith("91")


def main() -> None:
    have_y = {f.name.replace(".TW.csv", "") for f in (RAW / "yahoo_all").glob("*.TW.csv")}
    have_f = {f.stem for f in (RAW / "finmind_twse").glob("*.csv")}
    lst = pd.read_csv(ROOT / "data" / "processed" / "listing.csv", dtype=str)
    cur = {t.replace(".TW", "") for t in lst["ticker"] if t.endswith(".TW")}
    cur = {c for c in cur if is_common(c)}

    rows, seen = [], set()
    files = sorted((RAW / "daily_quotes").glob("*_twse.csv")) + sorted((RAW / "daily_quotes").glob("[0-9]*[0-9].csv"))
    for fp in files:
        try:
            d = pd.read_csv(fp, dtype={"code": str})
        except Exception:
            continue
        if "market" in d:
            d = d[d["market"] == "TWSE"]
        if d.empty:
            continue
        codes = {c for c in d["code"] if is_common(c)}
        seen |= codes
        miss = sorted(codes - have_y - have_f)
        rows.append({"date": fp.name[:8], "twse_common": len(codes), "have_yahoo": len(codes & have_y),
                     "have_finmind_only": len((codes & have_f) - have_y), "missing": len(miss), "missing_codes": " ".join(miss)})
    chk = pd.DataFrame(rows)
    RUN.mkdir(parents=True, exist_ok=True)
    chk.to_csv(RUN / "twse_coverage_check.csv", index=False, encoding="utf-8-sig")

    src = []
    for c in sorted(cur | seen | have_f):
        s = [n for n, ok in (("目前上市清單", c in cur), ("證交所行情樣本日", c in seen), ("FinMind 補抓", c in have_f)) if ok]
        src.append({"code": c, "source": "、".join(s), "data": "Yahoo" if c in have_y else ("FinMind" if c in have_f else "無")})
    codes = pd.DataFrame(src)
    codes.to_csv(RAW / "twse_codes.csv", index=False, encoding="utf-8-sig")
    (RAW / "twse_codes.txt").write_text("\n".join(codes["code"]) + "\n")     # 給 fetch_yahoo_all.py 重新下載用
    print(f"代號 {len(codes)} 檔（Yahoo {int((codes['data']=='Yahoo').sum())}、FinMind {int((codes['data']=='FinMind').sum())}、"
          f"無資料 {int((codes['data']=='無').sum())}）；樣本日 {len(chk)} 天，缺漏最多 {int(chk['missing'].max()) if len(chk) else 0} 檔")
    if len(chk) and chk["missing"].max() > 0:
        sys.exit("仍有缺漏：" + " ".join(sorted(set(" ".join(chk["missing_codes"]).split()))))


if __name__ == "__main__":
    main()
