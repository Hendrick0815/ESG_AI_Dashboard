"""大盤趨勢預測：加權指數未來 1 個月／1 季的方向（牛／熊）與風險（高波動、大回檔），附樣本外成績。"""
import importlib

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from src import config, market_trend as mt
from src.ui import charts
from src.ui.common import metric_cards, setup_page

if not hasattr(mt, "risk_level"):          # 雲端更新程式時模組可能仍是舊版
    importlib.reload(mt)

setup_page("大盤趨勢預測", "🧭")
st.title("🧭 大盤趨勢預測")


@st.cache_data(show_spinner="計算大盤趨勢預測（約 10 秒）…")
def compute(mtime: float):
    return mt.run()


if not config.MACRO_FILE.exists():
    st.info("還沒有大盤長期資料。請執行 `py scripts/update_data.py --auto`（會下載 1997 年起的加權指數、美股、VIX）。")
    st.stop()
res = compute(config.MACRO_FILE.stat().st_mtime)
if res is None:
    st.warning("大盤資料不足，無法計算。")
    st.stop()

M, L = res.metrics, res.latest
st.caption(f"資料到 {res.asof:%Y-%m-%d}（加權指數收盤；美股只用前一晚已收盤的資料）｜"
           f"樣本外評估期 {M['up20']['start']:%Y-%m-%d} 起，共約 {M['up20']['n']:,} 個交易日")

ICON = {"偏多": "🐂 偏多", "偏空": "🐻 偏空", "中性": "↔️ 中性"}
RISK_ICON = {"高": "🔴 高", "中": "🟡 中", "低": "🟢 低"}
p20, p60 = L["up20"]["p"], L["up60"]["p"]
pv, pdd = L["hivol20"]["p"], L["dd60"]["p"]
level = mt.risk_level(pv, M["hivol20"]["base"])


def trust(auc_: float) -> str:
    if auc_ >= 0.7:
        return "可信度高"
    if auc_ >= 0.58:
        return "可信度中"
    return "可信度低"


# ------------------------------------------------------------------ 結論卡片
st.subheader("目前判斷")
metric_cards([
    ("未來 1 個月（20 日）方向", ICON[mt.state_of(p20)],
     f"上漲機率 {p20:.0%}｜{trust(M['up20']['auc'])}（樣本外 AUC {M['up20']['auc']:.2f}）"),
    ("未來 1 季（60 日）方向", ICON[mt.state_of(p60)],
     f"上漲機率 {p60:.0%}｜{trust(M['up60']['auc'])}（樣本外 AUC {M['up60']['auc']:.2f}）"),
    ("未來 1 個月波動風險", RISK_ICON[level],
     f"高波動機率 {pv:.0%}（歷史平均 {M['hivol20']['base']:.0%}）｜{trust(M['hivol20']['auc'])}（AUC {M['hivol20']['auc']:.2f}）"),
    ("未來 1 季大回檔風險", f"{pdd:.0%}",
     f"60 日內跌 ≥10% 的機率（歷史平均 {M['dd60']['base']:.0%}）｜{trust(M['dd60']['auc'])}（AUC {M['dd60']['auc']:.2f}）"),
], min_width=230)

dir_ok = max(M["up20"]["auc"], M["up60"]["auc"]) >= 0.58
summary = []
if not dir_ok:
    summary.append("**方向（牛／熊）**：模型在 2008 年以來的樣本外測試中，並沒有比「一律猜會漲」更準"
                   f"（20 日 AUC {M['up20']['auc']:.2f}、60 日 {M['up60']['auc']:.2f}，0.5 等於丟銅板），"
                   "上面的偏多／偏空只能當參考，不建議據此進出場。")
summary.append(f"**風險**：未來 1 個月出現高波動（年化 ≥ 25%）的機率 {pv:.0%}，約為歷史平均的 "
               f"{pv / M['hivol20']['base']:.1f} 倍——這一項模型有明顯預測力（AUC {M['hivol20']['auc']:.2f}），"
               "風險高時可考慮降低持股或部位。")
