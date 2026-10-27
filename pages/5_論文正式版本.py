"""論文正式版本：讀取 scripts/research/run_research.py 與 build_report.py 的輸出（逐期股票池、含下市股），
顯示論文第三、四章的表格與圖。數字固定在資料截點，不會隨網站每天更新而改變。"""
import html
import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import config
from src.backtest import STRATEGY_AI, STRATEGY_AI_ESG, STRATEGY_ESG
from src.ui import charts
from src.ui.common import metric_cards, setup_page

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "research_config.json").read_text(encoding="utf-8"))
RUN = ROOT / "outputs" / "research" / CFG["run_id"]
TABLES = RUN / "report" / "web_tables.json"

# 論文名稱 → 網站內部名稱（沿用網站各策略／基準的固定顏色與線型）
SITE_NAME = {"單純 AI": STRATEGY_AI, "AI+ESG": STRATEGY_AI_ESG, "規則式 ESG 篩選": STRATEGY_ESG,
             "0050": "0050.TW", "00850": "00850.TW", "00878": "00878.TW", "加權指數": "^TWII"}

setup_page("論文正式版本", "📄")
st.title("📄 論文正式版本")

if not TABLES.exists():
    st.info("尚未產生論文版結果。請先執行 `python scripts/research/run_research.py` 與 "
            "`python scripts/research/build_report.py`。")
    st.stop()

tables = {t["key"]: t for t in json.loads(TABLES.read_text(encoding="utf-8"))}
st.caption(f"研究版本 {CFG['run_id']}｜資料截點 {CFG['data_cutoff']}｜評估期 {CFG['periods']['exploratory_evaluation'][0]} ～ "
           f"{CFG['periods']['exploratory_evaluation'][1]}（探索性）｜保留測試自 {CFG['periods']['locked_holdout'][0]} 起")
st.info("本頁是論文使用的正式結果：每個調倉日以「當時」成交金額前 300 大重建股票池，並保留之後下市的股票；"
        "設定固定在 research_config.json。其他頁面以「目前」前 300 大回測，報酬會因後見之明偏誤而偏高，兩者數字不同。")


# ------------------------------------------------------------------ 表格
CSS = """
<style>
.thesis-tbl{width:100%;border-collapse:collapse;font-size:15px;line-height:1.45;
  font-family:"Source Sans Pro","Source Sans 3","Noto Sans CJK TC","Microsoft JhengHei",sans-serif;
  font-variant-numeric:tabular-nums;table-layout:auto}
.thesis-tbl th{background:#1F3864;color:#fff;font-weight:600;padding:7px 9px;border:1px solid #1F3864;
  text-align:center;vertical-align:middle}
.thesis-tbl td{padding:6px 9px;border:1px solid rgba(128,128,128,.35);vertical-align:middle;overflow-wrap:anywhere}
.thesis-tbl tbody tr:nth-child(even) td{background:rgba(31,56,100,.07)}
.thesis-tbl .l{text-align:left}.thesis-tbl .c{text-align:center}.thesis-tbl .r{text-align:right;white-space:nowrap}
.thesis-tbl td{padding:6px 8px}
</style>
"""


def table_html(t) -> str:
    tot = sum(t["widths"])
    cols = "".join(f'<col style="width:{w / tot:.2%}">' for w in t["widths"])
    head = "".join(f"<th>{html.escape(h)}</th>" for h in t["header"])
    body = "".join("<tr>" + "".join(f'<td class="{t["align"][j]}">{html.escape(v)}</td>' for j, v in enumerate(r))
                   + "</tr>" for r in t["rows"])
    return f'{CSS}<table class="thesis-tbl"><colgroup>{cols}</colgroup><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def show_table(key: str) -> None:
    t = tables.get(key)
    if t is None:
        return
    st.markdown(f"**{t['caption'].replace('　', ' ')}**")
    with st.container(key=f"tbl-{key}"):
        st.html(table_html(t))
    if t.get("note"):
        st.caption(t["note"])


def show_figure(key: str, title: str, fig: go.Figure, note: str = "") -> None:
    st.markdown(f"**{title}**")
    with st.container(key=f"fig-{key}"):
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    if note:
        st.caption(note)


