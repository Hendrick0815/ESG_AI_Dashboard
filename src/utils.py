"""代號格式、檔案讀寫等小工具。"""
from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Dict, Iterable, Optional

import pandas as pd

_CODE_RE = re.compile(r"^\d{4,6}[A-Z]?$")


def normalize_ticker(value, otc_codes: Optional[set] = None) -> Optional[str]:
    """把 '2330'、2330、'2330.tw'、' 2330.TW ' 統一成 '2330.TW'。
    otc_codes 內的代號會加 .TWO（上櫃）。指數（^TWII）與其他格式原樣回傳。"""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    t = str(value).strip().upper()
    if t.endswith(".0") and t[:-2].isdigit():   # Excel 把代號讀成 2330.0
        t = t[:-2]
    if t.endswith(".TW") or t.endswith(".TWO") or t.startswith("^"):
        return t
    if _CODE_RE.match(t):
        if t.isdigit() and len(t) < 4:
            t = t.zfill(4)
        return f"{t}.TWO" if otc_codes and t in otc_codes else f"{t}.TW"
    return t


def code_of(ticker: str) -> str:
    """'2330.TW' -> '2330'"""
    return str(ticker).split(".")[0]


def read_csv_any(path: Path | str, **kwargs) -> pd.DataFrame:
    """自動判斷 UTF-8 / Big5(cp950) 編碼讀 CSV（TEJ 下載檔常是 cp950）。"""
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "cp950"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("cp950", errors="replace")
    return pd.read_csv(io.StringIO(text), **kwargs)


def write_csv(df: pd.DataFrame, path: Path | str) -> None:
    """統一用 utf-8-sig 存檔（Excel 開啟中文不會亂碼）。先寫暫存檔再改名，避免寫到一半壞檔。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.to_csv(tmp, index=False, encoding="utf-8-sig")
    tmp.replace(path)


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")


def rename_by_alias(df: pd.DataFrame, aliases: Dict[str, Iterable[str]]) -> pd.DataFrame:
    """依別名表改欄名：aliases = {'標準名': ['別名1', '別名2', ...]}（比對時忽略大小寫與空白）。"""
    lookup = {}
    for std, names in aliases.items():
        for n in [std, *names]:
            lookup[str(n).strip().lower()] = std
    mapping = {}
    for c in df.columns:
        key = str(c).strip().lower()
        if key in lookup and lookup[key] not in mapping.values():
            mapping[c] = lookup[key]
    return df.rename(columns=mapping)


def to_number(s: pd.Series) -> pd.Series:
    """'1,234.5'、'-'、'--'、'' 之類的字串轉成數字，轉不了就是 NaN。"""
    return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False).str.strip(), errors="coerce")
