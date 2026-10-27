"""大盤趨勢：目前是牛市還是熊市（7 項指標判斷表），以及未來 1 個月的展望（參考）。"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src._fresh import ensure_fresh
ensure_fresh()   # 雲端更新程式後，確保讀到新版 src 模組
from src import config, market_trend as mt
from src.ui import charts
from src.ui.common import metric_cards, setup_page

setup_page("大盤趨勢", "🧭")
st.title("🧭 大盤趨勢")

if not config.MACRO_FILE.exists():
    st.info("還沒有大盤長期資料。請執行 `py scripts/update_data.py --auto`（會下載 1997 年起的加權指數、美股、VIX）。")
    st.stop()


@st.cache_data(show_spinner="判斷大盤趨勢…")
def trend(mtime: float):
    w = mt.load_macro()
    return None if w is None or "^TWII" not in w else mt.current_trend(w)


@st.cache_data(show_spinner="計算未來 1 個月展望（約 10 秒）…")
def outlook(mtime: float):
    return mt.run()


mtime = config.MACRO_FILE.stat().st_mtime
tr = trend(mtime)
if tr is None:
    st.warning("大盤資料不足，無法判斷。")
    st.stop()

ICON = {"牛市": "🐂", "偏多": "📈", "盤整": "↔️", "偏空": "📉", "熊市": "🐻"}
COLOR = {"牛市": "rgba(27,175,122,0.22)", "偏多": "rgba(27,175,122,0.10)", "盤整": "rgba(128,128,128,0.0)",
         "偏空": "rgba(227,73,72,0.10)", "熊市": "rgba(227,73,72,0.24)"}

LEGEND = {"牛市": "rgba(27,175,122,0.7)", "偏多": "rgba(27,175,122,0.35)", "偏空": "rgba(227,73,72,0.35)",
          "熊市": "rgba(227,73,72,0.7)"}

# ------------------------------------------------------------------ 目前趨勢表
st.caption(f"資料到 {tr['date']:%Y-%m-%d} 收盤（美股、VIX 用前一晚已收盤的數字）")
metric_cards([
    ("目前趨勢", f"{ICON[tr['verdict']]} {tr['verdict']}", f"自 {tr['since']:%Y-%m-%d} 起，已 {tr['days']} 個交易日"),
    ("指標統計", f"多 {tr['n_bull']}｜空 {tr['n_bear']}", f"7 項指標，加總分數 {tr['score']:+d}"),
], min_width=260)
st.dataframe(tr["table"], hide_index=True, width="stretch",
             column_config={"指標": st.column_config.TextColumn(width="small"),
                            "判斷": st.column_config.TextColumn(width="small")})
st.caption("判斷規則：7 項指標各給 多（+1）／中性（0）／空（−1）。加總 ≥ 4 為**牛市**、2～3 **偏多**、−1～1 **盤整**、"
           "≤ −2 **偏空**；距一年高點跌超過 20% 依慣例直接判為**熊市**。這張表描述「現在」的狀態，不是預測未來。")

# ------------------------------------------------------------------ 歷史走勢（底色＝當時的判斷）
st.subheader("加權指數與歷來趨勢判斷")
span = st.radio("期間", ["近 1 年", "近 3 年", "近 5 年", "2008 年起"], index=1, horizontal=True)
years = {"近 1 年": 1, "近 3 年": 3, "近 5 年": 5}.get(span)
ts = tr["series"]
ts = ts[ts.index >= (tr["date"] - pd.DateOffset(years=years) if years else pd.Timestamp("2008-01-01"))]
fig = go.Figure()
fig.add_trace(go.Scatter(x=ts.index, y=ts["close"], name="加權指數", line=dict(color=charts._c("#3f3e3b"), width=1.8),
                         customdata=ts["verdict"], hovertemplate="%{y:,.0f}｜%{customdata}<extra></extra>"))
fig.add_trace(go.Scatter(x=ts.index, y=ts["ma200"], name="年線（200 日）", line=dict(color="#eda100", width=1.2, dash="dash"),
                         hovertemplate="年線 %{y:,.0f}<extra></extra>"))
seg = (ts["verdict"] != ts["verdict"].shift()).cumsum()
for _, g in ts.groupby(seg):
    v = g["verdict"].iloc[0]
    if COLOR.get(v, "rgba(0,0,0,0)").endswith("0.0)"):
        continue
    fig.add_vrect(x0=g.index[0], x1=g.index[-1] + pd.Timedelta(days=1), fillcolor=COLOR[v], line_width=0, layer="below")
for v in ["牛市", "偏多", "偏空", "熊市"]:                      # 圖例用的色塊
    fig.add_trace(go.Scatter(x=[None], y=[None], mode="markers", name=v,
                             marker=dict(size=12, symbol="square", color=LEGEND[v])))
fig = charts._layout(fig, "", height=440)
fig.update_yaxes(type="log", tickformat=",.0f", title="加權指數（對數）")
st.plotly_chart(fig, width="stretch")
dist = tr["series"]["verdict"].loc["2008":].value_counts(normalize=True).reindex(mt.TREND_ORDER).fillna(0)
st.caption("底色＝當天收盤後依同一套規則的判斷（深綠牛市、淺綠偏多、淺紅偏空、深紅熊市）。2008 年以來各狀態所占比例："
           + "、".join(f"{k} {v:.0%}" for k, v in dist.items()) + "。")

# ------------------------------------------------------------------ 未來 1 個月展望（參考）
with st.expander("未來 1 個月展望（模型預測，僅供參考）"):
    res = outlook(mtime)
    if res is None:
        st.info("資料不足，無法計算。")
    else:
        M, L = res.metrics, res.latest
        pv, p20 = L["hivol20"]["p"], L["up20"]["p"]
        metric_cards([
            ("未來 1 個月高波動機率", f"{pv:.0%}",
             f"歷史平均 {M['hivol20']['base']:.0%}｜樣本外 AUC {M['hivol20']['auc']:.2f}（預測力佳）"),
            ("未來 1 個月上漲機率", f"{p20:.0%}",
             f"樣本外 AUC {M['up20']['auc']:.2f}（接近丟銅板，參考性低）"),
        ], min_width=260)
        st.markdown(
            "- **波動（會不會劇烈震盪）可以預測**：最近震盪大，接下來通常也震盪大；機率明顯高於歷史平均時要留意風險。\n"
            "- **漲跌方向（牛轉熊、熊轉牛）目前無法可靠預測**：2008 年以來的樣本外測試，模型並不比「一律猜歷史平均」準，"
            "所以趨勢以上方的判斷表為主。")
        rows = []
        for key in ["up20", "up60", "hivol20", "dd60"]:
            m = M[key]
            rows.append({"預測目標": mt.TARGETS[key]["name"], "樣本外天數": f"{m['n']:,}",
                         "AUC（0.5＝丟銅板）": f"{m['auc']:.2f}", "Brier（越低越好）": f"{m['brier']:.3f}",
                         "猜平均的 Brier": f"{m['brier_base']:.3f}"})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.caption("模型：羅吉斯迴歸，特徵為加權指數報酬、均線距離、波動、回撤、RSI 及美股、費城半導體、VIX、美債殖利率；"
                   f"每 {mt.RETRAIN_EVERY} 個交易日只用當時已知結果的資料重新訓練，{mt.EVAL_START[:4]} 年起每天都是樣本外預測。")

with st.expander("指標與資料說明"):
    st.markdown("""
- **資料**：Yahoo Finance 日資料（1997 年起）：加權指數、S&P 500、VIX；每天由自動更新程式抓取（data/processed/macro.csv）。
- **年線**：200 個交易日收盤平均；**季線**：60 個交易日平均。站上年線、年線上揚、季線在年線之上是最常用的多頭定義。
- **熊市**：慣例上指從高點下跌超過 20%；10～20% 稱為修正。
- **VIX**：美國標普 500 選擇權隱含波動率，常被稱為恐慌指數；台股常受美股情緒影響，所以一併納入。
- 判斷表只描述「現在」的狀態，不代表未來一定延續；所有內容僅供學術參考，不構成投資建議。
""")
