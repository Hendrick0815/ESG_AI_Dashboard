"""雲端（Streamlit Cloud）從 GitHub 拉到新程式時，只會重跑頁面，src 底下已載入的模組仍是舊版，
新函式或新設定會出現 AttributeError。每個頁面最先呼叫 ensure_fresh()：src 的 .py 檔有更新
（或這個行程第一次執行）就把已載入的 src 模組清掉，接下來的 import 會讀到新版。"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent


def _stamp() -> float:
    return max(p.stat().st_mtime for p in _ROOT.rglob("*.py"))


def ensure_fresh() -> None:
    me = sys.modules[__name__]
    stamp = _stamp()
    if getattr(me, "_last", None) != stamp:
        pkg = sys.modules.get("src")
        for name in [m for m in list(sys.modules) if m.startswith("src.") and m != __name__]:
            del sys.modules[name]
            short = name.split(".")[1]
            if pkg is not None and short != "_fresh" and hasattr(pkg, short):
                delattr(pkg, short)     # 「from src import config」會先拿套件屬性，舊的也要拿掉
        me._last = stamp
