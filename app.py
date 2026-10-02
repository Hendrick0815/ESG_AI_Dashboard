"""ESG-AI 選股平台 — 首頁（總覽＋資料管理）。執行：streamlit run app.py"""
import pandas as pd
import streamlit as st

from src import config, store
from src.backtest import STRATEGIES, STRATEGY_DESC
from src.metrics import fmt_num, fmt_pct
from src.ui import charts
from src.ui.common import (clear_caches, get_result, holdings_block, metric_cards, portfolio_labels,
                           require_prices, setup_page, show_notes, sidebar_data, sidebar_strategy)

setup_page("首頁")
ds, mode, demo_set = sidebar_data()

st.title("🌿 ESG-AI 台股選股平台")
st.caption("AI 選股 × ESG 因子 × 台股大盤／ETF 比較｜左側選擇資料來源與策略參數，其他頁面會沿用同一組設定")

# ------------------------------------------------------------------ 資料狀態
with st.expander("📦 資料狀態與更新", expanded=ds.prices.empty):
    p = ds.prices
    last_close = store.last_close_date()
    latest_px = p["date"].max() if not p.empty else None
    metric_cards([
        ("股票數", f"{p['ticker'].nunique():,}" if not p.empty else "0"),
        ("股價資料到", f"{latest_px:%Y-%m-%d}" if latest_px is not None else "—",
         f"從 {p['date'].min():%Y-%m-%d} 開始｜最近收盤日 {last_close:%Y-%m-%d}" if latest_px is not None else ""),
        ("ESG 資料", f"{ds.esg['ticker'].nunique():,} 檔 / {ds.esg['available_date'].nunique()} 期"
         if not ds.esg.empty else "無"),
        ("三大法人", f"到 {ds.flows['date'].max():%Y-%m-%d}" if not ds.flows.empty else "尚未抓取",
         f"{ds.flows['date'].nunique()} 個交易日" if not ds.flows.empty else "py scripts/update_data.py --flows"),
        ("比較基準", "、".join(sorted(ds.benchmarks["ticker"].unique())) if not ds.benchmarks.empty else "無"),
    ])
    if not p.empty and "source" in p.columns:
        st.caption("價格來源：" + "、".join(f"{k} {v:,} 筆" for k, v in p["source"].value_counts().items()))

    if mode == "real" and config.ALLOW_DATA_UPDATE:
        st.markdown("**自動更新**：每次打開網頁，股價若落後最近收盤日會自動補抓（和 TEJ 無關）。"
                    "想在不開網頁時也自動更新，雙擊 `scripts/install_schedule.bat` 建立平日 14:45 的排程。")
        st.markdown("**手動更新／換股票池**（只補抓缺少的日期；也可以在終端機執行 `py scripts/update_data.py`）")
        u1, u2, u3 = st.columns([1, 1, 1])
        universe = u1.selectbox("股票池", ["top", "core", "tej"], format_func={
            "top": f"成交金額前 {config.UNIVERSE_SIZE} 大（第一次約 10 分鐘）",
            "core": "市值前 50 大（約 1 分鐘）", "tej": "所有有 TEJ 評等的股票（約 1,900 檔，10 分鐘以上）"}.get)
        if universe in ("top", "tej"):
            st.caption(f"⚠️ 檔數多時建議改在終端機執行 `py scripts/update_data.py --universe {universe}`："
                       "網頁更新期間不能切換頁面，否則會中斷。")
        years = u2.slider("回看年數", 1, 5, 3)
        do_val = u3.checkbox("一併抓本益比／淨值比／殖利率", value=True, help="每月一筆，約 3 秒一個月")
        if st.button("🔄 更新資料", type="primary"):
            end = store.last_close_date()
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
           f"{params.weighting}｜Top {params.top_n}｜模型 {params.model_name}｜"
           f"{'風險控制：避開跌破年線與最震盪的股票、大盤跌破年線持股減半' if params.risk_control else '目標最高報酬（不做風險控制）'}")

perf = res.perf.set_index("portfolio")
cards = []
for strat in STRATEGIES:
    if strat in perf.index:
        cards.append((f"{strat} 年化報酬", fmt_pct(perf.loc[strat, "ann_return"]),
                      f"累積 {fmt_pct(perf.loc[strat, 'cum_return'])}｜最大回撤 {fmt_pct(perf.loc[strat, 'max_drawdown'])}"
                      f"｜Sharpe {fmt_num(perf.loc[strat, 'sharpe'])}"))
bench_key = next((b for b in config.BENCHMARKS if b in perf.index), None)
if bench_key:
    cards.append((f"{labels.get(bench_key, bench_key)} 年化報酬", fmt_pct(perf.loc[bench_key, "ann_return"]),
                  f"累積 {fmt_pct(perf.loc[bench_key, 'cum_return'])}｜最大回撤 {fmt_pct(perf.loc[bench_key, 'max_drawdown'])}"))
if params.risk_control and not res.risk_log.empty:
    expo = res.risk_log[res.risk_log["date"] == res.risk_log["date"].max()]["exposure"].max()
    cards.append(("目前建議持股比例", fmt_pct(expo),
                  "加權指數在年線之上" if expo >= 0.99 else "加權指數跌破年線，持股減半"))
metric_cards(cards, min_width=200)

pick_cols = st.columns(len(STRATEGIES))
for col, strat in zip(pick_cols, STRATEGIES):
    with col:
        st.markdown(f"**{strat}**<br><span style='opacity:.7;font-size:.9em'>{STRATEGY_DESC[strat]}</span>",
                    unsafe_allow_html=True)
        holdings_block(res.latest[res.latest["portfolio"] == strat], names, strat)

st.plotly_chart(charts.nav_chart(res.returns, labels, "累積淨值（樣本外，扣除交易成本）"), width="stretch")
st.caption("實線 = 策略；虛線 = 比較基準。詳細績效、持股比例、歷次持股請看「策略回測」頁；"
           "產業趨勢、法人買賣超請看「產業與籌碼」頁（僅供參考，不影響選股）。")

st.divider()
st.caption(
    "**免責聲明**：本站為學術專題成果，所有數字均為歷史資料的回測結果，不代表未來績效，"
    "也不構成任何投資建議。回測假設以收盤價成交，未考慮滑價、流動性與稅務個別差異；"
    "股票池僅含目前仍上市櫃的公司，存在存活者偏差。"
    "資料來源：Yahoo Finance（股價）、台灣證券交易所（清單與估值）、TEJ 台灣經濟新報（TESG 永續評等）。"
    + (f"　{config.SITE_NOTICE}" if config.SITE_NOTICE else ""))
