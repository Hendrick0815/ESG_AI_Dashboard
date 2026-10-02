"""策略回測：績效比較、歷次持股、市場情境、換股成本、方法說明。"""
import pandas as pd
import streamlit as st

from src import config
from src.backtest import STRATEGIES
from src.metrics import format_table, performance_table
from src.ui import charts
from src.ui.common import (get_result, holdings_block, portfolio_labels, require_prices, setup_page,
                           show_notes, sidebar_data, sidebar_strategy)
from src.utils import to_csv_bytes

setup_page("策略回測", "📈")
ds, mode, demo_set = sidebar_data()
require_prices(ds)
params = sidebar_strategy(ds)
res = get_result(mode, demo_set, params)
if res is None:
    st.stop()
names = ds.names
labels = portfolio_labels(names)

st.title("📈 策略回測")
st.caption(f"樣本外期間 {res.test_start:%Y-%m-%d} ～ {res.latest_date:%Y-%m-%d}，共 {len(res.rebalance_dates)} 次調倉")
show_notes(res.notes)

tab1, tab2, tab3, tab4, tab5 = st.tabs(["績效比較", "歷次持股", "市場情境", "換股與成本", "方法說明"])

with tab1:
    st.plotly_chart(charts.nav_chart(res.returns, labels), width="stretch")
    tbl = format_table(res.perf)
    tbl["投組"] = tbl["投組"].map(lambda p: labels.get(p, p))
    st.dataframe(tbl, hide_index=True, width="stretch")
    st.download_button("下載績效表 CSV", to_csv_bytes(res.perf), "performance.csv", "text/csv")
    c1, c2 = st.columns(2)
    c1.plotly_chart(charts.risk_return_scatter(res.perf, labels), width="stretch")
    c2.plotly_chart(charts.drawdown_chart(res.returns, labels), width="stretch")
    if not res.risk_log.empty:
        st.plotly_chart(charts.exposure_chart(res.risk_log), width="stretch")
        st.caption("持股比例：加權指數在年線之上時 100%，跌破年線時 50%（其餘為現金）。")
    with st.expander("指標怎麼看"):
        st.markdown(
            f"- **年化報酬**：幾何年化，(1+累積報酬)^(252/天數) − 1\n"
            f"- **Sharpe**：(年化報酬 − 無風險利率 {config.RISK_FREE_RATE:.0%}) ÷ 年化波動，越高代表每承擔一單位風險換到越多報酬\n"
            "- **最大回撤**：從歷史高點（含起始淨值 1）跌下來的最大幅度，代表最糟情況\n"
            "- **Beta**：對加權指數的敏感度，1.2 代表大盤漲跌 1%、投組平均漲跌約 1.2%\n"
            f"- **詹森 Alpha**：年化報酬 −［無風險利率 {config.RISK_FREE_RATE:.0%} ＋ Beta ×（加權指數年化報酬 − 無風險利率）］，也就是扣掉「承擔大盤風險本來就該賺的」之後多賺的部分；正值代表選股真的有超額報酬\n"
            "- **日報酬平均／變異數**：平均數反映期望獲利，變異數反映單日漲跌的劇烈程度")
    st.download_button("下載每日報酬 CSV", to_csv_bytes(res.returns), "strategy_returns.csv", "text/csv")

with tab2:
    dates = sorted(res.holdings["date"].unique(), reverse=True)
    if not dates:
        st.info("沒有持股紀錄")
    else:
        d = st.selectbox("調倉日", dates, format_func=lambda x: pd.Timestamp(x).strftime("%Y-%m-%d"))
        cols = st.columns(len(STRATEGIES))
        for col, strat in zip(cols, STRATEGIES):
            with col:
                st.markdown(f"**{strat}**")
                sub = res.holdings[(res.holdings["date"] == d) & (res.holdings["portfolio"] == strat)]
                holdings_block(sub, names, strat, "該期空手（沒有可用分數）")
        st.download_button("下載全部持股紀錄 CSV", to_csv_bytes(res.holdings), "holdings.csv", "text/csv")

with tab3:
    r0, r1 = res.test_start, res.latest_date
    mid = r0 + (r1 - r0) / 2
    options = {"全部樣本外期間": (r0, r1), "前半段": (r0, mid), "後半段": (mid, r1), "自訂": None}
    choice = st.radio("期間", list(options), horizontal=True)
    if choice == "自訂":
        rng = st.date_input("選擇區間", value=(r0.date(), r1.date()), min_value=r0.date(), max_value=r1.date())
        if not isinstance(rng, (list, tuple)) or len(rng) < 2:
            st.info("請選擇結束日期")
            st.stop()
        a, b = pd.Timestamp(rng[0]), pd.Timestamp(rng[1])
    else:
        a, b = options[choice]
    sub = res.returns[(res.returns["date"] > a) & (res.returns["date"] <= b)]
    if sub.empty:
        st.info("這段期間沒有資料")
    else:
        st.plotly_chart(charts.nav_chart(sub, labels, f"{choice} 累積淨值"), width="stretch")
        t = format_table(performance_table(sub))
        t["投組"] = t["投組"].map(lambda p: labels.get(p, p))
        st.dataframe(t, hide_index=True, width="stretch")

