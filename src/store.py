"""本機資料層：把「網路爬蟲」和「本機檔案」整合成同一份資料。

原則
1. 增量更新：已經存在的日期不重抓，只補抓缺少的區間（多抓 7 天重疊，順便修正除權息調整）。
2. 同一天同一檔有多個來源時，網路爬蟲 > 本機 CSV（爬蟲的價格有還原權息）。
3. 真實資料與示範資料分開，不會混在一起。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from . import config
from .loaders import local as local_loader
from .loaders.tej import load_tej
from .utils import read_csv_any, write_csv

log = logging.getLogger(__name__)

PRICE_COLS = ["date", "ticker", "open", "high", "low", "close", "volume", "source"]
FAILED_FILE = config.PROCESSED_DIR / "failed_tickers.csv"   # Yahoo 抓不到的代號（7 天內不再重抓）
FAILED_SKIP_DAYS = 7
SOURCE_PRIORITY = {"yahoo": 2, "local": 1, "demo": 0}


# ------------------------------------------------------------------ 讀寫
def _read(path: Path, date_cols=("date",)) -> Optional[pd.DataFrame]:
    if not Path(path).exists():
        return None
    df = read_csv_any(path)
    for c in date_cols:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce")
    return df


def merge_prices(*frames: Optional[pd.DataFrame]) -> pd.DataFrame:
    """合併多個價格表；同一 (date, ticker) 依來源優先序、再以後傳入者為準。"""
    parts = [f for f in frames if f is not None and not f.empty]
    if not parts:
        return pd.DataFrame(columns=PRICE_COLS)
    df = pd.concat(parts, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"])
    df = df[df["date"].dt.dayofweek < 5]          # 排除週末（非交易日）的假資料
    if "source" not in df.columns:
        df["source"] = "local"
    df["source"] = df["source"].fillna("local")
    df["_prio"] = df["source"].map(SOURCE_PRIORITY).fillna(0)
    df["_order"] = range(len(df))
    df = (df.sort_values(["ticker", "date", "_prio", "_order"])
            .drop_duplicates(["ticker", "date"], keep="last")
            .drop(columns=["_prio", "_order"]))
    for c in PRICE_COLS:
        if c not in df.columns:
            df[c] = pd.NA
    return df[PRICE_COLS].reset_index(drop=True)


def plan_fetch(existing: Optional[pd.DataFrame], tickers: List[str], start, end,
               overlap_days: int = 7) -> Dict[pd.Timestamp, List[str]]:
    """決定每檔要從哪天開始抓 → {開始日: [代號...]}；已經是最新的就不抓。"""
    start, end = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    plan: Dict[pd.Timestamp, List[str]] = {}
    span = {}
    if existing is not None and not existing.empty:
        span = existing.groupby("ticker")["date"].agg(["min", "max"]).to_dict("index")
    for t in tickers:
        s = span.get(t)
        if s is None or s["min"] > start + pd.Timedelta(days=overlap_days):
            fetch_from = start                     # 沒有資料，或歷史不夠長 → 從頭抓
        elif s["max"] >= end - pd.Timedelta(days=1):
            continue                               # 已是最新
        else:
            fetch_from = s["max"] - pd.Timedelta(days=overlap_days)
        # 同一週開始的合併成一批，減少請求次數
        key = (fetch_from - pd.Timedelta(days=fetch_from.weekday())).normalize()
        plan.setdefault(key, []).append(t)
    return plan


def _recent_failures() -> set:
    f = _read(FAILED_FILE, date_cols=("failed_at",))
    if f is None or f.empty:
        return set()
    cutoff = pd.Timestamp.today() - pd.Timedelta(days=FAILED_SKIP_DAYS)
    return set(f.loc[f["failed_at"] >= cutoff, "ticker"])


def _remember_failures(failed: List[str], succeeded: set) -> None:
    old = _read(FAILED_FILE, date_cols=("failed_at",))
    now = pd.DataFrame({"ticker": failed, "failed_at": pd.Timestamp.today().normalize()})
    parts = [x for x in [old, now] if x is not None and not x.empty]
    df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=["ticker", "failed_at"])
    df = df[~df["ticker"].isin(succeeded)].drop_duplicates("ticker", keep="last")
    write_csv(df, FAILED_FILE)


def _update_price_file(path: Path, tickers: List[str], start, end, progress=None) -> Dict:
    from .crawlers import yahoo
    existing = _read(path)
    have = set(existing["ticker"]) if existing is not None else set()
    skip = _recent_failures() - have
    tickers = [t for t in tickers if t not in skip]
    plan = plan_fetch(existing, tickers, start, end)
    new_frames, failed = [], []
    for fetch_from, batch in plan.items():
        df, bad = yahoo.fetch_prices(batch, fetch_from, end, progress=progress)
        df["source"] = "yahoo"
        new_frames.append(df)
        failed += bad
    merged = merge_prices(existing, *new_frames)
    if new_frames:
        write_csv(merged, path)
    n_new = sum(len(f) for f in new_frames)
    if plan:
        got = set().union(*[set(f["ticker"]) for f in new_frames]) if new_frames else set()
        _remember_failures(failed, got)
    return {"requested": len(tickers), "fetched_tickers": sum(len(b) for b in plan.values()),
            "rows_downloaded": n_new, "failed": failed, "skipped_recent_failures": len(skip),
            "total_rows": len(merged)}


def update_prices(tickers: List[str], start, end, progress=None) -> Dict:
    return _update_price_file(config.PRICES_FILE, tickers, start, end, progress)


def update_benchmarks(start, end, tickers: List[str] = config.BENCHMARKS) -> Dict:
    return _update_price_file(config.BENCH_FILE, tickers, start, end)


def update_listing() -> pd.DataFrame:
    from .crawlers import twse
    listing = twse.fetch_listing()
    if len(listing) >= 100:            # 抓到的量太少代表網頁改版或被擋，不要覆蓋舊檔
        write_csv(listing, config.LISTING_FILE)
    return listing


def month_end_trading_days(prices: pd.DataFrame, start=None) -> List[pd.Timestamp]:
    """用價格資料裡實際出現的日期，找出每個月最後一個交易日（估值只在這些日子抓）。"""
    d = pd.Series(pd.to_datetime(prices["date"].unique())).sort_values()
    d = d[d.dt.dayofweek < 5]
    if start is not None:
        d = d[d >= pd.Timestamp(start)]
    if d.empty:
        return []
    last = d.groupby(d.dt.to_period("M")).max()
    return [pd.Timestamp(x) for x in last.tolist()]


def update_valuation(start=None, progress=None) -> Dict:
    from .crawlers import twse
    prices = _read(config.PRICES_FILE)
    if prices is None or prices.empty:
        return {"error": "請先更新股價（估值日期依股價的交易日決定）"}
    existing = _read(config.VALUATION_FILE)
    wanted = [pd.Timestamp(x) for x in month_end_trading_days(prices, start)]
    have = set(existing["date"]) if existing is not None else set()
    todo = [d for d in wanted if d not in have]
    new = twse.fetch_valuation_series(todo, progress=progress) if todo else None
    if new is not None and not new.empty:
        merged = pd.concat([x for x in [existing, new] if x is not None], ignore_index=True)
        merged = merged.drop_duplicates(["date", "ticker"], keep="last").sort_values(["date", "ticker"])
        write_csv(merged, config.VALUATION_FILE)
    return {"dates_requested": len(todo), "rows_downloaded": 0 if new is None else len(new)}


def append_update_log(record: Dict) -> None:
    row = pd.DataFrame([{"time": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
                         **{k: str(v) for k, v in record.items()}}])
    old = _read(config.UPDATE_LOG_FILE, date_cols=())
    write_csv(pd.concat([x for x in [old, row] if x is not None], ignore_index=True), config.UPDATE_LOG_FILE)


def pick_universe(kind: str, listing: pd.DataFrame, max_n: int | None) -> list[str]:
    """core = 市值前 50 大；tej = 所有有 TEJ 評等的普通股；all = 全部上市櫃普通股。"""
    if kind == "core" or (listing.empty and kind == "all"):
        tickers = list(config.CORE_UNIVERSE)
    elif kind == "all":
        tickers = listing["ticker"].tolist()
    elif kind == "tej":
        otc = set(listing.loc[listing["market"] == "上櫃", "code"].astype(str)) if not listing.empty else None
        tej = load_tej(config.TEJ_DIR, otc)
        tickers = tej["ticker"].unique().tolist()
        if not listing.empty:   # 只留普通股（排除已下市、ETF 等）
            tickers = [t for t in tickers if t in set(listing["ticker"])]
        tickers = list(dict.fromkeys(config.CORE_UNIVERSE + tickers))
    else:
        raise ValueError(f"不認得的 universe：{kind}")
    return tickers[:max_n] if max_n else tickers


# ------------------------------------------------------------------ 組合成可分析的資料集
@dataclass
class Dataset:
    mode: str
    prices: pd.DataFrame                    # date,ticker,open,high,low,close,volume,source
    benchmarks: pd.DataFrame                # 同上
    esg: pd.DataFrame                       # ticker,available_date,esg_total,e_score,...
    financials: pd.DataFrame                # ticker,available_date,pe,pb,dividend_yield,roe,...
    listing: pd.DataFrame                   # ticker,code,name,market,industry
    notes: List[str] = field(default_factory=list)

    @property
    def names(self) -> Dict[str, str]:
        d = {}
        if not self.esg.empty and "name" in self.esg.columns:
            d.update(self.esg.dropna(subset=["name"]).drop_duplicates("ticker", keep="last")
                     .set_index("ticker")["name"].astype(str).to_dict())
        if not self.listing.empty:
            d.update(self.listing.set_index("ticker")["name"].astype(str).to_dict())
        d.update(config.BENCHMARK_NAMES)
        return d

    @property
    def industries(self) -> Dict[str, str]:
        d = {}
        if not self.esg.empty and "industry" in self.esg.columns:
            d.update(self.esg.dropna(subset=["industry"]).drop_duplicates("ticker", keep="last")
                     .set_index("ticker")["industry"].astype(str).to_dict())
        if not self.listing.empty:
            d.update({k: v for k, v in self.listing.set_index("ticker")["industry"].astype(str).to_dict().items()
                      if v and v != "nan"})
        return d


def _empty(cols) -> pd.DataFrame:
    return pd.DataFrame(columns=cols)


def demo_sets() -> List[str]:
    return sorted(p.name for p in config.DEMO_DIR.iterdir() if p.is_dir()) if config.DEMO_DIR.exists() else []


def load_dataset(mode: str = "real", demo_set: Optional[str] = None) -> Dataset:
    notes: List[str] = []
    listing = _read(config.LISTING_FILE, date_cols=())
    listing = listing if listing is not None else _empty(["ticker", "code", "name", "market", "industry"])

    if mode == "demo":
        folder = config.DEMO_DIR / (demo_set or (demo_sets() or ["sample_1y"])[0])
        d = local_loader.load_folder(folder)
        for k in ("prices", "benchmarks"):
            if d[k] is not None:
                d[k]["source"] = "demo"
        notes.append(f"目前使用「合成示範資料」（{folder.name}），數字不代表真實市場。")
        return Dataset("demo", merge_prices(d["prices"]), merge_prices(d["benchmarks"]),
                       d["esg"] if d["esg"] is not None else _empty(["ticker", "available_date"]),
                       d["financials"] if d["financials"] is not None else _empty(["ticker", "available_date"]),
                       listing, notes)

    # ---- 真實資料：爬蟲 + 本機檔 + TEJ ----
    local = local_loader.load_folder(config.LOCAL_DIR)
    for k in ("prices", "benchmarks"):
        if local[k] is not None:
            local[k]["source"] = "local"
    prices = merge_prices(local["prices"], _read(config.PRICES_FILE))
    bench = merge_prices(local["benchmarks"], _read(config.BENCH_FILE))

    otc = set(listing.loc[listing["market"] == "上櫃", "code"].astype(str)) if not listing.empty else None
    tej = load_tej(config.TEJ_DIR, otc)
    esg_parts = [x for x in [local["esg"], tej] if x is not None and not x.empty]
    esg = (pd.concat(esg_parts, ignore_index=True)
             .drop_duplicates(["ticker", "available_date"], keep="last")) if esg_parts else _empty(["ticker", "available_date"])
    if not tej.empty:
        n_periods = tej["available_date"].nunique()
        notes.append(f"TEJ ESG：{tej['ticker'].nunique()} 檔、{n_periods} 期評等"
                     f"（最早公告日 {tej['available_date'].min().date()}）。")

    val = _read(config.VALUATION_FILE)
    fin_parts = []
    if val is not None and not val.empty:
        fin_parts.append(val.rename(columns={"date": "available_date"}))
    if local["financials"] is not None:
        fin_parts.append(local["financials"])
    fin = pd.concat(fin_parts, ignore_index=True) if fin_parts else _empty(["ticker", "available_date"])
    if len(fin_parts) == 2:   # 兩個來源同欄位時各自保留，as-of 合併時每欄各取最新值
        fin = fin.groupby(["ticker", "available_date"], as_index=False).last()

    if prices.empty:
        notes.append("尚未有真實股價資料：請執行 `python scripts/update_data.py` 或按首頁的「更新資料」。")
    return Dataset("real", prices, bench, esg, fin, listing, notes)
