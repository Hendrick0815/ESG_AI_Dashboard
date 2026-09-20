"""回測結果存檔：同一組資料＋設定只算一次，重開網頁、換頁都直接讀檔。

資料檔（股價、ESG…）有任何更新，或程式版本改變，存檔就自動失效。
存檔位置：outputs/cache/（可以整個刪掉，下次會重算）
"""
from __future__ import annotations

import hashlib
import logging
import pickle
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Optional, Tuple

from . import config

log = logging.getLogger(__name__)

CACHE_VERSION = "2026-09-20b"   # 回測邏輯有改時換掉，舊存檔就不會被用到
KEEP_FILES = 30


def data_stamp(mode: str, demo_set: Optional[str] = None) -> Tuple:
    """資料檔的名稱＋修改時間＋大小；任何一個變了，存檔就失效。"""
    if mode == "demo":
        folder = config.DEMO_DIR / (demo_set or "")
        files = sorted(folder.glob("*.csv"))
    else:
        files = [config.PRICES_FILE, config.BENCH_FILE, config.VALUATION_FILE, config.LISTING_FILE,
                 *sorted(config.TEJ_DIR.glob("*.*")), *sorted(config.LOCAL_DIR.glob("*.csv"))]
    return tuple((f.name, int(f.stat().st_mtime), f.stat().st_size) for f in files if f.exists())


def result_key(mode: str, demo_set: Optional[str], stamp: Tuple, params) -> str:
    raw = repr((CACHE_VERSION, mode, demo_set, stamp, sorted(asdict(params).items())))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _path(key: str) -> Path:
    return config.CACHE_DIR / f"result_{key}.pkl"


def load(key: str):
    p = _path(key)
    if not p.exists():
        return None
    try:
        with p.open("rb") as f:
            return pickle.load(f)
    except Exception as e:   # 套件升級後舊檔可能讀不了 → 當作沒有
        log.warning("回測存檔讀取失敗，將重新計算：%s", e)
        return None


def save(key: str, result) -> None:
    try:
        config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _path(key).with_suffix(".tmp")
        with tmp.open("wb") as f:
            pickle.dump(result, f, protocol=pickle.HIGHEST_PROTOCOL)
        tmp.replace(_path(key))
        old = sorted(config.CACHE_DIR.glob("result_*.pkl"), key=lambda x: x.stat().st_mtime)
        for f in old[:-KEEP_FILES]:
            f.unlink(missing_ok=True)
    except Exception as e:
        log.warning("回測結果存檔失敗（不影響使用）：%s", e)


def get_or_run(mode: str, demo_set: Optional[str], params, load_dataset: Callable, run: Callable,
               progress=None):
    """先找存檔；沒有才真的計算，算完存檔。回傳 (result, 是否來自存檔)。"""
    stamp = data_stamp(mode, demo_set)
    key = result_key(mode, demo_set, stamp, params)
    res = load(key)
    if res is not None:
        return res, True
    res = run(load_dataset(), params, progress=progress)
    save(key, res)
    return res, False
