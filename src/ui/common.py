"""各頁共用：資料來源選擇、策略參數、快取、顯示小工具。"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

import pandas as pd
import streamlit as st

from .. import config, store
from ..models import available_models
from .. import cache as result_cache
from ..pipeline import Params, Result, run

MODE_LABELS = {"real": "真實資料（爬蟲＋本機＋TEJ）", "demo": "合成示範資料"}


def setup_page(title: str, icon: str = "📊") -> None:
    st.set_page_config(page_title=f"{title}｜ESG-AI 選股平台", page_icon=icon, layout="wide",
                       initial_sidebar_state="expanded")


def _remember(key: str, default):
    """跨頁保留設定值（Streamlit 換頁時會清掉 widget 狀態，另外存一份）。"""
    return st.session_state.get(f"_keep_{key}", default)


def _keep(key: str, value):
    st.session_state[f"_keep_{key}"] = value
    return value


def data_stamp(mode: str = "real", demo_set: Optional[str] = None) -> Tuple:
    """資料檔的修改時間；檔案一更新，快取就會失效。"""
    return result_cache.data_stamp(mode, demo_set)


@st.cache_resource(show_spinner="讀取資料中…", max_entries=4)
def _load(mode: str, demo_set: Optional[str], stamp: Tuple) -> store.Dataset:
    return store.load_dataset(mode, demo_set)


@st.cache_resource
def _memory() -> dict:
    """同一次執行期間放在記憶體的回測結果（換頁、調整顯示選項時直接用）。"""
    return {}


def sidebar_data() -> Tuple[store.Dataset, str, Optional[str]]:
    with st.sidebar:
        st.header("⚙️ 設定")
        modes = list(MODE_LABELS)
        mode = _keep("mode", st.radio("資料來源", modes, index=modes.index(_remember("mode", "real")),
                                      format_func=MODE_LABELS.get))
        demo_set = None
        if mode == "demo":
            sets = store.demo_sets()
            prev = _remember("demo_set", sets[0] if sets else None)
            demo_set = _keep("demo_set", st.selectbox("示範資料集", sets, index=sets.index(prev) if prev in sets else 0))
    ds = _load(mode, demo_set, data_stamp(mode, demo_set))
    return ds, mode, demo_set


def sidebar_strategy(ds: store.Dataset) -> Params:
    models = available_models()
    if not models:
        st.error("請先安裝 scikit-learn：pip install scikit-learn")
        st.stop()
    with st.sidebar:
        st.subheader("選股策略")
        model = _keep("model", st.selectbox("AI 模型", models, index=models.index(_remember("model", models[0]))
                                            if _remember("model", models[0]) in models else 0))
        top_n = _keep("top_n", st.slider("每次持有檔數（Top N）", 3, 30, _remember("top_n", config.DEFAULT_TOP_N)))
        w_opts = ["等權", "集中加權"]
        weighting = _keep("weighting", st.radio("權重方式", w_opts, horizontal=True,
                                                index=w_opts.index(_remember("weighting", "等權")),
                                                help="集中加權：第 1 名 30%，前 5 名約 69%（原 generate_backtest.py 的做法）"))
        esg_w = _keep("esg_w", st.slider("AI+ESG 中 ESG 的比重", 0.0, 1.0, _remember("esg_w", config.DEFAULT_ESG_WEIGHT), 0.05,
                                         help="混合分數 =（1−比重）× AI 預測排名 ＋ 比重 × ESG 排名"))
        st.caption("每月最後一個交易日調倉；已扣交易成本（手續費 0.1425%、賣出證交稅 0.3%）")
        with st.expander("進階"):
            trees = _keep("trees", st.slider("樹的數量", 50, 500, _remember("trees", config.DEFAULT_N_ESTIMATORS), 50))
            static_esg = _keep("static_esg", st.checkbox(
                "ESG 歷史不足時，用最新一期回填（有前視偏差，僅供對照）", _remember("static_esg", False)))
            tickers = sorted(ds.prices["ticker"].unique()) if not ds.prices.empty else []
            names = ds.names
            picked = st.multiselect("限定股票池（空白 = 全部）", tickers, default=[t for t in _remember("pool", []) if t in tickers],
                                    format_func=lambda t: label(t, names))
            _keep("pool", picked)
    return Params(model_name=model, top_n=top_n, n_estimators=trees, esg_weight=esg_w,
                  weighting=weighting, static_esg=static_esg,
                  tickers=tuple(sorted(picked)) or None)


def get_result(mode: str, demo_set: Optional[str], params: Params) -> Optional[Result]:
    """順序：記憶體 → outputs/cache 存檔 → 真的計算（顯示進度條，算完存檔）。"""
    stamp = data_stamp(mode, demo_set)
    key = result_cache.result_key(mode, demo_set, stamp, params)
    mem = _memory()
    if key in mem:
        return mem[key]
    res = result_cache.load(key)
    if res is None:
        box = st.empty()
        with box.container():
            st.info("第一次用這組設定，AI 模型滾動訓練中。算完會存檔，之後打開就不用再等。"
                    "**計算中請不要切換頁面或調整左側設定**，否則會從頭重算。")
            bar = st.progress(0.0, text="準備資料…")

        def progress(i, n, d):
            bar.progress(min(i / max(n, 1), 1.0), text=f"訓練與預測 {i + 1}/{n}（{pd.Timestamp(d):%Y-%m}）")

        try:
            res = run(_load(mode, demo_set, stamp), params, progress=progress)
        except Exception as e:
            box.empty()
            st.error(f"回測無法執行：{e}")
            return None
        box.empty()
        result_cache.save(key, res)
    if len(mem) > 8:
        mem.clear()
    mem[key] = res
    return res


def clear_caches() -> None:
    _load.clear()
    _memory().clear()


def require_prices(ds: store.Dataset) -> None:
    if ds.prices.empty:
        st.warning("目前沒有股價資料。請到「首頁」按「更新資料」，或在左側改用「合成示範資料」。")
        st.stop()


# ------------------------------------------------------------------ 顯示
def label(ticker: str, names: Dict[str, str]) -> str:
    n = names.get(ticker, "")
    return f"{ticker}　{n}" if n else ticker


def show_notes(notes) -> None:
    for n in dict.fromkeys(notes):
        (st.warning if n.startswith("⚠️") else st.info)(n)


def holdings_table(df: pd.DataFrame, names: Dict[str, str], score_fmt: str = "{:.3f}") -> pd.DataFrame:
    out = pd.DataFrame({
        "代號": df["ticker"].values,
        "公司": [names.get(t, "") for t in df["ticker"]],
        "權重": [f"{w:.1%}" for w in df["weight"]],
        "分數": [score_fmt.format(s) if pd.notna(s) else "-" for s in df["score"]],
    })
    return out


def portfolio_labels(names: Dict[str, str]) -> Dict[str, str]:
    """比較基準顯示成「0050.TW 元大台灣50」。"""
    return {t: f"{t} {n}" for t, n in config.BENCHMARK_NAMES.items()} | \
           {t: label(t, names) for t in names if t.startswith("^") or t.startswith("00")}
