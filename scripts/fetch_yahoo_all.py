"""研究用：下載全部上市普通股（含 2017 年後曾掛牌者）的 Yahoo 日資料（未還原收盤價、還原收盤價、成交量），
存到 data/raw/yahoo_all/{ticker}.csv；Yahoo 沒有的（多為已下市）列在 missing.txt，另以 FinMind 補。
執行：python scripts/fetch_yahoo_all.py codes.txt
"""
import sys, time
from pathlib import Path
import pandas as pd, yfinance as yf

OUT = Path(__file__).resolve().parents[1] / "data" / "raw" / "yahoo_all"

def main(codes):
    OUT.mkdir(parents=True, exist_ok=True)
    tickers = [c if "." in c else c + ".TW" for c in codes]
    todo = [t for t in tickers if not (OUT / f"{t}.csv").exists()]
    missing = []
    for i in range(0, len(todo), 40):
        batch = todo[i:i + 40]
        d = None
        for k in range(4):
            try:
                d = yf.download(batch, start="2017-07-01", end="2026-10-21", auto_adjust=False, group_by="ticker",
                                progress=False, threads=False)
                break
            except Exception as e:
                print("retry", e, flush=True); time.sleep(60 * (k + 1))
        if d is None:
            continue
        for t in batch:
            try:
                x = d[t].dropna(how="all")
            except KeyError:
                x = pd.DataFrame()
            if x.empty or x["Close"].notna().sum() < 5:
                missing.append(t); continue
            x.reset_index().to_csv(OUT / f"{t}.csv", index=False)
        print(i + len(batch), "/", len(todo), "missing so far", len(missing), flush=True)
        time.sleep(8)
    (OUT / "missing.txt").write_text("\n".join(missing))

if __name__ == "__main__":
    main(Path(sys.argv[1]).read_text().split())