st.markdown("\n\n".join(summary))

# ------------------------------------------------------------------ 走勢圖
st.subheader("加權指數與預測機率")
span = st.radio("期間", ["近 1 年", "近 3 年", "近 5 年", "2008 年起"], index=1, horizontal=True)
years = {"近 1 年": 1, "近 3 年": 3, "近 5 年": 5}.get(span)
d = res.data.copy()
d = d[d["date"] >= (res.asof - pd.DateOffset(years=years) if years else pd.Timestamp(mt.EVAL_START))]

fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.62, 0.38], vertical_spacing=0.06)
fig.add_trace(go.Scatter(x=d["date"], y=d["close"], name="加權指數", line=dict(color=charts._c("#3f3e3b"), width=1.6),
                         hovertemplate="%{y:,.0f}<extra>加權指數</extra>"), row=1, col=1)
fig.add_trace(go.Scatter(x=d["date"], y=d["p_up20"], name="20 日上漲機率（方向）",
                         line=dict(color=charts.STRATEGY_COLORS["AI+ESG"], width=1.6),
                         hovertemplate="%{y:.0%}<extra>20 日上漲機率</extra>"), row=2, col=1)
fig.add_trace(go.Scatter(x=d["date"], y=d["p_hivol20"], name="1 個月高波動機率（風險）",
                         line=dict(color="#e34948", width=1.6),
                         hovertemplate="%{y:.0%}<extra>高波動機率</extra>"), row=2, col=1)
# 加完線之後再畫底色（空的子圖不會畫 vrect）；高波動風險 ≥ 2 倍歷史平均的日子以紅底標示
hi = d["p_hivol20"] >= 2 * M["hivol20"]["base"]
grp = (hi != hi.shift()).cumsum()
for _, g in d[hi].groupby(grp[hi]):
    fig.add_vrect(x0=g["date"].iloc[0], x1=g["date"].iloc[-1] + pd.Timedelta(days=1), fillcolor="rgba(227,73,72,0.28)",
                  line_width=0, layer="below", row="all", col=1)
for yv in (mt.BULL, mt.BEAR):
    fig.add_hline(y=yv, line=dict(color=charts.GRID, width=1, dash="dot"), row=2, col=1)
fig = charts._layout(fig, "", height=560)
fig.update_yaxes(type="log", title="加權指數（對數）", tickformat=",.0f", row=1, col=1)
fig.update_yaxes(range=[0, 1], tickformat=".0%", title="機率", row=2, col=1)
st.plotly_chart(fig, width="stretch")
st.caption("紅底＝模型判斷未來 1 個月高波動機率 ≥ 歷史平均 2 倍的期間；下圖點線為 40%／60%（偏空／偏多門檻）。"
           "2008 年起每一天的機率都是「當天以前的資料訓練出來的模型」所預測（樣本外）。")

# ------------------------------------------------------------------ 樣本外成績
st.subheader("準不準？樣本外成績")
rows = []
for key in ["up20", "up60", "hivol20", "dd60"]:
    m = M[key]
    rows.append({"預測目標": mt.TARGETS[key]["name"], "樣本外天數": f"{m['n']:,}",
                 "AUC（0.5＝丟銅板）": f"{m['auc']:.2f}", "2020 年後 AUC": f"{m['auc_recent']:.2f}",
                 "Brier（越低越好）": f"{m['brier']:.3f}", "一律猜平均的 Brier": f"{m['brier_base']:.3f}",
                 "結論": "比猜平均準" if m["brier"] < m["brier_base"] and m["auc"] >= 0.55 else
                 ("能分高低但機率偏差" if m["auc"] >= 0.58 else "不比猜平均準")})
st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