with tab4:
    if res.trades.empty:
        st.info("沒有換股紀錄")
    else:
        summary = res.trades.groupby("portfolio").agg(換股次數=("turnover", "size"), 平均週轉率=("turnover", "mean"),
                                                      累計成本=("cost", "sum")).reindex(
            [s for s in STRATEGIES if s in set(res.trades["portfolio"])])
        st.dataframe(summary.style.format({"平均週轉率": "{:.1%}", "累計成本": "{:.2%}"}), width="stretch")
        st.caption("週轉率 = 換掉的部位比例（0% 完全沒換、100% 全部換掉）。成本已反映在淨值裡。")
        st.dataframe(res.trades.sort_values(["date", "portfolio"], ascending=[False, True])
                     .style.format({"turnover": "{:.1%}", "cost": "{:.3%}", "date": "{:%Y-%m-%d}"}),
                     hide_index=True, width="stretch")

with tab5:
    info = res.panel_info
    n_universe = ds.prices["ticker"].nunique() if not ds.prices.empty else 0
    feats = info["tech_features"] + info["fin_features"]
    rc = params.risk_control
    st.markdown(f"""
#### 流程
資料（股價、估值、ESG）→ 特徵工程 → AI 模型滾動訓練 → 三種策略選股 → 回測 → 與大盤／ETF 比較（含詹森 Alpha）

#### 預測目標（Y）
每檔股票從調倉日收盤起，未來 **{params.hold_days} 個交易日**的報酬，再減去同一天所有股票的平均（相對報酬）。
模型學的是「哪些股票會比別人好」，不是猜大盤漲跌。

#### 特徵（X）
{", ".join(feats)}（共 {len(feats)} 個）。**AI 模型不使用 ESG**，ESG 在選股階段才與 AI 分數融合。

#### 訓練方式：滾動式（walk-forward）
- 每 {config.RETRAIN_EVERY} 個月重新訓練一次，只用「在訓練當天已經知道結果」的樣本
  （樣本日期 ≤ 調倉日往前 {params.hold_days} 個交易日）；訓練樣本每 5 個交易日取一天。
- 缺值用訓練集的中位數補，不會用到測試期資訊。測試期（樣本外）從 {res.test_start:%Y-%m-%d} 開始。

#### 三種策略
1. **單純 AI**：模型預測分數最高的 {params.top_n} 檔。
2. **AI+ESG**：先排除爭議分數 > 3、EPS 為負的公司，混合分數 = {1 - params.esg_weight:.0%} × AI 排名 ＋ {params.esg_weight:.0%} × ESG 排名。
3. **單純 ESG**：同樣的排除條件後，ESG 總分最高的 {params.top_n} 檔。

#### 目標：最高報酬（不限制回撤）
預設設定以**報酬最大化**為唯一目標，不考慮最大回撤：
1. **股票池 {n_universe} 檔**：近 20 個交易日平均成交金額最大的上市櫃普通股（市值前 50 大一定納入），選擇範圍越大，模型越有機會挑到飆股。
2. **選前 {config.DEFAULT_TOP_N} 檔、等權**（預設）：永遠滿倉，不設停損、不因大盤轉弱減碼。
3. **怎麼選出這組設定**：用 300 檔股票池比較 Top N（5～30）、等權／集中加權，並用 3 組隨機種子重跑。
   等權 Top 15～30 的「單純 AI」年化報酬都在 100% 上下；集中加權反而只有約 85%（股票池大時，模型第 1 名的把握沒有比第 15 名高多少）。
   先前 50 檔股票池時也比較過模型（XGBoost、Ensemble 都比 Random Forest 差）與更長期的動能特徵（反而變差）。

代價：最大回撤約 −40%（2026 年 7 月急跌時），比大盤的 −29% 更深。

#### 風險控制（選用）{"　✅ 目前開啟" if rc else "　目前關閉"}
側邊欄勾選後會加上三條規則，可降低回撤，但報酬也會明顯變低：
1. **不買跌破年線的股票**：收盤價在 {config.STOCK_TREND_MA} 日均線之下就不買。
2. **不買最震盪的 20%**：近 60 日波動最高的 {1 - config.VOL_CAP_QUANTILE:.0%} 不買。
3. **大盤跌破年線持股減半**：加權指數在 {config.MARKET_MA} 日均線之下時，持股降為 {config.MARKET_WEAK_EXPOSURE:.0%}、其餘放現金。

#### 回測規則
- **每月**調倉（每個月最後一個交易日），以當天收盤價換股，報酬從**下一個交易日**開始計算。
- 持有期間權重隨股價漂移，{params.weighting}配置；未投入的部分為現金（報酬 0）。
- 交易成本：買進手續費 0.1425%、賣出手續費 0.1425% + 證交稅 0.3%，換股與調整持股比例都會扣。
- ESG 與估值資料一律依**公告日**對齊：某天只會用到當天以前已公告的資料
  {"（⚠️ 目前勾選了「用最新一期回填」，回測含前視偏差）" if params.static_esg else ""}。

#### 限制
- 股票池是用「最近」的成交金額挑出的目前上市櫃公司，存在存活者偏差與前視偏差（過去冷門、現在才熱門的股票也被納入）；以收盤價成交為假設，未考慮滑價。
- 回測期間只有約兩年半，而且是電子股大多頭；預設參數是在同一段期間比較後選出的，未來報酬很可能比回測低。
""")
