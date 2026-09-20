"""Yahoo Finance 股價爬蟲：批次下載（取代原本一檔一檔抓、每檔等 2 秒的做法）。"""
from __future__ import annotations

import logging
import random
import time
from typing import Callable, List, Optional, Tuple

import pandas as pd

log = logging.getLogger(__name__)

PRICE_COLS = ["date", "ticker", "open", "high", "low", "close", "volume"]

try:
    import yfinance as yf
    YF_AVAILABLE = True
except Exception:  # pragma: no cover
    yf = None
    YF_AVAILABLE = False


def parse_yf_frame(raw: pd.DataFrame, tickers: List[str]) -> pd.DataFrame:
    """把 yf.download 的結果（單層或兩層欄位、任一層放 ticker）轉成長表。"""
    if raw is None or raw.empty:
        return pd.DataFrame(columns=PRICE_COLS)
    frames = []
    if isinstance(raw.columns, pd.MultiIndex):
        lvl = 0 if "Close" in raw.columns.get_level_values(1) else 1  # ticker 在哪一層
        for t in raw.columns.get_level_values(lvl).unique():
            sub = raw.xs(t, axis=1, level=lvl).copy()
            sub["ticker"] = t
            frames.append(sub)
    else:
        sub = raw.copy()
        sub["ticker"] = tickers[0]
        frames.append(sub)

    out = []
    for sub in frames:
        sub = sub.reset_index()
        sub.columns = [str(c).strip().lower() for c in sub.columns]
        sub = sub.rename(columns={"index": "date", "datetime": "date", "adj close": "adj_close"})
        if "close" not in sub.columns:
            continue
        sub["date"] = pd.to_datetime(sub["date"], errors="coerce")
        if getattr(sub["date"].dt, "tz", None) is not None:
            sub["date"] = sub["date"].dt.tz_localize(None)
        sub["date"] = sub["date"].dt.normalize()
        for c in ["open", "high", "low", "close", "volume"]:
            sub[c] = pd.to_numeric(sub[c], errors="coerce") if c in sub.columns else float("nan")
        sub = sub.dropna(subset=["date", "close"])
        sub = sub[sub["date"].dt.dayofweek < 5]   # Yahoo 週末偶爾會多一筆「今天」的報價，不是交易日
        out.append(sub[PRICE_COLS])
    if not out:
        return pd.DataFrame(columns=PRICE_COLS)
    return pd.concat(out, ignore_index=True).sort_values(["ticker", "date"]).reset_index(drop=True)


def fetch_prices(tickers: List[str], start, end, chunk: int = 50,
                 progress: Optional[Callable[[int, int, str], None]] = None) -> Tuple[pd.DataFrame, List[str]]:
    """批次下載還原權息後的日 K。回傳 (長表, 失敗代號)。
    progress(完成數, 總數, 階段說明)。沒抓到的代號只再「批次」重試一輪，不再一檔一檔重試
    （舊做法遇到上百檔抓不到時，會每檔等 2 秒、卡住十幾分鐘）。"""
    if not YF_AVAILABLE:
        raise ImportError("尚未安裝 yfinance：pip install yfinance")
    tickers = list(dict.fromkeys(t for t in tickers if t))
    if not tickers:
        return pd.DataFrame(columns=PRICE_COLS), []
    end_excl = (pd.Timestamp(end) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")  # yfinance 的 end 不含當天
    start = pd.Timestamp(start).strftime("%Y-%m-%d")

    def _download(batch):
        raw = yf.download(batch, start=start, end=end_excl, auto_adjust=True, group_by="ticker",
                          threads=True, progress=False)
        return parse_yf_frame(raw, batch)

    got = []
    for i in range(0, len(tickers), chunk):
        batch = tickers[i:i + chunk]
        try:
            got.append(_download(batch))
        except Exception as e:
            log.warning("批次下載失敗（%s...）：%s", batch[0], e)
        if progress:
            progress(min(i + chunk, len(tickers)), len(tickers), "下載股價")
        time.sleep(1 + random.random())

    df = pd.concat(got, ignore_index=True) if got else pd.DataFrame(columns=PRICE_COLS)
    missing = [t for t in tickers if t not in set(df["ticker"])]
    retry = []
    if missing:
        time.sleep(3)   # 可能是被 Yahoo 限流，先等一下
    for i in range(0, len(missing), 20):   # 沒抓到的，每 20 檔一批重試一輪
        batch = missing[i:i + 20]
        try:
            one = _download(batch)
            if not one.empty:
                retry.append(one)
        except Exception as e:
            log.warning("重試失敗（%s...）：%s", batch[0], e)
        if progress:
            progress(min(i + 20, len(missing)), len(missing), "重試沒抓到的股票")
        time.sleep(2 + random.random())
    if retry:
        df = pd.concat([df, *retry], ignore_index=True)
    failed = [t for t in tickers if t not in set(df["ticker"])]
    return df, failed
