"""個股分析（原 my_project/app.py）：走勢、風險、ESG、同業比較。"""
import numpy as np
import pandas as pd
import streamlit as st

from src.metrics import fmt_num, fmt_pct, performance, price_metrics
from src.ui import charts
from src.ui.common import label, setup_page, show_notes, sidebar_data
from src.utils import normalize_ticker

setup_page("個股分析", "🔍")
ds, mode, demo_set = sidebar_data()
names, industries = ds.names, ds.industries
st.title("🔍 個股分析")


@st.cache_data(ttl=3600, show_spinner="從 Yahoo Finance 抓取…")
def fetch_one(ticker: str, start, end) -> pd.DataFrame:
    from src.crawlers import yahoo
    df, _ = yahoo.fetch_prices([ticker], start, end)
    return df


# ------------------------------------------------------------------ 選標的
tickers = sorted(ds.prices["ticker"].unique()) if not ds.prices.empty else []
with st.sidebar:
    st.subheader("標的")
    typed = st.text_input("輸入代號（如 2330；不在資料裡會即時抓取）", "")
    choice = st.selectbox("或從資料中選擇", tickers, format_func=lambda t: label(t, names)) if tickers else None
    candle = st.toggle("K 線圖", value=False)
ticker = normalize_ticker(typed) if typed.strip() else choice
if not ticker:
    st.info("請輸入股票代號，或先在首頁更新資料。")
    st.stop()

px_df = ds.prices[ds.prices["ticker"] == ticker].sort_values("date")
end_default = pd.Timestamp.today().normalize() if px_df.empty else px_df["date"].max()
with st.sidebar:
    lookback = st.select_slider("期間", options=["3 個月", "6 個月", "1 年", "2 年", "3 年", "全部"], value="1 年")
months = {"3 個月": 3, "6 個月": 6, "1 年": 12, "2 年": 24, "3 年": 36}.get(lookback)
start = (end_default - pd.DateOffset(months=months)) if months else pd.Timestamp("2000-01-01")

if px_df.empty:
    if mode == "demo":
        st.warning(f"示範資料裡沒有 {ticker}。")
        st.stop()
    try:
        px_df = fetch_one(ticker, (start - pd.DateOffset(days=120)).strftime("%Y-%m-%d"), end_default.strftime("%Y-%m-%d"))
    except Exception as e:
        st.error(f"抓不到 {ticker} 的價格：{e}")
        st.stop()
    if px_df.empty:
        st.error(f"{ticker} 在這段期間沒有交易資料。")
        st.stop()

d = px_df.copy()
d["sma20"] = d["close"].rolling(20).mean()
d["sma60"] = d["close"].rolling(60).mean()
d["ret"] = d["close"].pct_change()
d["vol20"] = d["ret"].rolling(20).std() * np.sqrt(252)
d = d[d["date"] >= start]
m = price_metrics(d["close"])

# ESG：取期間結束時「已公告」的最新一期
esg_row = None
if not ds.esg.empty:
    e = ds.esg[(ds.esg["ticker"] == ticker)].sort_values("available_date")
    e_known = e[e["available_date"].isna() | (e["available_date"] <= d["date"].max())]
    esg_row = (e_known if not e_known.empty else e).iloc[-1] if not e.empty else None

name = names.get(ticker, "")
ind = industries.get(ticker, "")
st.markdown(f"### {ticker}　{name}" + (f"　<span style='opacity:.7'>｜{ind}</span>" if ind else ""),
            unsafe_allow_html=True)
st.caption(f"資料期間：{d['date'].min():%Y-%m-%d} ～ {d['date'].max():%Y-%m-%d}")
if ds.mode == "demo":
    show_notes(ds.notes)

c = st.columns(5)
c[0].metric("累積報酬", fmt_pct(m["cum_return"]))
c[1].metric("年化波動", fmt_pct(m["ann_vol"]))
c[2].metric("Sharpe", fmt_num(m["sharpe"]))
c[3].metric("最大回撤", fmt_pct(m["max_drawdown"]))
if esg_row is not None and pd.notna(esg_row.get("esg_total")):
    grade = esg_row.get("esg_grade")
    c[4].metric("ESG 評等", f"{grade if isinstance(grade, str) else ''} {esg_row['esg_total']:.1f}".strip())
else:
    c[4].metric("ESG 評等", "無資料")

tab1, tab2, tab3, tab4 = st.tabs(["走勢", "風險與技術指標", "ESG", "同業比較"])

with tab1:
    st.plotly_chart(charts.price_chart(d, candle, "價格走勢"), width="stretch",
                    config={"scrollZoom": True})
    ret, vol, dd = m["cum_return"], m["ann_vol"], m["max_drawdown"]
    trend = ("強勁上漲" if ret > 0.2 else "溫和上漲" if ret > 0 else "震盪回落" if ret > -0.2 else "明顯下跌")
    last, ma20, ma60 = d["close"].iloc[-1], d["sma20"].iloc[-1], d["sma60"].iloc[-1]
    pos = ("站上月線與季線" if last > ma20 and last > ma60 else "跌破月線與季線" if last < ma20 and last < ma60
           else "位於月線與季線之間") if pd.notna(ma60) else "資料不足以判斷均線位置"
    st.info(f"**規則式摘要**（依固定門檻自動產生，非投資建議）：期間內由 {d['close'].iloc[0]:.2f} 變動至 {last:.2f}，"
            f"呈現**{trend}**（{fmt_pct(ret)}）；年化波動 {fmt_pct(vol)}"
            f"{'，波動偏高' if vol > 0.35 else ''}；最大回撤 {fmt_pct(dd)}；目前股價{pos}。")

