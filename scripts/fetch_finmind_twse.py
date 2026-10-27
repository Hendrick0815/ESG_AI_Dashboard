"""上市個股逐日行情（FinMind TaiwanStockPrice，含已下市股票）：data/raw/finmind_twse/{代號}.csv。
用途：證交所逐日全市場行情下載受限流時，替逐期股票池中的上市股票補齊逐日收盤價、漲跌價差與成交金額。
執行：python scripts/fetch_finmind_twse.py 2330 2317 ...   或   python scripts/fetch_finmind_twse.py --file codes.txt
"""
import sys, time
from pathlib import Path
import pandas as pd, requests

OUT = Path(__file__).resolve().parents[1] / "data" / "raw" / "finmind_twse"
URL = "https://api.finmindtrade.com/api/v4/data"

def fetch(code, start="2017-07-01", end="2026-10-20"):
    for i in range(5):
        try:
            r = requests.get(URL, params={"dataset": "TaiwanStockPrice", "data_id": code, "start_date": start, "end_date": end}, timeout=60)
            j = r.json()
            if j.get("status") == 200:
                return pd.DataFrame(j.get("data") or [])
            print(code, j.get("msg"), flush=True)
            time.sleep(300 if "limit" in str(j.get("msg", "")).lower() or r.status_code == 402 else 30)
        except Exception as e:
            print(code, "err", e, flush=True); time.sleep(30)
    return None

def main(codes):
    OUT.mkdir(parents=True, exist_ok=True)
    for c in codes:
        fp = OUT / f"{c}.csv"
        if fp.exists():
            continue
        df = fetch(c)
        if df is None:
            continue
        df.to_csv(fp, index=False)
        print(c, len(df), flush=True)
        time.sleep(12)

if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "--file":
        a = Path(a[1]).read_text().split()
    main(a)
