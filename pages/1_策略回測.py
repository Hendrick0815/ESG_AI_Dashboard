"""策略回測：績效比較、歷次持股、市場情境、換股成本、方法說明。"""
import pandas as pd
import streamlit as st

from src import config
from src.backtest import HARD_SCREENS, SCREEN_LABELS, SOFT_SCREENS, STRATEGIES
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
        st.caption("持股比例 = 合格股票占 Top N 名額的比例 ×（開啟波動控管時）回撤目標 ÷ 大盤年化波動。"
                   "大盤越震盪、合格股票越少，現金就越多。")
    with st.expander("指標怎麼看"):
        st.markdown(
            f"- **年化報酬**：幾何年化，(1+累積報酬)^(252/天數) − 1\n"
            f"- **Sharpe**：(年化報酬 − 無風險利率 {config.RISK_FREE_RATE:.0%}) ÷ 年化波動，越高代表每承擔一單位風險換到越多報酬\n"
            "- **最大回撤**：從歷史高點（含起始淨值 1）跌下來的最大幅度，代表最糟情況\n"
            "- **日報酬平均／變異數**：平均數反映期望獲利，變異數反映單日漲跌的劇烈程度")
    st.download_button("下載每日報酬 CSV", to_csv_bytes(res.returns), "strategy_returns.csv", "text/csv")

with tab2:
    dates = sorted(res.holdings["date"].unique(), reverse=True)
    if not dates:
        st.info("沒有持股紀錄")
    else:
        d = st.selectbox("調倉日", dates, format_func=lambda x: pd.Timestamp(x).strftime("%Y-%m-%d"))
        for row in range(0, len(STRATEGIES), 2):
            cols = st.columns(2)
            for col, strat in zip(cols, STRATEGIES[row:row + 2]):
                with col:
                    st.markdown(f"**{strat}**")
                    sub = res.holdings[(res.holdings["date"] == d) & (res.holdings["portfolio"] == strat)]
                    holdings_block(sub, names, strat, "該期空手（沒有符合條件的股票或沒有可用分數）")
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
    feats = info["tech_features"] + info.get("extra_features", []) + info["fin_features"]
    hard = "、".join(SCREEN_LABELS[c] for c in HARD_SCREENS if params.use_screen or c == "liquid")
    soft = "、".join(SCREEN_LABELS[c] for c in SOFT_SCREENS)
    st.markdown(f"""
#### 流程
資料（股價與成交量、估值、ESG、三大法人）→ 特徵工程 → 選股條件篩選 → AI 模型滾動訓練 → 四種策略排序
→ 依大盤波動決定持股比例 → 回測 → 與大盤／ETF 比較

#### 選股條件（每個調倉日先篩選，四種策略都只在合格名單裡挑）
- **硬性條件**（不符合就不能買）：{hard}。
- **加分條件**（技術選股的排序依據）：{soft}。
- 定義：
  - 均線全上：收盤價 ≥ 5、10、20、60 日均線，且 20 日與 60 日均線都比 5 天前高。
  - 區間整理：過去 {40} 個交易日（不含當天）的最高價 ÷ 最低價 − 1 ≤ {config.RANGE_MAX_WIDTH:.0%}。
  - 即將突破：整理區間內，收盤價距區間高點 {config.BREAKOUT_BAND:.0%} 以內，且突破幅度不超過 {config.BREAKOUT_MAX_ABOVE:.0%}（避免追高）。
  - 稍微出量：5 日均量 ÷ 20 日均量介於 {config.VOLUME_RATIO_MIN} ～ {config.VOLUME_RATIO_MAX} 倍（超過屬於爆量）。
  - 流動性：近 20 個交易日每天成交量 ≥ {config.MIN_DAILY_LOTS} 張。
  - 產業趨勢：股票池內同產業股票的等權指數在季線之上、且近 20 日上漲。
  - 法人買超：外資＋投信近 20 日買超股數 ÷ 同期成交量 > 0；證交所收盤後才公布，一律延後一天使用。
- 合格股票不足 {params.top_n} 檔時，空下的名額放現金，不會把錢集中到少數幾檔。

#### 預測目標（Y）
每檔股票從調倉日收盤起，未來 **{params.hold_days} 個交易日**的報酬，再減去同一天所有股票的平均（相對報酬）。

#### 特徵（X）
{", ".join(feats)}（共 {len(feats)} 個）。**AI 模型不使用 ESG**，ESG 在選股階段才與 AI 分數融合。

#### 訓練方式：滾動式（walk-forward）
- 每 {config.RETRAIN_EVERY} 個月重新訓練一次，只用「在訓練當天已經知道結果」的樣本
  （樣本日期 ≤ 調倉日往前 {params.hold_days} 個交易日）；訓練樣本每 5 個交易日取一天。
- 缺值用訓練集的中位數補，不會用到測試期資訊。測試期（樣本外）從 {res.test_start:%Y-%m-%d} 開始。

#### 四種策略（都先經過上面的選股條件）
1. **單純 AI**：合格名單中模型預測分數最高的 {params.top_n} 檔。
2. **AI+ESG**：再排除爭議分數 > 3、EPS 為負的公司，混合分數 = {1 - params.esg_weight:.0%} × AI 排名 ＋ {params.esg_weight:.0%} × ESG 排名。
3. **單純 ESG**：同樣的排除條件後，ESG 總分最高的 {params.top_n} 檔。
4. **技術選股**：不用 AI 與 ESG。分數 = 符合幾個加分條件（0～3）＋ 細部排序（區間越窄、越接近高點、法人買越多、產業越強越高）。

#### 風險控制（回撤目標 {params.max_dd:.0%}）{"" if params.risk_control else "　⚠️ 目前關閉，永遠滿倉"}
- 每天收盤計算大盤年化波動（近 20 日、近 60 日取較大者），持股比例 = min(100%, {params.max_dd:.0%} ÷ 大盤波動)，以 10% 為單位調整。
- 例：大盤年化波動 25% → 持股 40%；波動 10% 以下 → 滿倉。只調整比例，不在月中換股。
- 為什麼不用停損或「跌破季線就出場」：實測這兩種做法在 2024–2026 的震盪中反覆賣低買高，報酬大減、回撤卻沒有變小。
- 回撤目標是**設計目標，不是保證**：跳空大跌或波動突然放大時，實際回撤仍可能超過。

#### 回測規則
- **每月**調倉（每個月最後一個交易日），以當天收盤價換股，報酬從**下一個交易日**開始計算。
- 持有期間權重隨股價漂移，{params.weighting}配置；未投入的部分為現金（報酬 0）。
- 交易成本：買進手續費 0.1425%、賣出手續費 0.1425% + 證交稅 0.3%，換股與調整持股比例都會扣。
- ESG、估值、法人資料一律依**公告日**對齊：某天只會用到當天以前已公告的資料
  {"（⚠️ 目前勾選了「用最新一期回填」，回測含前視偏差）" if params.static_esg else ""}。

#### 限制
- 股票池為目前上市櫃的公司，存在存活者偏差；以收盤價成交為假設，未考慮滑價。
- 產業趨勢用股票池內的股票計算；市值前 50 大時有些產業只有 1～2 檔，股票池越大越準。
- 三大法人資料目前只有上市（證交所），上櫃股票沒有這項加分。
- 選股門檻（區間 25%、量比 1.1～2 倍等）是常見的技術分析設定，沒有針對這段回測期間最佳化；調整門檻去追求更好看的回測數字容易過度擬合。
""")
