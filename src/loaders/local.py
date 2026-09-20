"""讀取自己準備的 CSV（沿用 app_v5 的格式，長表或寬表都可以）。

資料夾內可放：
- stock_price.csv  ：date,ticker,close（長表）或 date,2330.TW,2317.TW,...（寬表）；可另有 open/high/low/volume
- etf_prices.csv   ：同上，放比較基準
- esg_scores.csv   ：date,ticker,esg_total,e_score,s_score,g_score,controversy_score,carbon_intensity
- financials.csv   ：date,ticker,roe,roa,pb,pe,debt_ratio,eps
ESG 與財報的 date 會被當成「公布日」（那天之後才能使用），請填公布日而不是所屬期間。
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from ..utils import normalize_ticker, read_csv_any, rename_by_alias

PRICE_ALIASES = {"date": ["日期", "年月日"], "ticker": ["代號", "stock_id", "code", "symbol"],
                 "close": ["收盤價", "adj close", "adj_close"], "open": ["開盤價"], "high": ["最高價"],
                 "low": ["最低價"], "volume": ["成交量"]}
ESG_ALIASES = {"date": ["yearmonth", "month", "日期", "公告日"], "ticker": ["stock_id", "code", "symbol", "代號"],
               "esg_total": ["esg", "esg總分"], "e_score": ["e"], "s_score": ["s"], "g_score": ["g"],
               "controversy_score": ["controversy"], "carbon_intensity": ["carbon", "carbon_emission"]}
FIN_ALIASES = {"date": ["yearmonth", "month", "日期", "公告日"], "ticker": ["stock_id", "code", "symbol", "代號"],
               "debt_ratio": ["lev"]}


def parse_prices(df: pd.DataFrame) -> pd.DataFrame:
    df = rename_by_alias(df, PRICE_ALIASES)
    df.columns = [str(c).strip() for c in df.columns]
    lower = {c: c.lower() for c in df.columns if c.lower() in {"date", "ticker", "close", "open", "high", "low", "volume"}}
    df = df.rename(columns=lower)
    if "date" not in df.columns:
        raise ValueError("價格檔需要 date 欄位")
    if not {"ticker", "close"}.issubset(df.columns):  # 寬表 → 長表
        value_cols = [c for c in df.columns if c != "date"]
        df = df.melt(id_vars=["date"], value_vars=value_cols, var_name="ticker", value_name="close")
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
    df["ticker"] = df["ticker"].map(normalize_ticker)
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce") if c in df.columns else float("nan")
    df = df.dropna(subset=["date", "ticker", "close"])
    return df[["date", "ticker", "open", "high", "low", "close", "volume"]].sort_values(["ticker", "date"])


def _parse_dated(df: pd.DataFrame, aliases: dict, what: str) -> pd.DataFrame:
    df = rename_by_alias(df, aliases)
    df.columns = [str(c).strip().lower() for c in df.columns]
    if "ticker" not in df.columns:
        raise ValueError(f"{what} 需要 ticker 欄位")
    df["ticker"] = df["ticker"].map(normalize_ticker)
    if "date" in df.columns:
        df["available_date"] = pd.to_datetime(df.pop("date"), errors="coerce").dt.normalize()
    else:
        df["available_date"] = pd.NaT   # 沒有日期 → 視為靜態資料（UI 會提示前視偏差）
    for c in df.columns:
        if c not in ("ticker", "available_date"):
            conv = pd.to_numeric(df[c], errors="coerce")
            if conv.notna().any():
                df[c] = conv
    return df


def parse_esg(df: pd.DataFrame) -> pd.DataFrame:
    return _parse_dated(df, ESG_ALIASES, "ESG 檔")


def parse_financials(df: pd.DataFrame) -> pd.DataFrame:
    return _parse_dated(df, FIN_ALIASES, "財務檔")


def load_folder(folder: Path) -> Dict[str, Optional[pd.DataFrame]]:
    folder = Path(folder)
    spec = {"prices": ("stock_price.csv", parse_prices), "benchmarks": ("etf_prices.csv", parse_prices),
            "esg": ("esg_scores.csv", parse_esg), "financials": ("financials.csv", parse_financials)}
    out: Dict[str, Optional[pd.DataFrame]] = {}
    for key, (fname, fn) in spec.items():
        path = folder / fname
        out[key] = fn(read_csv_any(path)) if path.exists() else None
    return out
