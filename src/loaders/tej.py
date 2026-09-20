"""讀取 TEJ TESG 評等下載檔。

把下載檔（TEJ Pro 匯出的 .xlsx，或 CSV：cp950 / UTF-8 皆可）放進 data/raw/tej/，檔名不拘，可一次多期。
程式會全部讀進來、合併、去除重複，並以「TESG評等公告日」作為這筆評等「可以被使用」的日期，
回測時某天只會用到當天以前已公告的評等（避免前視偏差）。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import pandas as pd

from .. import config
from ..utils import normalize_ticker, read_csv_any, rename_by_alias

log = logging.getLogger(__name__)

TEJ_ALIASES = {
    "code": ["代號", "公司代碼", "證券代碼", "股票代號"],
    "name": ["名稱", "公司名稱", "簡稱"],
    "period": ["TESG評等季度", "評等季度", "年月"],
    "available_date": ["TESG評等公告日", "評等公告日", "公告日"],
    "industry": ["交易所產業名", "產業別"],
    "sasb_industry": ["SASB主產業"],
    "esg_grade": ["TESG等級", "等級"],
    "esg_total": ["TESG分數", "總分", "ESG總分"],
    "event_score": ["事件雷達轉換計分"],
    "e_score": ["環境構面分數", "E評分", "環境分數"],
    "s_score": ["社會構面分數", "S評分", "社會分數"],
    "g_score": ["公司治理構面分數", "G評分", "治理分數"],
}
TEJ_COLS = ["ticker", "name", "period", "available_date", "industry", "sasb_industry",
            "esg_grade", "esg_total", "e_score", "s_score", "g_score", "event_score", "source_file"]


def _parse_period(s: pd.Series) -> pd.Series:
    """'2026/06' → 2026-06-30（該季最後一天）"""
    p = pd.to_datetime(s.astype(str).str.strip(), format="%Y/%m", errors="coerce")
    return p + pd.offsets.MonthEnd(0)


def parse_tej(df: pd.DataFrame, otc_codes: Optional[set] = None, source: str = "") -> pd.DataFrame:
    df = rename_by_alias(df, TEJ_ALIASES)
    if "code" not in df.columns or "esg_total" not in df.columns:
        raise ValueError(f"{source}：找不到「代號」或「TESG分數」欄位，不像是 TEJ TESG 檔")
    out = pd.DataFrame({"ticker": df["code"].map(lambda c: normalize_ticker(c, otc_codes))})
    for c in TEJ_COLS[1:-1]:
        out[c] = df[c] if c in df.columns else pd.NA
    for c in ["esg_total", "e_score", "s_score", "g_score", "event_score"]:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out["period"] = _parse_period(out["period"]) if "period" in df.columns else pd.NaT
    ann = pd.to_datetime(out["available_date"].astype(str).str.strip(), errors="coerce") \
        if "available_date" in df.columns else pd.Series(pd.NaT, index=out.index)
    # 沒有公告日時，保守地用「評等季度結束日」當可用日
    out["available_date"] = ann.fillna(out["period"])
    out["source_file"] = source
    out = out.dropna(subset=["ticker", "esg_total", "available_date"])
    return out[TEJ_COLS]


def _read_any(f: Path) -> pd.DataFrame:
    """CSV（cp950/UTF-8）或 TEJ Pro 直接匯出的 Excel 都可以；代號一律當文字讀，避免 0050 變成 50。"""
    if f.suffix.lower() in (".xlsx", ".xls"):
        return pd.read_excel(f, dtype=str)
    return read_csv_any(f, dtype=str)


def load_tej(folder: Path = config.TEJ_DIR, otc_codes: Optional[set] = None) -> pd.DataFrame:
    folder = Path(folder)
    files = sorted(f for f in folder.glob("*") if f.suffix.lower() in (".csv", ".xlsx", ".xls")
                   and not f.name.startswith("~$")) if folder.exists() else []   # ~$ 是 Excel 開啟中的暫存檔
    frames = []
    for f in files:
        try:
            frames.append(parse_tej(_read_any(f), otc_codes, f.name))
        except Exception as e:
            log.warning("略過 %s：%s", f.name, e)
    if not frames:
        return pd.DataFrame(columns=TEJ_COLS)
    df = pd.concat(frames, ignore_index=True)
    # 同一公司同一期重複下載 → 留公告日最新的一筆
    df = (df.sort_values(["ticker", "period", "available_date"])
            .drop_duplicates(["ticker", "period"], keep="last")
            .drop_duplicates(["ticker", "available_date"], keep="last"))
    return df.reset_index(drop=True)