a, b = st.columns(2)
with a:
    st.markdown("**方向：模型喊偏多／偏空之後，加權指數實際怎麼走？**")
    rr = []
    for key, lab in [("up20", "20 日"), ("up60", "60 日")]:
        for s_ in ("偏多", "中性", "偏空"):
            x = M[key][s_]
            rr.append({"期間": lab, "模型判斷": s_, "天數": x["n"],
                       "之後真的上漲": f"{x['up']:.0%}" if x["n"] else "-",
                       "之後平均報酬": f"{x['ret']:+.1%}" if x["n"] else "-"})
    st.dataframe(pd.DataFrame(rr), hide_index=True, width="stretch")
    st.caption("如果模型有用，「偏空」之後上漲比例應該明顯較低；實際上偏空之後反而常常反彈，代表方向預測不可靠。")
with b:
    st.markdown("**風險：把每天的高波動機率分成五組，實際發生高波動的比例**")
    q = M["hivol20"]["by_quintile"]
    fq = go.Figure(go.Bar(x=[f"第 {i + 1} 組" for i in range(len(q))], y=q, marker_color="#e34948",
                          text=[f"{v:.0%}" for v in q], textposition="outside"))
    fq = charts._layout(fq, "", height=300, pct_y=True)
    fq.update_layout(showlegend=False, hovermode="closest")
    fq.update_xaxes(title="模型機率由低到高")
    st.plotly_chart(fq, width="stretch")
    st.caption("機率越高的組別，之後真的出現高波動的比例越高，代表風險預測有用。")

# ------------------------------------------------------------------ 今天的判斷依據
with st.expander("今天的判斷依據（各指標的影響）"):
    c1, c2 = st.columns(2)
    for col, key, title in [(c1, "up20", "20 日方向：往右＝偏多"), (c2, "hivol20", "1 個月波動風險：往右＝風險高")]:
        cb = L[key]["contrib"].copy()
        cb = cb.reindex(cb.abs().sort_values().index).tail(10)
        df = pd.DataFrame({"名稱": [mt.FEATURE_LABELS.get(f, f) for f in cb.index], "影響": cb.values})
        fb = go.Figure(go.Bar(x=df["影響"], y=df["名稱"], orientation="h",
                              marker_color=["#e34948" if v > 0 and key != "up20" else
                                            ("#2a78d6" if v > 0 else "#8a8984") for v in df["影響"]],
                              hovertemplate="%{y}：%{x:+.2f}<extra></extra>"))
        fb = charts._layout(fb, title, height=360)
        fb.update_layout(showlegend=False, hovermode="closest")
        col.plotly_chart(fb, width="stretch")
    st.caption("數值為各指標對模型 log-odds 的貢獻（標準化後 × 係數）；只描述模型怎麼使用資料，不代表因果。")

with st.expander("方法說明"):
    st.markdown(f"""
- **資料**：Yahoo Finance 日資料（1997 年起）——加權指數、S&P 500、費城半導體、VIX、美國 10 年期公債殖利率。
  美股收盤在台股之後，所以台股第 t 天只用 t 之前已收盤的美股資料，不會偷看。
- **方向**：預測未來 20／60 個交易日加權指數是否上漲；上漲機率 ≥ {mt.BULL:.0%} 為偏多、≤ {mt.BEAR:.0%} 為偏空，其餘中性。
  特徵為加權指數的報酬、均線距離、波動、回撤、RSI，以及美股、半導體、VIX、美債殖利率。
- **風險**：未來 20 個交易日年化波動 ≥ 25%（高波動）；未來 60 個交易日內從當天跌 ≥ 10%（大回檔）。
- **模型**：標準化 ＋ 羅吉斯迴歸，每 {mt.RETRAIN_EVERY} 個交易日用「當時已知結果」的資料重新訓練（滾動式），
  {mt.EVAL_START[:4]} 年起每一天都是樣本外預測。
- **AUC**：模型能不能把「會發生」和「不會發生」的日子分開；0.5 等於丟銅板、1 為完美。
  **Brier 分數**：機率和實際結果的平均平方誤差，越低越好；和「一律猜歷史平均」比較才知道有沒有用。
- **限制**：大盤方向接近隨機，這裡的方向預測樣本外不比一律猜漲好；台灣景氣燈號、外資長期買賣超等資料
  免費來源取不到完整歷史，尚未納入。所有結果僅供學術參考，不構成投資建議。
""")