with tab2:
    a, b = st.columns(2)
    a.plotly_chart(charts.line_chart(d.dropna(subset=["vol20"]), "date", "vol20", "20 日年化波動率", pct=True), width="stretch")
    b.plotly_chart(charts.histogram(d["ret"].dropna(), "日報酬分布"), width="stretch")
    st.dataframe(pd.DataFrame({
        "指標": ["Sharpe", "最大回撤", "年化波動", "日報酬平均", "日報酬變異數"],
        "數值": [fmt_num(m["sharpe"]), fmt_pct(m["max_drawdown"]), fmt_pct(m["ann_vol"]),
               fmt_pct(m["daily_mean"]), fmt_num(m["daily_var"], 6)],
        "怎麼看": ["每承擔一單位波動換到的超額報酬，越高越有效率", "從高點跌下來最深的幅度，代表最糟情況",
                "價格變動的劇烈程度，越大越不穩定", "每天平均賺或賠多少", "單日漲跌的分散程度"],
    }), hide_index=True, width="stretch")

with tab3:
    if esg_row is None:
        st.info("這檔股票沒有 ESG 資料。把 TEJ TESG 下載檔放進 data/raw/tej/ 即可顯示。")
    else:
        a, b = st.columns([1, 1])
        vals = [esg_row.get(k) for k in ("e_score", "s_score", "g_score")]
        if all(pd.notna(v) for v in vals):
            a.plotly_chart(charts.esg_radar(*[float(v) for v in vals], float(esg_row["esg_total"])), width="stretch")
        info_rows = {
            "ESG 總分": esg_row.get("esg_total"), "等級": esg_row.get("esg_grade"),
            "環境 E": esg_row.get("e_score"), "社會 S": esg_row.get("s_score"), "治理 G": esg_row.get("g_score"),
            "事件雷達分數": esg_row.get("event_score"), "爭議分數": esg_row.get("controversy_score"),
            "公告日": esg_row.get("available_date"), "SASB 產業": esg_row.get("sasb_industry"),
        }
        b.dataframe(pd.DataFrame({"項目": list(info_rows), "數值": [
            (f"{v:%Y-%m-%d}" if isinstance(v, pd.Timestamp) else f"{v:.2f}" if isinstance(v, (float, np.floating)) else str(v))
            for v in info_rows.values()]}).query("數值 not in ['nan', 'None', '<NA>', 'NaT']"),
            hide_index=True, width="stretch")
        hist = ds.esg[ds.esg["ticker"] == ticker].dropna(subset=["available_date"]).sort_values("available_date")
        if len(hist) > 1:
            st.plotly_chart(charts.line_chart(hist, "available_date", "esg_total", "ESG 總分歷史（依公告日）"), width="stretch")
        else:
            st.caption("目前只有一期 ESG 評等；補上更多期 TEJ 資料後會顯示歷史變化。")

with tab4:
    pool = [t for t in ds.prices["ticker"].unique()]
    same = [t for t in pool if ind and industries.get(t) == ind]
    peers = same if len(same) >= 3 else pool
    st.caption(f"比較對象：{'同產業「' + ind + '」' if peers is same else '資料中的全部股票'}（{len(peers)} 檔），期間同上")
    latest_esg = (ds.esg.sort_values("available_date").groupby("ticker")["esg_total"].last()
                  if not ds.esg.empty and "esg_total" in ds.esg.columns else pd.Series(dtype=float))
    rows = []
    for t in dict.fromkeys([ticker, *peers]):
        g = ds.prices[(ds.prices["ticker"] == t) & (ds.prices["date"] >= start)].sort_values("date")
        if t == ticker:
            g = d
        if len(g) < 20:
            continue
        pm = performance(g["close"].pct_change())
        rows.append({"代號": t, "公司": names.get(t, ""), "產業": industries.get(t, ""),
                     "ESG 總分": latest_esg.get(t, np.nan), "累積報酬": pm["cum_return"], "年化波動": pm["ann_vol"],
                     "Sharpe": pm["sharpe"], "最大回撤": pm["max_drawdown"]})
    peer_df = pd.DataFrame(rows)
    if peer_df.empty:
        st.info("沒有可比較的股票")
    else:
        st.dataframe(peer_df.style.format({"ESG 總分": "{:.1f}", "累積報酬": "{:.1%}", "年化波動": "{:.1%}",
                                           "Sharpe": "{:.2f}", "最大回撤": "{:.1%}"}, na_rep="-"),
                     hide_index=True, width="stretch")
        pts = peer_df.dropna(subset=["ESG 總分"])
        if len(pts) >= 2:
            st.plotly_chart(charts.scatter_peers(pts, "ESG 總分", "累積報酬", "代號", ticker,
                                                 "ESG 與報酬", "ESG 總分", "累積報酬"), width="stretch")
