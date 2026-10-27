"""逐日下載上市（TWSE MI_INDEX）與上櫃（TPEx dailyQuotes）全部股票的收盤價、成交量、成交金額與漲跌，
存到 data/raw/daily_quotes/YYYYMMDD.csv（已存在就跳過，可中斷續跑）。
用途：重建「各調倉日當時可得」的股票池（含後來下市的股票），以及用交易所參考價計算含權息日報酬。
執行：python scripts/backfill_daily_quotes.py 2017-07-01 2026-10-20
"""
import sys, time, random, re, os
from pathlib import Path
import pandas as pd, requests

OUT = Path(__file__).resolve().parents[1] / "data" / "raw" / "daily_quotes"
TWSE = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
TPEX = "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes"
H = {"User-Agent": "Mozilla/5.0 (research backfill)"}

def num(s):
    s = pd.Series(s).astype(str).str.replace(",", "").str.strip()
    return pd.to_numeric(s.replace({"--": None, "---": None, "": None, "X": None}), errors="coerce")

def get(url, params, tries=5):
    for i in range(tries):
        try:
            r = requests.get(url, params=params, headers=H, timeout=30)
            if r.status_code == 200 and r.text.strip().startswith("{"):
                return r.json()
            time.sleep(30 * (i + 1))
        except Exception:
            time.sleep(30 * (i + 1))
    raise RuntimeError(f"failed {url} {params}")

def twse(d):
    j = get(TWSE, {"date": d.strftime("%Y%m%d"), "type": "ALLBUT0999", "response": "json"})
    for t in j.get("tables") or []:
        f = t.get("fields") or []
        if "證券代號" in f and "收盤價" in f and t.get("data"):
            df = pd.DataFrame(t["data"], columns=f)
            sign = df["漲跌(+/-)"].astype(str).map(lambda s: -1 if "-" in re.sub("<[^>]+>", "", s) and "+" not in s else (1 if "+" in s else (0 if s.strip() in ("", " ") else None)))
            raw = df["漲跌(+/-)"].astype(str).map(lambda s: re.sub("<[^>]+>", "", s).strip())
            return pd.DataFrame({"market": "TWSE", "code": df["證券代號"].str.strip(), "name": df["證券名稱"].str.strip(),
                                 "volume": num(df["成交股數"]), "value": num(df["成交金額"]), "close": num(df["收盤價"]),
                                 "sign": raw.values, "change": num(df["漲跌價差"]), "next_ref": None})
    return pd.DataFrame()

def tpex(d):
    j = get(TPEX, {"date": d.strftime("%Y/%m/%d"), "response": "json"})
    for t in j.get("tables") or []:
        f = t.get("fields") or []
        if "代號" in f and t.get("data"):
            df = pd.DataFrame(t["data"], columns=f)
            vcol = next(c for c in f if "成交金額" in c); ref = next((c for c in f if "參考價" in c), None)
            ch = df["漲跌"].astype(str).str.strip()
            return pd.DataFrame({"market": "TPEx", "code": df["代號"].str.strip(), "name": df["名稱"].str.strip(),
                                 "volume": num(df["成交股數"]), "value": num(df[vcol]), "close": num(df["收盤"]),
                                 "sign": ch.values, "change": num(ch.str.replace("+", "", regex=False)),
                                 "next_ref": num(df[ref]) if ref else None})
    return pd.DataFrame()

def main(a, b, market):
    """market = twse / tpex：兩個市場分開跑（不同主機，可同時進行）；檔名 YYYYMMDD_twse.csv / _tpex.csv。
    舊版合併檔 YYYYMMDD.csv 存在時跳過。證交所限流嚴格，每次請求間隔約 5 秒。"""
    OUT.mkdir(parents=True, exist_ok=True)
    fn, pause = (twse, float(os.getenv("TWSE_PAUSE", "6"))) if market == "twse" else (tpex, 2.0)
    for d in pd.bdate_range(a, b):
        if (OUT / f"{d:%Y%m%d}.csv").exists():
            continue
        fp = OUT / f"{d:%Y%m%d}_{market}.csv"
        if fp.exists():
            continue
        try:
            x = fn(d)
        except Exception as e:            # 抓不到就先跳過（不寫檔），之後重跑會補
            print(d.date(), market, "失敗", e, flush=True)
            time.sleep(60)
            continue
        time.sleep(pause + random.random())
        if x.empty:                       # 非交易日：留空檔做記號
            fp.write_text("")
            continue
        x = x[x["code"].str.fullmatch(r"\d{4}")]
        x.to_csv(fp, index=False)
        print(d.date(), market, len(x), flush=True)

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "twse")
