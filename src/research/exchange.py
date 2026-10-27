"""以證交所／櫃買中心逐日行情（data/raw/daily_quotes）建立研究用的價格面板與「逐期股票池」。

為什麼要另外建：平台平常只下載「目前」成交金額前 300 檔的 Yahoo 股價，過去已下市或曾經熱門、
現在不在前 300 的股票都不在裡面（存活者偏誤）。交易所每日行情包含當天所有掛牌股票，
因此可以在每個調倉日用「當天以前 20 個交易日」的成交金額重新排名，並保留後來下市的股票。

日報酬（含權息）：用交易所的漲跌價差回推「當日參考價」，報酬 = 收盤價 ÷ 參考價 − 1。
除權息當天的參考價已扣掉股利，因此等同股利再投入的總報酬。
- 上市：參考價 = 收盤價 − 漲跌價差（漲跌符號 +/−；空白 = 平盤；X = 不比價，當日報酬記為 0）
- 上櫃：當日參考價 = 前一交易日公布的「次日參考價」
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
QUOTES_DIR = ROOT / "data" / "raw" / "daily_quotes"


def is_common_stock(code: pd.Series) -> pd.Series:
    """普通股判斷（代號規則，適用已下市股票）：4 碼、不以 0 開頭（ETF/受益憑證）、不是 91xx（存託憑證）。"""
    c = code.astype(str)
    return c.str.fullmatch(r"[1-9]\d{3}") & ~c.str.startswith("91")


def _num(s: pd.Series) -> pd.Series:
    s = s.astype(str).str.replace(",", "").str.strip()
    return pd.to_numeric(s.replace({"--": None, "---": None, "": None, "X": None, "nan": None}), errors="coerce")


def load_quotes(start=None, end=None, qdir: Path = QUOTES_DIR) -> pd.DataFrame:
    frames = []
    for fp in sorted(qdir.glob("*.csv")):
        d = pd.Timestamp(fp.stem.split("_")[0])
        if (start is not None and d < pd.Timestamp(start)) or (end is not None and d > pd.Timestamp(end)):
            continue
        if fp.stat().st_size == 0:
            continue
        df = pd.read_csv(fp, dtype={"code": str, "sign": str})
        df["date"] = d
        frames.append(df)
    # GitHub Actions 回補的上市年度檔（data/raw/daily_quotes_twse/twse_YYYY.csv.gz）
    tdir = qdir.parent / "daily_quotes_twse"
    have = {(d, m) for f in frames for d, m in zip(f["date"].iloc[:1], f["market"].iloc[:1])}
    for fp in sorted(tdir.glob("twse_*.csv.gz")) if tdir.exists() else []:
        t = pd.read_csv(fp, dtype=str)
        t["date"] = pd.to_datetime(t["date"], format="%Y%m%d")
        if start is not None:
            t = t[t["date"] >= pd.Timestamp(start)]
        if end is not None:
            t = t[t["date"] <= pd.Timestamp(end)]
        sign = t["漲跌(+/-)"].fillna("").str.replace(r"<[^>]+>", "", regex=True).str.strip()
        df = pd.DataFrame({"market": "TWSE", "code": t["證券代號"].str.strip(), "name": t["證券名稱"].str.strip(),
                           "volume": _num(t["成交股數"]), "value": _num(t["成交金額"]), "close": _num(t["收盤價"]),
                           "sign": sign, "change": _num(t["漲跌價差"]), "next_ref": np.nan, "date": t["date"]})
        frames.append(df)
    q = pd.concat(frames, ignore_index=True)
    q = q.drop_duplicates(["date", "market", "code"], keep="first")
    q = q[is_common_stock(q["code"])].copy()
    q["ticker"] = q["code"] + np.where(q["market"] == "TWSE", ".TW", ".TWO")
    return q.sort_values(["ticker", "date"]).reset_index(drop=True)


FINMIND_DIR = ROOT / "data" / "raw" / "finmind_twse"


def load_finmind_twse(end=None, fdir: Path = FINMIND_DIR) -> pd.DataFrame:
    """上市個股逐日行情（FinMind，資料來自證交所，含已下市股票）。
    日報酬 = 漲跌價差 ÷（收盤價 − 漲跌價差）；除權息日 FinMind 的價差為 0（不比價），當日報酬記為 0。"""
    frames = []
    for fp in sorted(fdir.glob("*.csv")) if fdir.exists() else []:
        if fp.stat().st_size < 10:
            continue
        d = pd.read_csv(fp, dtype={"stock_id": str})
        if d.empty:
            continue
        frames.append(d)
    if not frames:
        return pd.DataFrame()
    f = pd.concat(frames, ignore_index=True)
    f["date"] = pd.to_datetime(f["date"])
    if end is not None:
        f = f[f["date"] <= pd.Timestamp(end)]
    f = f[(f["close"] > 0) & is_common_stock(f["stock_id"])]
    prev = f["close"] - f["spread"]
    ret = (f["spread"] / prev).where(prev > 0, 0.0)
    out = pd.DataFrame({"date": f["date"], "ticker": f["stock_id"] + ".TW", "market": "TWSE", "raw_close": f["close"],
                        "volume": f["Trading_Volume"], "value": f["Trading_money"], "ret": ret.clip(-0.5, 1.0)})
    return out.sort_values(["ticker", "date"]).reset_index(drop=True)


YAHOO_ALL_DIR = ROOT / "data" / "raw" / "yahoo_all"


def load_yahoo_all(end=None, ydir: Path = YAHOO_ALL_DIR) -> pd.DataFrame:
    """上市普通股的 Yahoo 日資料（scripts/fetch_yahoo_all.py 下載）：日報酬用還原收盤價，
    成交金額以「未還原收盤價 × 成交股數」近似（只用於股票池排名）。"""
    frames = []
    for fp in sorted(ydir.glob("*.csv")) if ydir.exists() else []:
        d = pd.read_csv(fp, parse_dates=["Date"])
        if d.empty:
            continue
        d["ticker"] = fp.stem
        frames.append(d)
    if not frames:
        return pd.DataFrame()
    y = pd.concat(frames, ignore_index=True).rename(columns={"Date": "date"})
    y["date"] = pd.to_datetime(y["date"]).dt.tz_localize(None).dt.normalize()
    if end is not None:
        y = y[y["date"] <= pd.Timestamp(end)]
    y = y[(y["Close"] > 0) & (y["Volume"].fillna(0) >= 0)].sort_values(["ticker", "date"])
    y = y[is_common_stock(y["ticker"].str[:4])]
    ret = y.groupby("ticker")["Adj Close"].pct_change()
    out = pd.DataFrame({"date": y["date"], "ticker": y["ticker"], "market": "TWSE", "raw_close": y["Close"],
                        "volume": y["Volume"].fillna(0), "value": y["Close"] * y["Volume"].fillna(0),
                        "ret": ret.clip(-0.5, 1.0)})
    return out.reset_index(drop=True)


def daily_returns(q: pd.DataFrame) -> pd.Series:
    """依上方規則計算含權息日報酬。"""
    q = q.sort_values(["ticker", "date"])
    prev_close = q.groupby("ticker")["close"].transform(lambda s: s.ffill().shift())
    sign = q["sign"].fillna("").astype(str).str.strip()
    ch = q["change"].abs()
    sgn = np.select([sign.str.startswith("+"), sign.str.startswith("-"), sign.isin(["", " ", "0.00", "0"])],
                    [1.0, -1.0, 0.0], default=np.nan)
    ref_twse = q["close"] - sgn * ch
    prev_next_ref = q.groupby("ticker")["next_ref"].shift()
    ref = np.where(q["market"] == "TWSE", ref_twse, prev_next_ref)
    ref = pd.Series(ref, index=q.index).where(lambda s: s > 0)
    xmark = sign.str.upper().eq("X")
    ref = ref.where(~xmark).fillna(prev_close)          # 缺參考價 → 用前一日收盤
    r = q["close"] / ref - 1
    r[xmark] = 0.0                                     # X（不比價，多為除權息或恢復交易）→ 當日報酬記 0，避免把配息誤算成虧損
    r[q["close"].isna()] = 0.0                         # 當天無成交 → 視為 0
    return r.clip(-0.5, 1.0)                           # 防止資料錯誤造成極端值（漲跌幅限制為 ±10%）


def index_from_returns(df: pd.DataFrame) -> pd.DataFrame:
    """由日報酬建立還原價格指數（起點 = 第一個收盤價）。"""
    df = df.sort_values(["ticker", "date"]).copy()
    first = df.groupby("ticker")["raw_close"].transform("first")
    df["close"] = first * (1 + df["ret"].fillna(0)).groupby(df["ticker"]).cumprod()
    return df


def apply_yahoo_returns(px: pd.DataFrame, yahoo: pd.DataFrame) -> pd.DataFrame:
    """有 Yahoo 還原收盤價的股票（平台現存的 300 檔），日報酬改用 Yahoo（除權息處理較精確）；
    成交金額與其他股票（含已下市）不變。回傳重新計算還原指數後的價格表。"""
    y = yahoo[["date", "ticker", "close"]].sort_values(["ticker", "date"]).copy()
    y["ry"] = y.groupby("ticker")["close"].pct_change()
    out = px.merge(y[["date", "ticker", "ry"]], on=["date", "ticker"], how="left")
    use = out["ry"].notna()
    out["ret_ex"] = out["ret"]                      # 保留交易所算法的報酬（驗證用）
    out.loc[use, "ret"] = out.loc[use, "ry"]
    out["ret_source"] = np.where(use, "Yahoo", "交易所")
    return index_from_returns(out.drop(columns=["ry", "close"]))


def build_prices_hybrid(q: pd.DataFrame, fm: pd.DataFrame, ya: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """上櫃：交易所逐日行情（參考價法）；上市：Yahoo（現存股票）＋ FinMind（Yahoo 沒有的已下市股票）。"""
    tp = build_prices(q[q["market"] == "TPEx"])
    cols = ["date", "ticker", "raw_close", "volume", "value", "market", "ret", "close"]
    parts = [tp]
    have = set()
    if ya is not None and len(ya):
        parts.append(index_from_returns(ya)[cols]); have |= set(ya["ticker"])
    if len(fm):
        f = fm[~fm["ticker"].isin(have)]
        if len(f):
            parts.append(index_from_returns(f)[cols]); have |= set(f["ticker"])
    tw_q = q[(q["market"] == "TWSE") & ~q["ticker"].isin(have)]
    if len(tw_q) and ya is None:
        parts.append(build_prices(tw_q))
    out = pd.concat(parts, ignore_index=True)
    names = q.drop_duplicates("ticker", keep="last").set_index("ticker")["name"]
    out["name"] = out["ticker"].map(names)
    return out


def build_prices(q: pd.DataFrame) -> pd.DataFrame:
    """回傳與平台相同格式的價格表：date,ticker,close(還原指數),volume,value,raw_close,market,name。"""
    q = q.copy()
    q["ret"] = daily_returns(q)
    q["first"] = q.groupby("ticker")["close"].transform(lambda s: s.dropna().iloc[0] if s.notna().any() else np.nan)
    q["idx"] = (1 + q["ret"].fillna(0)).groupby(q["ticker"]).cumprod()
    q["close_adj"] = q["first"] * q["idx"]
    out = q.rename(columns={"close": "raw_close"})[["date", "ticker", "raw_close", "volume", "value", "market", "name", "ret"]]
    out["close"] = q["close_adj"].values
    out["volume"] = out["volume"].fillna(0)
    return out


def eligibility(prices: pd.DataFrame, size: int = 300, window: int = 20, min_days: int = 15) -> pd.DataFrame:
    """每個交易日 t：以 t 當天（含）往前 window 個交易日的平均成交金額排名，取前 size 檔。
    交易天數不足 min_days（新上市）不納入。回傳 date,ticker,avg_value,n_days,rank（只含入選者）。"""
    days = pd.DatetimeIndex(sorted(prices["date"].unique()))
    v = prices.pivot_table(index="date", columns="ticker", values="value", aggfunc="sum").reindex(days)
    listed = v.notna()
    avg = v.fillna(0).rolling(window, min_periods=1).sum() / window
    n = listed.rolling(window, min_periods=1).sum()
    avg = avg.where(n >= min_days)
    rk = avg.rank(axis=1, ascending=False, method="first")
    long = pd.DataFrame({"avg_value": avg.stack(), "n_days": n.stack(), "rank": rk.stack()}).dropna().reset_index()
    long.columns = ["date", "ticker", "avg_value", "n_days", "rank"]
    out = long[long["rank"] <= size].copy()
    out["rank"] = out["rank"].astype(int)
    return out


def eligibility_sampled(values: pd.DataFrame, trading_days, size: int = 300, k: int = 4, min_k: int = 3) -> pd.DataFrame:
    """上市逐日資料不齊時使用：只在「兩個市場都有全市場行情」的抽樣日（約每 5 個交易日）計算成交金額，
    每個交易日 t 以 t 當天（含）以前最近 k 個抽樣日的平均排名（約等於近 20 個交易日），出現少於 min_k 次者不納入；
    排名在下一個抽樣日之前維持不變（只用過去資訊）。"""
    v = values.pivot_table(index="date", columns="ticker", values="value", aggfunc="sum")
    mk = values.groupby("date")["market"].nunique()
    samp = mk[mk == 2].index.sort_values()
    v = v.reindex(samp)
    listed = v.notna()
    avg = v.fillna(0).rolling(k, min_periods=1).sum() / k
    n = listed.rolling(k, min_periods=1).sum()
    avg = avg.where(n >= min_k)
    rk = avg.rank(axis=1, ascending=False, method="first")
    long = pd.DataFrame({"avg_value": avg.stack(), "n_days": n.stack(), "rank": rk.stack()}).dropna().reset_index()
    long.columns = ["sample_date", "ticker", "avg_value", "n_days", "rank"]
    long = long[long["rank"] <= size]
    td = pd.DatetimeIndex(sorted(trading_days))
    td = td[td >= samp[0]]
    pos = np.searchsorted(samp.values, td.values, side="right") - 1
    m = pd.DataFrame({"date": td, "sample_date": samp[pos]})
    out = m.merge(long, on="sample_date", how="inner")
    out["rank"] = out["rank"].astype(int)
    return out[["date", "ticker", "avg_value", "n_days", "rank", "sample_date"]]


def universe_summary(prices: pd.DataFrame, elig: pd.DataFrame, dates) -> pd.DataFrame:
    """每個調倉日：掛牌普通股數、交易天數不足數、入選數、入選者之後下市的檔數。"""
    last_day = prices.groupby("ticker")["date"].max()
    end = prices["date"].max()
    rows = []
    for d in dates:
        live = prices[prices["date"] == d]["ticker"]
        e = elig[elig["date"] == d]
        rows.append({"date": d, "listed_common": len(live), "selected": len(e),
                     "min_avg_value": float(e["avg_value"].min()) if len(e) else np.nan,
                     "later_delisted": int((last_day.reindex(e["ticker"]) < end - pd.Timedelta(days=10)).sum())})
    return pd.DataFrame(rows)
