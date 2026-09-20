"""ESG-AI 選股平台 — 首頁（總覽＋資料管理）。執行：streamlit run app.py"""
import pandas as pd
import streamlit as st

from src import config, store
from src.backtest import STRATEGIES
from src.metrics import fmt_num, fmt_pct
from src.ui import charts
from src.ui.common import (clear_caches, get_result, holdings_table, portfolio_labels, require_prices,
                           setup_page, show_notes, sidebar_data, sidebar_strategy)

setup_page("首頁")
ds, mode, demo_set = sidebar_data()

st.title("🌿 ESG-AI 台股選股平台")
st.caption("AI 選股 × ESG 因子 × 台股大盤／ETF 比較｜左側選擇資料來源與策略參數，其他頁面會沿用同一組設定")

# ------------------------------------------------------------------ 資料狀態
with st.expander("📦 資料狀態與更新", expanded=ds.prices.empty):
    c1, c2, c3, c4 = st.columns(4)
    p = ds.prices
    c1.metric("股票數", f"{p['ticker'].nunique():,}" if not p.empty else "0")
    c2.metric("價格期間", f"{p['date'].min():%Y-%m-%d} ～ {p['date'].max():%Y-%m-%d}" if not p.empty else "—")
    c3.metric("ESG 資料", f"{ds.esg['ticker'].nunique():,} 檔 / {ds.esg['available_date'].nunique()} 期"
              if not ds.esg.empty else "無")
    c4.metric("比較基準", ", ".join(sorted(ds.benchmarks["ticker"].unique())) if not ds.benchmarks.empty else "無")
    if not p.empty and "source" in p.columns:
        st.caption("價格來源：" + "、".join(f"{k} {v:,} 筆" for k, v in p["source"].value_counts().items()))

    if mode == "real" and config.ALLOW_DATA_UPDATE:
        st.markdown("**從網路更新**（只補抓缺少的日期；也可以在終端機執行 `python scripts/update_data.py`）")
        u1, u2, u3 = st.columns([1, 1, 1])
        universe = u1.selectbox("股票池", ["core", "tej"], format_func={
            "core": "市值前 50 大（約 1 分鐘）", "tej": "所有有 TEJ 評等的股票（約 1,900 檔，10 分鐘以上）"}.get)
        if universe == "tej":
            st.caption("⚠️ 檔數多時建議改在終端機執行 `py scripts/update_data.py --universe tej`："
                       "網頁更新期間不能切換頁面，否則會中斷。")
        years = u2.slider("回看年數", 1, 5, 3)
        do_val = u3.checkbox("一併抓本益比／淨值比／殖利率", value=True, help="每月一筆，約 3 秒一個月")
        if st.button("🔄 更新資料", type="primary"):
            end = pd.Timestamp.today().normalize()
            start = end - pd.DateOffset(years=years)
            log = st.status("更新中…", expanded=True)
            try:
                try:
                    listing = store.update_listing()
                    log.write(f"✅ 股票清單：{len(listing)} 檔普通股")
                except Exception as e:
                    listing = ds.listing
                    log.write(f"⚠️ 股票清單更新失敗（沿用舊的）：{e}")
                tickers = store.pick_universe(universe, listing, None)
                bar = st.progress(0.0, text="下載股價…")
                r = store.update_prices(tickers, start, end,
                                        progress=lambda i, n, phase: bar.progress(min(i / max(n, 1), 1.0),
                                                                                  text=f"{phase} {i}/{n}"))
                bar.empty()
                log.write(f"✅ 股價：新增 {r['rows_downloaded']:,} 筆，失敗 {len(r['failed'])} 檔 {r['failed'][:8]}")
                b = store.update_benchmarks(start, end)
                log.write(f"✅ 比較基準：新增 {b['rows_downloaded']:,} 筆")
                if do_val:
                    v = store.update_valuation(start)
                    log.write(f"✅ 估值：{v}")
                store.append_update_log({"start": start.date(), "end": end.date(), "universe": universe,
                                         "prices_rows": r["rows_downloaded"]})
                log.update(label="更新完成", state="complete")
                clear_caches()
                st.rerun()
            except Exception as e:
                log.update(label=f"更新失敗：{e}", state="error")

    if mode == "real" and not config.ALLOW_DATA_UPDATE:
        st.caption("此網站顯示的是固定的資料快照。資料由專案作者在本機更新後上傳，網站本身不會連線抓取。")

    if config.UPDATE_LOG_FILE.exists():
        with st.popover("更新紀錄"):
            st.dataframe(store._read(config.UPDATE_LOG_FILE, date_cols=()).tail(10), hide_index=True)

show_notes(ds.notes)
require_prices(ds)

# ------------------------------------------------------------------ 總覽
params = sidebar_strategy(ds)
res = get_result(mode, demo_set, params)
if res is None:
    st.stop()
names = ds.names
labels = portfolio_labels(names)
show_notes([n for n in res.notes if n not in ds.notes])

st.subheader(f"🗓️ 最新選股（{res.latest_date:%Y-%m-%d} 收盤後）")
st.caption(f"樣本外回測期間：{res.test_start:%Y-%m-%d} ～ {res.latest_date:%Y-%m-%d}｜每月調倉｜"
           f"{params.weighting}｜Top {params.top_n}｜模型 {params.model_name}")

perf = res.perf.set_index("portfolio")
cols = st.columns(4)
if "AI+ESG" in perf.index:
    cols[0].metric("AI+ESG 年化報酬", fmt_pct(perf.loc["AI+ESG", "ann_return"]))
    cols[1].metric("AI+ESG Sharpe", fmt_num(perf.loc["AI+ESG", "sharpe"]))
    cols[2].metric("AI+ESG 最大回撤", fmt_pct(perf.loc["AI+ESG", "max_drawdown"]))
bench_key = next((b for b in config.BENCHMARKS if b in perf.index), None)
if bench_key:
    cols[3].metric(f"{labels.get(bench_key, bench_key)} 年化報酬", fmt_pct(perf.loc[bench_key, "ann_return"]))

pick_cols = st.columns(3)
desc = {"AI+ESG": "AI 預測排名與 ESG 排名加權", "單純 AI": "只看 AI 預測，不用 ESG", "單純 ESG": "只看 ESG 總分"}
for col, strat in zip(pick_cols, STRATEGIES):
    with col:
        st.markdown(f"**{strat}**　<span style='opacity:.7'>{desc[strat]}</span>", unsafe_allow_html=True)
        sub = res.latest[res.latest["portfolio"] == strat]
        if sub.empty:
            st.info("沒有可用的選股")
        else:
            st.dataframe(holdings_table(sub, names, "{:.1f}" if strat == "單純 ESG" else "{:.3f}"),
                         hide_index=True, width="stretch")

st.plotly_chart(charts.nav_chart(res.returns, labels, "累積淨值（樣本外，扣除交易成本）"), width="stretch")
st.caption("實線 = 策略；虛線 = 比較基準。詳細績效、歷次持股、市場情境請看「策略回測」頁。")

st.divider()
st.caption(
    "**免責聲明**：本站為學術專題成果，所有數字均為歷史資料的回測結果，不代表未來績效，"
    "也不構成任何投資建議。回測假設以收盤價成交，未考慮滑價、流動性與稅務個別差異；"
    "股票池僅含目前仍上市櫃的公司，存在存活者偏差。"
    "資料來源：Yahoo Finance（股價）、台灣證券交易所（清單與估值）、TEJ 台灣經濟新報（TESG 永續評等）。"
    + (f"　{config.SITE_NOTICE}" if config.SITE_NOTICE else ""))
