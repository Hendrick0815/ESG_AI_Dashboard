"""各頁共用：資料來源選擇、策略參數、快取、顯示小工具。"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

import html

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
    st.sidebar.caption("🌙 深色模式：網頁右上角 ⋮ → Settings → Theme 選 Dark（選 System 會跟著電腦或手機的設定）")


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


def auto_update_prices(mode: str) -> None:
    """打開網頁時：股價落後最近收盤日就自動補抓（和 TEJ 無關）。每個瀏覽階段只檢查一次。
    公開網站（ESG_ALLOW_UPDATE=0）不會執行。"""
    if mode != "real" or not config.ALLOW_DATA_UPDATE or st.session_state.get("_auto_checked"):
        return
    st.session_state["_auto_checked"] = True
    try:
        if not store.needs_price_update():
            return
    except Exception:
        return
    target = store.last_close_date()
    with st.status(f"自動更新股價到 {target:%Y-%m-%d} 收盤（約 1 分鐘，不需要 TEJ）…", expanded=False) as box:
        try:
            out = store.auto_update(progress=box.write)
        except Exception as e:
            box.update(label=f"自動更新失敗，沿用舊資料：{e}", state="error")
            return
        last = out.get("last_price_date")
        ok = last is not None and pd.Timestamp(last) >= target
        box.update(label=(f"股價已更新到 {last}" if ok else
                          f"股價目前到 {last}（{target:%Y-%m-%d} 可能是休市日，或 Yahoo 尚未提供，稍後會再試）"),
                   state="complete")
    clear_caches()


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
    auto_update_prices(mode)
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
                                                index=w_opts.index(_remember("weighting", config.DEFAULT_WEIGHTING)),
                                                help="集中加權：第 1 名 30%，前 5 名約 69%（原 generate_backtest.py 的做法）"))
        esg_w = _keep("esg_w", st.slider("AI+ESG 中 ESG 的比重", 0.0, 1.0, _remember("esg_w", config.DEFAULT_ESG_WEIGHT), 0.05,
                                         help="混合分數 =（1−比重）× AI 預測排名 ＋ 比重 × ESG 排名"))
        st.caption(f"每 {config.HOLD_DAYS} 個交易日調倉；已扣交易成本（手續費 0.1425%、賣出證交稅 0.3%）")
        risk_on = _keep("risk_on", st.checkbox(
            "風險控制（降低最大回撤，報酬會變低）", _remember("risk_on", config.DEFAULT_RISK_CONTROL),
            help="① 不買跌破年線（200 日均線）的股票\n\n"
                 "② 不買近 60 日波動最高的 20% 股票\n\n"
                 "③ 加權指數跌破年線時持股減半，站回年線恢復滿倉\n\n"
                 "預設關閉（以最高報酬為目標）；勾選可以比較降低回撤後的結果。"))
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
                  tickers=tuple(sorted(picked)) or None,
                  risk_control=risk_on)


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


def metric_cards(items, min_width: int = 170) -> None:
    """取代 st.columns + st.metric：卡片會依視窗寬度自動換行，長文字也會折行，不會和標題重疊。
    items：[(標題, 數值), ...] 或 [(標題, 數值, 小字說明), ...]"""
    cards = []
    for it in items:
        label, value = it[0], it[1]
        sub = it[2] if len(it) > 2 and it[2] else ""
        cards.append(
            f'<div class="esg-card"><div class="esg-card-label">{html.escape(str(label))}</div>'
            f'<div class="esg-card-value">{html.escape(str(value))}</div>'
            + (f'<div class="esg-card-sub">{html.escape(str(sub))}</div>' if sub else "") + "</div>")
    st.markdown(
        "<style>"
        f".esg-cards{{display:grid;grid-template-columns:repeat(auto-fill,minmax({min_width}px,1fr));"
        "gap:.6rem;margin:.25rem 0 1rem}}"
        ".esg-card{border:1px solid rgba(128,128,128,.25);border-radius:.5rem;padding:.6rem .8rem;min-width:0}"
        ".esg-card-label{font-size:.82rem;opacity:.72;line-height:1.3;overflow-wrap:anywhere}"
        ".esg-card-value{font-size:1.35rem;font-weight:600;line-height:1.35;margin-top:.15rem;"
        "overflow-wrap:anywhere;font-variant-numeric:tabular-nums}"
        ".esg-card-sub{font-size:.75rem;opacity:.6;margin-top:.1rem;overflow-wrap:anywhere}"
        "</style>"
        f'<div class="esg-cards">{"".join(cards)}</div>', unsafe_allow_html=True)


def holdings_table(df: pd.DataFrame, names: Dict[str, str], score_fmt: str = "{:.3f}") -> pd.DataFrame:
    out = pd.DataFrame({
        "代號": df["ticker"].values,
        "公司": [names.get(t, "") for t in df["ticker"]],
        "權重": [f"{w:.1%}" for w in df["weight"]],
        "分數": [score_fmt.format(s) if pd.notna(s) else "-" for s in df["score"]],
    })
    return out


SCORE_FMT = {"單純 ESG": "{:.1f}"}


def holdings_block(sub: pd.DataFrame, names: Dict[str, str], strat: str, empty_text: str = "沒有可用的選股") -> None:
    """一個策略的持股表（權重是滿倉時的比例；大盤跌破年線時實際持股會減半）。"""
    if sub.empty:
        st.info(empty_text)
        return
    st.dataframe(holdings_table(sub, names, SCORE_FMT.get(strat, "{:.3f}")), hide_index=True, width="stretch")


def portfolio_labels(names: Dict[str, str]) -> Dict[str, str]:
    """比較基準顯示成「0050.TW 元大台灣50」。"""
    return {t: f"{t} {n}" for t, n in config.BENCHMARK_NAMES.items()} | \
           {t: label(t, names) for t in names if t.startswith("^") or t.startswith("00")}
