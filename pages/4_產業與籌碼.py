"""產業與籌碼：哪些產業正在上漲、主力（三大法人）在買什麼、每檔股票符合哪些選股條件。"""
import pandas as pd
import streamlit as st

from src import analysis
from src.backtest import SCREEN_LABELS
from src.metrics import fmt_pct
from src.ui import charts
from src.ui.common import (data_stamp, get_result, metric_cards, require_prices, setup_page, show_notes,
                           sidebar_data, sidebar_strategy)
from src.utils import to_csv_bytes

setup_page("產業與籌碼", "🏭")
ds, mode, demo_set = sidebar_data()
require_prices(ds)
params = sidebar_strategy(ds)
names, industries = ds.names, ds.industries

st.title("🏭 產業與籌碼")
st.caption(f"資料日期：{ds.prices['date'].max():%Y-%m-%d} 收盤")


@st.cache_data(show_spinner="計算產業趨勢…", max_entries=4)
def _industry(stamp, mode, demo_set):
    return analysis.industry_trend(ds.prices, industries)

tab1, tab2, tab3 = st.tabs(["產業趨勢", "主力動向（三大法人）", "選股條件檢查"])

with tab1:
    it = _industry(data_stamp(mode, demo_set), mode, demo_set)
    if it.empty:
        st.info("沒有產業分類資料。請先更新股票清單（首頁「更新資料」會一併更新 listing.csv）。")
    else:
        up = it[it["趨勢向上"]]
        metric_cards([
            ("趨勢向上的產業", f"{len(up)} / {len(it)}"),
            ("近 1 月最強", f"{it.iloc[0]['產業']}", fmt_pct(it.iloc[0]["近1月"])),
            ("近 1 月最弱", f"{it.iloc[-1]['產業']}", fmt_pct(it.iloc[-1]["近1月"])),
        ])
        st.plotly_chart(charts.industry_bar(it, "近1月", "產業", "各產業近 1 個月報酬（等權）",
                                            height=max(320, 26 * len(it) + 120)), width="stretch")
        st.dataframe(it.style.format({"近5日": "{:.1%}", "近1月": "{:.1%}", "季線乖離": "{:.1%}"}),
                     hide_index=True, width="stretch",
                     column_config={"趨勢向上": st.column_config.CheckboxColumn("趨勢向上")})
        st.caption("產業指數 = 股票池內同產業股票的等權平均。「趨勢向上」= 指數在季線（60 日均線）之上，且近 20 日上漲。"
                   "股票池只有市值前 50 大時，部分產業只有 1～2 檔，參考性較低。")

with tab2:
    if ds.flows.empty:
        st.info("還沒有三大法人買賣超資料。在專案資料夾執行：\n\n"
                "`py scripts/update_data.py --flows`\n\n"
                "第一次會回補整段回測期間（約 40 分鐘，可中斷，下次接著抓）；之後每天自動更新只補最近幾天。")
    else:
        days = st.radio("統計期間", [1, 5, 20], index=1, horizontal=True, format_func=lambda d: f"近 {d} 個交易日")
        ld = analysis.flow_leaders(ds.flows, ds.prices, names, industries, days)
        a, b = ld.attrs.get("period", (None, None))
        if a is not None:
            st.caption(f"{a:%Y-%m-%d} ～ {b:%Y-%m-%d}｜單位：張（1 張 = 1,000 股）｜金額 = 買超股數 × 最新收盤價（估計）")
        by_ind = analysis.flow_by_industry(ld)
        if not by_ind.empty:
            top = pd.concat([by_ind.head(8), by_ind.tail(5)]).drop_duplicates("產業")
            st.plotly_chart(charts.industry_bar(top, "估計金額(億)", "產業", "法人買賣超金額（依產業，億元）", pct=False,
                                                height=max(320, 26 * len(top) + 120)), width="stretch")
        c1, c2 = st.columns(2)
        fmt = {"外資(張)": "{:,.0f}", "投信(張)": "{:,.0f}", "自營商(張)": "{:,.0f}", "合計(張)": "{:,.0f}",
               "估計金額(億)": "{:,.1f}"}
        with c1:
            st.markdown("**買超金額前 15 名**")
            st.dataframe(ld.sort_values("估計金額(億)", ascending=False).head(15).style.format(fmt),
                         hide_index=True, width="stretch")
        with c2:
            st.markdown("**賣超金額前 15 名**")
            st.dataframe(ld.sort_values("估計金額(億)").head(15).style.format(fmt), hide_index=True, width="stretch")
        st.markdown("**投信買超前 10 名**（投信常被視為中小型股的主力）")
        st.dataframe(ld.sort_values("投信(張)", ascending=False).head(10).style.format(fmt),
                     hide_index=True, width="stretch")
        st.caption("資料來源：證交所 T86（僅上市股票）。外資 = 外陸資＋外資自營商。")

with tab3:
    res = get_result(mode, demo_set, params)
    if res is None:
        st.stop()
    show_notes([n for n in res.notes if n not in ds.notes])
    tbl = analysis.screen_table(res.screen, names)
    if tbl.empty:
        st.info("沒有資料")
    else:
        passed = (tbl["合格"] == "✓").sum()
        metric_cards([("最新一天", f"{res.latest_date:%Y-%m-%d}"),
                      ("通過硬性條件", f"{passed} / {len(tbl)} 檔",
                       "流動性＋均線全上＋產業向上" if params.use_screen else "只檢查流動性（技術面條件已關閉）")])
        only = st.toggle("只顯示合格股票", value=True)
        show = tbl[tbl["合格"] == "✓"] if only else tbl
        fmt = {"距區間高點": "{:+.1%}", "量比(5/20)": "{:.2f}", "20日均量(張)": "{:,.0f}", "技術分數": "{:.2f}"}
        st.dataframe(show.style.format({k: v for k, v in fmt.items() if k in show.columns}, na_rep="—"),
                     hide_index=True, width="stretch")
        st.download_button("下載條件檢查表 CSV", to_csv_bytes(tbl), "screen.csv", "text/csv")
        with st.expander("每個條件的定義"):
            st.markdown("\n".join(f"- **{v}**" for v in SCREEN_LABELS.values()) +
                        "\n\n✓ = 符合、✗ = 不符合、— = 沒有資料（例如尚未抓三大法人）。"
                        "技術分數 = 符合幾個加分條件（即將突破、稍微出量、法人買超）＋ 0～0.99 的細部排序。")
