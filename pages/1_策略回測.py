"""策略回測：績效比較（可選期間）、歷次持股、換股成本、方法說明。"""
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

tab1, tab2, tab4, tab5 = st.tabs(["績效比較", "歷次持股", "換股與成本", "方法說明"])

with tab1:
    r0, r1 = res.test_start, res.latest_date
    options = {"全部樣本外期間": (r0, r1)}
    for label, years in [("近 1 年", 1), ("近 3 年", 3), ("近 5 年", 5)]:
        a0 = r1 - pd.DateOffset(years=years)
        if a0 > r0:
            options[label] = (a0, r1)
    options["自訂"] = None
    p1, p2 = st.columns([5, 1])
    keys = list(options)
    choice = p1.radio("期間", keys, horizontal=True)
    log_y = p2.checkbox("對數刻度", value=False, help="期間很長、淨值差距很大時，對數刻度比較看得出每段期間的漲跌幅")
    if choice == "自訂":
        rng = st.date_input("選擇區間", value=(r0.date(), r1.date()), min_value=r0.date(), max_value=r1.date())
        if not isinstance(rng, (list, tuple)) or len(rng) < 2:
            st.info("請選擇結束日期")
            st.stop()
        a, b = pd.Timestamp(rng[0]), pd.Timestamp(rng[1])
    else:
        a, b = options[choice]
    full = choice == "全部樣本外期間"
    sub_ret = res.returns if full else res.returns[(res.returns["date"] > a) & (res.returns["date"] <= b)]
    if sub_ret.empty:
        st.info("這段期間沒有資料")
        st.stop()
    sub_perf = res.perf if full else performance_table(sub_ret)
    title = "全部樣本外期間 累積淨值" if full else f"累積淨值（{a:%Y-%m-%d} ～ {b:%Y-%m-%d}）"
    st.plotly_chart(charts.nav_chart(sub_ret, labels, title, log_y=log_y), width="stretch")
    tbl = format_table(sub_perf)
    tbl["投組"] = tbl["投組"].map(lambda p: labels.get(p, p))
    st.dataframe(tbl, hide_index=True, width="stretch")
    st.download_button("下載績效表 CSV", to_csv_bytes(sub_perf), "performance.csv", "text/csv")
    c1, c2 = st.columns(2)
    c1.plotly_chart(charts.risk_return_scatter(sub_perf, labels), width="stretch")
    c2.plotly_chart(charts.drawdown_chart(sub_ret, labels), width="stretch")
    if not res.risk_log.empty:
        rl = res.risk_log if full else res.risk_log[(res.risk_log["date"] > a) & (res.risk_log["date"] <= b)]
        if not rl.empty:
            st.plotly_chart(charts.exposure_chart(rl), width="stretch")
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
    from src.features import TECH_LABELS
    feats = list(res.importance["feature"]) if not res.importance.empty else info["tech_features"] + info["fin_features"]
    feat_text = "、".join(TECH_LABELS.get(f, f) for f in feats)
    rc = params.risk_control
    st.markdown(f"""
#### 流程
資料（股價、估值、ESG）→ 特徵工程 → AI 模型滾動訓練 → 三種策略選股 → 回測 → 與大盤／ETF 比較（含詹森 Alpha）

#### 預測目標（Y）
每檔股票從調倉日收盤起，未來 **{params.hold_days} 個交易日**的報酬，再減去同一天所有股票的平均（相對報酬）。
模型學的是「哪些股票會比別人好」，不是猜大盤漲跌。

#### 特徵（X）
{feat_text}（共 {len(feats)} 個）。**AI 模型不使用 ESG**，ESG 在選股階段才與 AI 分數融合。

其中「距 20 日最高價跌幅、距 20 日最高價天數、連續下跌天數、量能比、短期反轉」是**見頂訊號**，
用來區分「還在噴的飆股」和「已經從高點回落的飆股」。加入後「單純 AI」年化從約 100% 提高到約 106%（3 組隨機種子平均）。

#### 訓練方式：滾動式（walk-forward）
- 每 {config.RETRAIN_EVERY} 次調倉（約 {config.RETRAIN_EVERY * config.HOLD_DAYS} 個交易日）重新訓練一次，只用「在訓練當天已經知道結果」的樣本
  （樣本日期 ≤ 調倉日往前 {params.hold_days} 個交易日）；訓練樣本每 5 個交易日取一天。
- 缺值用訓練集的中位數補，不會用到測試期資訊。
- **訓練資料從 {config.HISTORY_START[:7]} 起；樣本外績效從 {res.test_start:%Y-%m-%d} 起**（TEJ ESG 評等第一次公告日），
  三個策略從同一天開始比較才公平。在那之前的資料只拿來訓練模型，不計入績效。

#### 三種策略
1. **單純 AI**：模型預測分數最高的 {params.top_n} 檔。
2. **AI+ESG**：先排除爭議分數 > 3、EPS 為負的公司，混合分數 = {1 - params.esg_weight:.0%} × AI 排名 ＋ {params.esg_weight:.0%} × ESG 排名。
3. **單純 ESG**：同樣的排除條件後，ESG 總分最高的 {params.top_n} 檔。

#### 目標：最高報酬（不限制回撤）
預設設定以**報酬最大化**為唯一目標，不考慮最大回撤：
1. **股票池 {n_universe} 檔**：近 20 個交易日平均成交金額最大的上市櫃普通股（市值前 50 大一定納入）。
2. **選前 {config.DEFAULT_TOP_N} 檔、等權**：永遠滿倉，不設停損、不因大盤轉弱減碼。
3. **每 {config.HOLD_DAYS} 個交易日調倉**，模型每 {config.RETRAIN_EVERY} 次調倉重新訓練一次。
4. **怎麼選出這組設定**：在近兩年半（300 檔）比較 Top N、等權／集中加權、調倉與重訓頻率；
   再用 2018 年底起約 8 年的回測比較特徵與產業的用法（期間較長、包含 2020 與 2022 年的大跌），各用 3 組隨機種子重跑，
   選平均最好、且不是只有單一參數特別好的組合。

#### 產業
- **同一產業最多 {config.MAX_PER_INDUSTRY} 檔**（{"開啟" if config.MAX_PER_INDUSTRY else "關閉"}）：分數高的股票若同產業已經有 {config.MAX_PER_INDUSTRY} 檔，就跳過、改選下一名。
  2018～2026 年的測試中報酬幾乎不變（約 106% → 105%），最大回撤從約 −47% 改善到約 −42%，避免全部押在同一個產業。
- 也試過另外兩種做法，**報酬都明顯變差，所以沒有採用**：
  把「產業近 1 月報酬、產業季線乖離、個股相對產業強弱」當成模型特徵（約 85%）；只買產業在季線之上的股票（約 78%）。
  原因是強勢股常常在產業轉強之前就先漲，等產業趨勢確認時已經太晚。

代價：持股集中在高波動股票，最大回撤約 −40%，比大盤深；調倉次數多，交易成本也較高（已反映在報酬裡）。

#### 風險控制（選用）{"　✅ 目前開啟" if rc else "　目前關閉"}
側邊欄勾選後會加上三條規則，可降低回撤，但報酬也會明顯變低：
1. **不買跌破年線的股票**：收盤價在 {config.STOCK_TREND_MA} 日均線之下就不買。
2. **不買最震盪的 20%**：近 60 日波動最高的 {1 - config.VOL_CAP_QUANTILE:.0%} 不買。
3. **大盤跌破年線持股減半**：加權指數在 {config.MARKET_MA} 日均線之下時，持股降為 {config.MARKET_WEAK_EXPOSURE:.0%}、其餘放現金。

#### 回測規則
- **每 {config.HOLD_DAYS} 個交易日**調倉一次，以當天收盤價換股，報酬從**下一個交易日**開始計算。
- 持有期間權重隨股價漂移，{params.weighting}配置；未投入的部分為現金（報酬 0）。
- 交易成本：買進手續費 0.1425%、賣出手續費 0.1425% + 證交稅 0.3%，換股與調整持股比例都會扣。
- ESG 與估值資料一律依**公告日**對齊：某天只會用到當天以前已公告的資料
  {"（⚠️ 目前勾選了「用最新一期回填」，回測含前視偏差）" if params.static_esg else ""}。

#### 限制
- 股票池是用「最近」的成交金額挑出的目前上市櫃公司，存在存活者偏差與前視偏差（過去冷門、現在才熱門的股票也被納入）；以收盤價成交為假設，未考慮滑價。
- 樣本外期間從 2022-11-01 起，主要是 AI／電子股大多頭；預設參數是在 2018 年起的期間比較後選出的，未來報酬很可能比回測低。
- 2017～2022 年的本益比／淨值比若還沒補齊，該期間以中位數代替（每日排程會自動補）。
""")