# ------------------------------------------------------------------ 圖
@st.cache_data
def load_csv(name: str, mtime: float) -> pd.DataFrame:
    return pd.read_csv(RUN / name, parse_dates=["date"])


def csv(name):
    return load_csv(name, (RUN / name).stat().st_mtime)


def nav_figure() -> go.Figure:
    sr = csv("strategy_returns.csv")
    sr = sr[sr["date"] >= pd.Timestamp(CFG["backtest_start"])].copy()
    sr["portfolio"] = sr["portfolio"].map(SITE_NAME).fillna(sr["portfolio"])
    labels = {v: k for k, v in SITE_NAME.items()}
    fig = charts.nav_chart(sr, labels, title="", log_y=True)
    fig.update_layout(height=430, hovermode="x unified")
    fig.update_xaxes(tickformat="%Y-%m")
    return fig


def esg_figure() -> go.Figure:
    eq = csv("esg_quality_by_rebalance.csv")
    eq = eq[eq["date"] >= pd.Timestamp(CFG["backtest_start"])]
    fig = go.Figure()
    for name in ["規則式 ESG 篩選", "AI+ESG", "股票池等權", "單純 AI"]:
        g = eq[eq["portfolio"] == name]
        if g.empty:
            continue
        if name == "股票池等權":
            line = dict(color=charts._c("#3f3e3b"), width=1.6, dash="dash")
        else:
            line = dict(color=charts.STRATEGY_COLORS[SITE_NAME[name]], width=2.4)
        fig.add_trace(go.Scatter(x=g["date"], y=g["esg_total"], mode="lines", name=name, line=line,
                                 hovertemplate="%{y:.1f}"))
    fig = charts._layout(fig, "", height=360, y_title="持股加權 TESG 分數")
    fig.update_xaxes(tickformat="%Y-%m")
    return fig


# ------------------------------------------------------------------ 版面
perf = pd.read_csv(RUN / "tables" / "table_4_1_performance.csv", index_col=0)
cards = []
for name in ["單純 AI", "AI+ESG", "規則式 ESG 篩選", "0050", "00850"]:
    if name in perf.index:
        r = perf.loc[name]
        cards.append((f"{name} 年化報酬", f"{r['年化報酬']:.1%}", f"Sharpe {r['Sharpe']:.2f}｜最大回撤 {r['最大回撤']:.1%}"))
metric_cards(cards, min_width=180)

NAMES = ["股票池與期間", "績效", "市場情境", "統計檢定", "交易成本", "ESG 品質", "模型"]
# ?all=1：全部依序展開（給 capture_web.py 截圖用）；平常以分頁顯示
tabs = [st.container() for _ in NAMES] if st.query_params.get("all") else st.tabs(NAMES)
with tabs[0]:
    for k in ["3-3", "3-7", "3-8"]:
        show_table(k)
with tabs[1]:
    show_table("4-1")
    show_figure("4-1", "圖 4-1 累積淨值（對數刻度）", nav_figure(),
                "起點 = 1（評估期第一天）；策略已扣手續費與證交稅。來源：strategy_returns.csv。")
    show_table("4-2")
    show_table("4-3")
with tabs[2]:
    show_table("4-4")
    show_table("4-5")
with tabs[3]:
    show_table("4-6")
    show_table("4-7")
with tabs[4]:
    show_table("4-8")
    show_table("4-9")
with tabs[5]:
    show_table("4-10")
    show_figure("4-2", "圖 4-2 各調倉日持股加權 TESG 分數", esg_figure(),
                "「股票池等權」為當期 300 檔等權，作為市場代理。來源：esg_quality_by_rebalance.csv。")
with tabs[6]:
    show_table("4-11")
    show_table("4-12")

with st.expander("下載與重現方式"):
    st.markdown("在乾淨環境重現：`pip install -r requirements-lock.txt` → `python scripts/research/run_research.py` → "
                "`python scripts/research/build_report.py`。manifest.json 記錄設定、資料與程式的 SHA-256 與套件版本。")
    for name in ["strategy_returns.csv", "holdings.csv", "universe_history.csv", "availability_checks.csv", "manifest.json"]:
        if (RUN / name).exists():
            st.download_button(f"下載 {name}", (RUN / name).read_bytes(), name, key=f"dl-{name}")
