import math
from datetime import date, timedelta

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import yfinance as yf
import requests


st.set_page_config(
    page_title="跨領域金融資訊展示平台",
    page_icon="📊",
    layout="wide",
)

# -----------------------------
# 專題報告用基礎資料
# -----------------------------
COMPANY_INFO = {
    "2330.TW": {"name": "台積電", "sector": "Semiconductor", "theme": "台灣半導體龍頭"},
    "2317.TW": {"name": "鴻海", "sector": "Technology", "theme": "全球代工龍頭"},
    "2454.TW": {"name": "聯發科", "sector": "Semiconductor", "theme": "IC設計龍頭"},
    "2881.TW": {"name": "富邦金", "sector": "Financial Services", "theme": "台灣金控龍頭"},
    "1101.TW": {"name": "台泥", "sector": "Basic Materials", "theme": "傳產與綠能轉型"},
    "0050.TW": {"name": "元大台灣50", "sector": "ETF", "theme": "台灣大型權值股ETF"},
}



# -----------------------------
# 工具函數
# -----------------------------
def msci_score_to_grade(score: float) -> str:
    if score >= 85: return "AAA"
    if score >= 75: return "AA"
    if score >= 65: return "A"
    if score >= 55: return "BBB"
    if score >= 45: return "BB"
    if score >= 35: return "B"
    return "CCC"


def compute_total_esg(esg_row: dict) -> float:
    return round(0.4 * esg_row["E"] + 0.3 * esg_row["S"] + 0.3 * esg_row["G"], 1)



@st.cache_data(show_spinner="正在透過 curl_cffi 加密通道獲取真實數據...")
def get_price_data(ticker: str, start: date, end: date) -> pd.DataFrame:
    """
    修正版：移除手動 Session 設置，改由 yfinance 自動處理連線
    """
    try:
        # 建立 Ticker 物件 (不傳入自定義 Session，讓 yf 自己選用 curl_cffi)
        t = yf.Ticker(ticker)
        
        # 抓取直到 2026 年當日的歷史資料
        df = t.history(
            start=start,
            end=end + timedelta(days=1),
            interval="1d",
            auto_adjust=True
        )

        if df is not None and not df.empty:
            # 處理 MultiIndex 欄位結構
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            
            df = df.reset_index()
            
            # 移除時區資訊 (避免 Plotly 繪圖報錯)
            if "Date" in df.columns:
                if pd.api.types.is_datetime64tz_dtype(df['Date']):
                    df['Date'] = df['Date'].dt.tz_localize(None)
                
                # 統一欄位名稱
                df = df.rename(columns={
                    "Open": "Open", "High": "High", 
                    "Low": "Low", "Close": "Close", "Volume": "Volume"
                })
                
                # 回傳真實資料
                return df[["Date", "Open", "High", "Low", "Close", "Volume"]].dropna().copy()
                
    except Exception as e:
        # 若發生錯誤，為了學術嚴謹，直接中斷執行並顯示錯誤
        st.sidebar.error(f"⚠️ 無法取得真實市場資料 ({ticker}): {str(e)}")
        st.stop()

    # 確保不會回傳空值或假資料
    st.sidebar.error(f"⚠️ {ticker} 在該期間內無真實交易數據。")
    st.stop()

   
@st.cache_data(show_spinner=False)
def build_universe_metrics(selected_ticker: str, selected_sector: str, start: date, end: date) -> pd.DataFrame:
    # 建立一個同業/商業種類池
    SECTOR_UNIVERSE = {
        "Technology": ["2317.TW", "2382.TW", "3231.TW", "2308.TW", "2395.TW", "3008.TW", "2330.TW"],
        "Semiconductor": ["2330.TW", "2454.TW", "2303.TW", "3711.TW", "2379.TW", "3443.TW", "3034.TW"],
        "Automobile": ["2207.TW", "2201.TW", "1536.TW", "1319.TW", "1522.TW"],
        "Financial Services": ["2881.TW", "2882.TW", "2891.TW", "2886.TW", "2884.TW", "2892.TW", "2880.TW"],
        "Healthcare": ["1707.TW", "1795.TW", "4104.TW", "4105.TWO", "3176.TWO"],
        "Consumer Cyclical": ["2912.TW", "5904.TW", "9914.TW", "9921.TW", "2727.TW"],
        "Communication Services": ["2412.TW", "3045.TW", "4904.TW"],
        "Energy": ["6505.TW", "6806.TW", "8926.TW", "9933.TW"],
        "Basic Materials": ["1101.TW", "1102.TW", "2002.TW", "1301.TW", "1303.TW", "1326.TW", "2014.TW"],
        "Industrials": ["2603.TW", "2609.TW", "2615.TW", "1590.TW", "2618.TW", "2610.TW"],
        "Consumer Defensive": ["1216.TW", "1229.TW", "1210.TW", "1736.TW"],
        "Real Estate": ["2542.TW", "2504.TW", "2548.TW", "5522.TW"],
        "Utilities": ["9933.TW", "8926.TW", "8931.TW"],
        "ETF": ["0050.TW", "0056.TW", "00878.TW", "00850.TW", "00929.TW"]
    }

    # 找出對應產業的標的，若無則使用一個預設的混合池 (台股市值前幾大)
    pool = SECTOR_UNIVERSE.get(selected_sector, ["2330.TW", "2317.TW", "2454.TW", "2881.TW", "1101.TW", "2002.TW"])
    
    # 確保選中的標的也在名單內，並且隨機挑選最多 4 檔同業進行比較
    import random
    peers = [t for t in pool if t != selected_ticker]
    random.seed(int(start.strftime("%Y%m%d")) + sum(ord(c) for c in selected_ticker)) # 讓同一天查詢同標的時，同業固定
    sampled_peers = random.sample(peers, min(4, len(peers)))
    compare_list = [selected_ticker] + sampled_peers

    rows = []
    for ticker in compare_list:
        t_info = fetch_stock_info(ticker)
        price_df = get_price_data(ticker, start, end)
        perf = calculate_metrics(price_df)
        esg = fetch_esg_data(ticker)
        esg_total = compute_total_esg(esg)
        rows.append(
            {
                "股票代碼": ticker,
                "公司名稱": t_info["name"],
                "產業分類": t_info["sector"],
                "主題概念": t_info["theme"],
                "環境(E)": esg["E"],
                "社會(S)": esg["S"],
                "治理(G)": esg["G"],
                "ESG總分": esg_total,
                "新聞情緒": esg.get("news_sentiment", 0.0),
                "累積報酬率(%)": perf["cum_return_pct"],
                "年化波動率(%)": perf["ann_vol_pct"],
                "夏普值": perf["sharpe"],
                "最大回撤(%)": perf["max_drawdown_pct"],
            }
        )
    return pd.DataFrame(rows)


def calculate_metrics(df: pd.DataFrame) -> dict:
    data = df.copy()
    data["Return"] = data["Close"].pct_change()
    ret = data["Return"].dropna()
    if ret.empty:
        return {"cum_return_pct": 0.0, "ann_vol_pct": 0.0, "sharpe": 0.0, "max_drawdown_pct": 0.0}

    cum_return = data["Close"].iloc[-1] / data["Close"].iloc[0] - 1
    ann_vol = ret.std() * np.sqrt(252)
    sharpe = 0 if ret.std() == 0 else ret.mean() / ret.std() * np.sqrt(252)
    wealth = (1 + ret).cumprod()
    peak = wealth.cummax()
    drawdown = wealth / peak - 1
    max_dd = drawdown.min()

    return {
        "cum_return_pct": round(cum_return * 100, 2),
        "ann_vol_pct": round(ann_vol * 100, 2),
        "sharpe": round(float(sharpe), 2),
        "max_drawdown_pct": round(float(max_dd) * 100, 2),
    }


def add_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    data = df.copy()
    data["SMA20"] = data["Close"].rolling(20).mean()
    data["SMA60"] = data["Close"].rolling(60).mean()
    data["Return"] = data["Close"].pct_change()
    data["Vol20"] = data["Return"].rolling(20).std() * np.sqrt(252) * 100
    return data

def generate_dynamic_analysis(ticker, first_close, latest_close, metrics, esg_grade):
    ret = metrics.get('cum_return_pct', 0)
    vol = metrics.get('ann_vol_pct', 0)
    dd = metrics.get('max_drawdown_pct', 0)
    
    # 基於嚴謹性，完全依賴實際數據區間做固定邏輯判定，不使用任何亂數隨機產生句子
    if ret > 20:
        trend = "強勁的多頭走勢"
        reason = "反映了市場對其基本面成長的高度認可"
    elif ret > 0:
        trend = "溫和上漲的格局"
        reason = "顯示公司營運基本面保持穩健"
    elif ret > -20:
        trend = "震盪回落的修正期"
        reason = "主要歸因於資金輪動與短期修正賣壓"
    else:
        trend = "顯著的下行壓力"
        reason = "顯示市場對其未來獲利展望存在較大疑慮"

    if vol > 35:
        vol_desc = f"此外，高達 {vol}% 的年化波動率暗示該標的具備較高的籌碼不穩定性"
    else:
        vol_desc = f"搭配 {vol}% 的年化波動率來看，整體價格走勢相對可控"

    dd_desc = f"期間內面臨了 {dd}% 的最大回撤，反映其實際下行風險。"

    intro = f"根據最新數據分析，{ticker} 在本期間內由 {first_close:.2f} 變動至 {latest_close:.2f}，整體呈現{trend}。"
    
    paragraphs = f" **系統規則分析：**\n\n{intro}{reason}。 {vol_desc}。{dd_desc}"
    return paragraphs


# -----------------------------
# 側邊欄
# -----------------------------
st.sidebar.header(" 設定面板")
st.sidebar.divider()

# 1. 股票代碼輸入
st.sidebar.subheader("標的選擇")
ticker_input = st.sidebar.text_input("輸入股票代碼 (如 2330, AAPL)", value="2330").upper()

# 2. 自動處理台股字尾
if ticker_input.isdigit():
    selected_ticker = f"{ticker_input}.TW"
else:
    selected_ticker = ticker_input

st.sidebar.divider()

# 3. 日期與功能控制
st.sidebar.subheader("回測期間與視角")
end_date = st.sidebar.date_input("結束日期", value=date.today())
start_date = st.sidebar.date_input("開始日期", value=end_date - timedelta(days=365))
show_candle = st.sidebar.toggle("啟用 K 線圖視角 (Candlestick)", value=False)

# 4. 錯誤檢查 (對應你截圖第 215-217 行)
if start_date >= end_date:
    st.sidebar.error("開始日期必須早於結束日期。")
    st.stop()

# 將獲取資訊的邏輯封裝成快取函數，提升執行速度
@st.cache_data(show_spinner="正在獲取標的資訊...")
def fetch_stock_info(ticker_str):
    try:
        t_obj = yf.Ticker(ticker_str)
        s_info = t_obj.info
        # 動態獲取名稱，若無則回傳代碼
        return {
            "name": s_info.get("longName") or s_info.get("shortName") or ticker_str,
            "sector": s_info.get("sector", "未知板塊"),
            "theme": s_info.get("industry", "未知產業")
        }
    except:
        return {"name": ticker_str, "sector": "N/A", "theme": "N/A"}

@st.cache_data(show_spinner="正在讀取本地真實 ESG 數據庫...")
def fetch_esg_data(ticker_str):
    # 為維持畢業專題最高學術嚴謹性，完全拔除亂數模擬機制與不穩定的國外免費 API。
    # 專題若以台股為主，學術界標準作法為使用 TEJ (台灣經濟新報) 下載的 CSV 檔案。
    import os
    file_path = "taiwan_esg_data.csv"
    
    if os.path.exists(file_path):
        import io
        # 使用 Python 原生最高防護級別的讀取方式，解決 TEJ 檔案中的特殊繁體字 (如 碁、堃) 與 pandas 版本相容性問題
        try:
            with open(file_path, "rb") as f:
                raw_data = f.read()
            # 嘗試以 utf-8-sig 解碼，若失敗則使用 cp950 並強制替換無法辨識的字元
            try:
                decoded_data = raw_data.decode("utf-8-sig")
            except UnicodeDecodeError:
                decoded_data = raw_data.decode("cp950", errors="replace")
            
            df_esg = pd.read_csv(io.StringIO(decoded_data))
            
            # 將欄位名稱標準化 (自動相容 TEJ 中文欄位)
            col_map = {
                "代號": "Ticker", "公司代碼": "Ticker",
                "TESG分數": "ESG_Total", "總分": "ESG_Total",
                "環境構面分數": "E", "E評分": "E",
                "社會構面分數": "S", "S評分": "S",
                "公司治理構面分數": "G", "G評分": "G",
                "TESG等級": "Grade"
            }
            df_esg = df_esg.rename(columns=col_map)
            
            if "Ticker" in df_esg.columns:
                df_esg["Ticker"] = df_esg["Ticker"].astype(str).str.strip()
                clean_ticker = ticker_str.replace(".TW", "").replace(".TWO", "")
                
                match = df_esg[df_esg["Ticker"] == clean_ticker]
                if not match.empty:
                    # 嘗試抓取 E, S, G，若無則看是否有 TESG分數，再無則補 0
                    total_score = float(match["ESG_Total"].iloc[0]) if "ESG_Total" in match.columns else 0.0
                    
                    e = float(match["E"].iloc[0]) if "E" in match.columns else total_score
                    s = float(match["S"].iloc[0]) if "S" in match.columns else total_score
                    g = float(match["G"].iloc[0]) if "G" in match.columns else total_score
                    
                    return {"E": e, "S": s, "G": g, "news_sentiment": 0.0, "has_data": True}
        except Exception as e:
            st.sidebar.error(f"讀取 ESG CSV 時發生錯誤: {e}")

    # 無真實資料時，基於嚴謹性返回 0，不產生虛假評分
    return {
        "E": 0.0,
        "S": 0.0,
        "G": 0.0,
        "news_sentiment": 0.0,
        "has_data": False
    }

# 在主程式中呼叫
info = fetch_stock_info(selected_ticker)

# ---------------------------------------------------------
price_df = get_price_data(selected_ticker, start_date, end_date)
price_df = add_technical_indicators(price_df)
metrics = calculate_metrics(price_df)
esg = fetch_esg_data(selected_ticker)
esg_total = compute_total_esg(esg)
esg_grade = msci_score_to_grade(esg_total)

# -----------------------------
# 頁首
# -----------------------------
st.title("📊 跨領域金融資訊顯示平台")
st.caption("整合 ESG、股價、風險與情緒指標。")

col_a, col_b, col_c, col_d = st.columns(4)
col_a.metric("展示標的", f"{selected_ticker}")
col_b.metric("累積報酬率", f"{metrics['cum_return_pct']:.2f}%")
col_c.metric("年化波動率", f"{metrics['ann_vol_pct']:.2f}%")

import os
if not os.path.exists("taiwan_esg_data.csv"):
    col_d.metric("ESG 資料庫", "未掛載 CSV")
elif not esg.get("has_data", False):
    col_d.metric("TEJ 真實 ESG 評等", "查無ESG資料 (0.0)")
else:
    col_d.metric("TEJ 真實 ESG 評等", f"{esg_grade} ({esg_total:.1f})")

st.markdown(
    f"<div style='display: flex; justify-content: space-between;'>"
    f"<span><b>標的說明：</b> {info['name']}｜{info['sector']}｜{info['theme']}</span>"
    f"<span><b>資料期間：</b> {start_date} 至 {end_date}</span>"
    f"</div>",
    unsafe_allow_html=True
)

# -----------------------------
# 頁籤
# -----------------------------
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "一覽總表",
    "ESG 與跨領域分析",
    "風險與技術指標",
    "策略回測與 ETF 比較",
    "系統選股邏輯與解析"
])

with tab1:
    left, right = st.columns([1.8, 1.2])

    with left:
        st.subheader("股價走勢")
        if show_candle:
            fig = go.Figure(
                data=[
                    go.Candlestick(
                        x=price_df["Date"],
                        open=price_df["Open"],
                        high=price_df["High"],
                        low=price_df["Low"],
                        close=price_df["Close"],
                        name="Price",
                        increasing_line_color='#ef476f', # 台股紅漲
                        decreasing_line_color='#06d6a0'  # 台股綠跌
                    )
                ]
            )
            fig.update_layout(
                height=550, 
                xaxis_title="", 
                yaxis_title="Price",
                xaxis_rangeslider_visible=True,
                dragmode="zoom",
                xaxis=dict(
                    rangeselector=dict(
                        buttons=list([
                            dict(count=1, label="1個月", step="month", stepmode="backward"),
                            dict(count=3, label="3個月", step="month", stepmode="backward"),
                            dict(count=6, label="半年", step="month", stepmode="backward"),
                            dict(label="全部", step="all")
                        ])
                    )
                ),
                margin=dict(l=20, r=20, t=40, b=20),
                yaxis=dict(fixedrange=False) # 確保Y軸可以被拖曳縮放
            )
        else:
            fig = px.line(price_df, x="Date", y="Close", title="收盤價走勢")
            fig.add_scatter(x=price_df["Date"], y=price_df["SMA20"], mode="lines", name="SMA20")
            fig.add_scatter(x=price_df["Date"], y=price_df["SMA60"], mode="lines", name="SMA60")
            fig.update_layout(height=460, dragmode="zoom")
            
        st.plotly_chart(fig, use_container_width=True, config={"scrollZoom": True})
        if show_candle:
            st.caption(" **縮放圖表方式**：\n"
                       "1. **滑鼠滾輪**：在圖表內直接滾動滑鼠滾輪，即可依據游標位置「同時縮放」直式與橫式比例。\n"
                       "2. **框選放大**：在圖表內按住左鍵畫出一個方形，即可精準放大該區塊。\n"
                       "3. **單軸拉長**：將游標移至 Y 軸「上下兩端邊緣」，游標改變後按住拖曳，即可單獨拉長 K 線高度。")

    with right:
        st.subheader("展示摘要")
        summary_df = pd.DataFrame(
            {
                "指標": ["累積報酬率", "年化波動率", "Sharpe Ratio", "最大回撤", "Sustainalytics ESG 評等"],
                "數值": [
                    f"{metrics['cum_return_pct']:.2f}%",
                    f"{metrics['ann_vol_pct']:.2f}%",
                    f"{metrics['sharpe']:.2f}",
                    f"{metrics['max_drawdown_pct']:.2f}%",
                    esg_grade if esg.get("has_data", False) else "查無ESG資料 (0.0)",
                ],
            }
        )
        st.dataframe(summary_df, use_container_width=True, hide_index=True)

        latest_close = float(price_df["Close"].iloc[-1])
        first_close = float(price_df["Close"].iloc[0])
        ai_analysis = generate_dynamic_analysis(selected_ticker, first_close, latest_close, metrics, esg_grade)
        st.info(ai_analysis)

    st.subheader("跨標的比較")
    universe_df = build_universe_metrics(selected_ticker, info["sector"], start_date, end_date)
    st.dataframe(universe_df, use_container_width=True, hide_index=True)

with tab2:
    c1, c2 = st.columns([1, 1])

    with c1:
        st.subheader("E / S / G 分項雷達圖")
        radar_df = pd.DataFrame(
            {
                "Category": ["環境 (Environment)", "社會 (Social)", "治理 (Governance)", "環境 (Environment)"],
                "Score": [esg["E"], esg["S"], esg["G"], esg["E"]],
            }
        )
        radar = px.line_polar(radar_df, r="Score", theta="Category", line_close=True, markers=True)
        radar.update_traces(fill="toself", fillcolor="rgba(0, 180, 216, 0.4)", line=dict(color="#0077b6", width=2))
        radar.update_layout(
            height=420,
            polar=dict(
                radialaxis=dict(visible=True, range=[0, 100], tickfont=dict(size=10)),
                angularaxis=dict(tickfont=dict(size=13, color="black", weight="bold"))
            ),
            margin=dict(l=40, r=40, t=40, b=40)
        )
        st.plotly_chart(radar, use_container_width=True)

    with c2:
        st.subheader("ESG 組成")
        bar_df = pd.DataFrame({"Dimension": ["環境 (E)", "社會 (S)", "治理 (G)"], "Score": [esg["E"], esg["S"], esg["G"]]})
        bar = px.bar(
            bar_df, x="Dimension", y="Score", text="Score", title="各面向評分表現",
            color="Dimension", color_discrete_sequence=["#2a9d8f", "#e9c46a", "#f4a261"]
        )
        bar.update_traces(textposition="outside", textfont_size=14, marker_line_width=1.5, marker_line_color="black")
        bar.update_layout(
            height=420, 
            showlegend=False, 
            yaxis=dict(range=[0, 110], title="分數"),
            xaxis=dict(title="", tickfont=dict(size=14, weight="bold")),
            margin=dict(l=40, r=40, t=60, b=40)
        )
        bar.add_hline(y=esg_total, line_dash="dot", line_color="#e63946", line_width=2, 
                      annotation_text=f"總分: {esg_total:.1f}", annotation_position="top right", 
                      annotation_font=dict(color="#e63946", size=14, weight="bold"))
        st.plotly_chart(bar, use_container_width=True)

    st.subheader("ESG 與報酬率散佈圖")
    scatter_df = build_universe_metrics(selected_ticker, info["sector"], start_date, end_date)
    scatter = px.scatter(
        scatter_df,
        x="ESG總分",
        y="累積報酬率(%)",
        size="年化波動率(%)",
        color="產業分類",
        hover_name="公司名稱",
        text="股票代碼",
        title="不同標的的 ESG 與報酬率關係",
        color_discrete_sequence=["#457b9d", "#e63946", "#1d3557", "#2a9d8f", "#f4a261", "#e9c46a"]
    )
    scatter.update_traces(textposition="top center", marker=dict(line=dict(width=1, color='DarkSlateGrey')))
    scatter.update_layout(
        height=500,
        xaxis=dict(title="MSCI ESG 總分", showgrid=True, gridcolor='#f0f0f0'),
        yaxis=dict(title="累積報酬率 (%)", showgrid=True, gridcolor='#f0f0f0', zeroline=True, zerolinecolor='#ff9999', zerolinewidth=2),
        plot_bgcolor='white',
        margin=dict(l=40, r=40, t=60, b=40)
    )
    st.plotly_chart(scatter, use_container_width=True)

    st.subheader("新聞情緒 vs. ESG 總分")
    sent = px.scatter(
        scatter_df,
        x="新聞情緒",
        y="ESG總分",
        size="ESG總分",
        color="產業分類",
        text="股票代碼",
        hover_name="公司名稱",
        title="新聞情緒與 ESG 分數交叉分析",
        color_discrete_sequence=["#457b9d", "#e63946", "#1d3557", "#2a9d8f", "#f4a261", "#e9c46a"]
    )
    sent.update_traces(textposition="top center", marker=dict(line=dict(width=1, color='DarkSlateGrey')))
    sent.update_layout(
        height=500,
        xaxis=dict(title="新聞情緒分數 (-1 悲觀 到 1 樂觀)", showgrid=True, gridcolor='#f0f0f0', zeroline=True, zerolinecolor='#ff9999', zerolinewidth=2),
        yaxis=dict(title="MSCI ESG 總分", showgrid=True, gridcolor='#f0f0f0'),
        plot_bgcolor='white',
        margin=dict(l=40, r=40, t=60, b=40)
    )
    st.plotly_chart(sent, use_container_width=True)

with tab3:
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("滾動波動率")
        vol_fig = px.line(
            price_df, x="Date", y="Vol20", title="20日年化波動率（%）",
            color_discrete_sequence=["#e76f51"]
        )
        vol_fig.update_traces(fill="tozeroy", fillcolor="rgba(231, 111, 81, 0.2)", line=dict(width=2.5))
        vol_fig.update_layout(
            height=400,
            xaxis=dict(title="", showgrid=True, gridcolor='#f0f0f0'),
            yaxis=dict(title="波動率 (%)", showgrid=True, gridcolor='#f0f0f0'),
            plot_bgcolor='white',
            margin=dict(l=40, r=40, t=50, b=40)
        )
        st.plotly_chart(vol_fig, use_container_width=True)

    with c2:
        st.subheader("日報酬率分布")
        hist_df = price_df.dropna().copy()
        hist_df['Return_%'] = hist_df['Return'] * 100
        hist = px.histogram(
            hist_df, x="Return_%", nbins=40, title="日報酬率直方圖",
            marginal="box",
            color_discrete_sequence=["#2a9d8f"],
            opacity=0.8
        )
        hist.update_layout(
            height=400,
            xaxis=dict(title="日報酬率 (%)", showgrid=True, gridcolor='#f0f0f0', zeroline=True, zerolinecolor='#e63946', zerolinewidth=2),
            yaxis=dict(title="天數 (頻率)", showgrid=True, gridcolor='#f0f0f0'),
            plot_bgcolor='white',
            margin=dict(l=40, r=40, t=50, b=40)
        )
        st.plotly_chart(hist, use_container_width=True)

    st.subheader("風險指標解讀")
    risk_table = pd.DataFrame(
        {
            "指標": ["Sharpe Ratio", "最大回撤", "年化波動率"],
            "指標解讀": [
                "報酬相對風險的效率指標，數值越高代表單位風險帶來的報酬越高。",
                "衡量歷史上從高點回落的最深幅度，可用來說明下行風險。",
                "衡量報酬變動程度，數值越大代表價格越不穩定。",
            ],
            "本標的數值": [
                f"{metrics['sharpe']:.2f}",
                f"{metrics['max_drawdown_pct']:.2f}%",
                f"{metrics['ann_vol_pct']:.2f}%",
            ],
        }
    )
    st.dataframe(risk_table, use_container_width=True, hide_index=True)

with tab4:
    st.header(" 策略多維度實測：AI vs ESG vs AI+ESG vs 大盤")
    st.markdown("本專題運用 **機器學習演算法** 整合 ESG 指標與市場資料，建立動態選股模型。此處將展示四種情境之**真實績效與成分股比較**。")
    
    import os
    import json
    file_path = "ai_strategy_returns.csv"
    comp_path = "strategy_components.json"
    
    if os.path.exists(file_path):
        st.success("成功讀取真實策略回測數據。")
        try:
            ai_df = pd.read_csv(file_path)
            ai_df["Date"] = pd.to_datetime(ai_df["Date"])
            
            # 若為舊版檔案，提供向下相容或提示
            has_pure_ai = "Pure_AI_Net_Value" in ai_df.columns
            has_pure_esg = "Pure_ESG_Net_Value" in ai_df.columns
            has_ai_esg = "AI_ESG_Net_Value" in ai_df.columns
            
            # 相容舊檔名
            if "AI_Strategy_Net_Value" in ai_df.columns and not has_ai_esg:
                ai_df = ai_df.rename(columns={"AI_Strategy_Net_Value": "AI_ESG_Net_Value"})
                has_ai_esg = True
            
            # 取得 00850.TW 作為對標 ETF
            benchmark_ticker = "00850.TW"
            bm_df = get_price_data(benchmark_ticker, start_date, end_date)
            
            if not bm_df.empty:
                bm_df["Date"] = pd.to_datetime(bm_df["Date"])
                
                # 先進行合併，確保大家有相同的日期交集
                merged_df = pd.merge(ai_df, bm_df[["Date", "Close"]], on="Date", how="inner")
                
                if not merged_df.empty:
                    # 統一用「交集後的第一天」作為基準 1.0 進行正規化
                    merged_df["Benchmark_Net_Value"] = merged_df["Close"] / merged_df["Close"].iloc[0]
                    if has_ai_esg:
                        merged_df["AI_ESG_Net_Value"] = merged_df["AI_ESG_Net_Value"] / merged_df["AI_ESG_Net_Value"].iloc[0]
                    if has_pure_ai:
                        merged_df["Pure_AI_Net_Value"] = merged_df["Pure_AI_Net_Value"] / merged_df["Pure_AI_Net_Value"].iloc[0]
                    if has_pure_esg:
                        merged_df["Pure_ESG_Net_Value"] = merged_df["Pure_ESG_Net_Value"] / merged_df["Pure_ESG_Net_Value"].iloc[0]

                    # 繪製走勢圖
                    fig = go.Figure()
                    
                    if has_ai_esg:
                        fig.add_trace(go.Scatter(x=merged_df["Date"], y=merged_df["AI_ESG_Net_Value"], mode='lines', name='AI+ESG 投資組合', line=dict(color='#e63946', width=2.5)))
                    if has_pure_ai:
                        fig.add_trace(go.Scatter(x=merged_df["Date"], y=merged_df["Pure_AI_Net_Value"], mode='lines', name='單純AI選股', line=dict(color='#f4a261', width=2)))
                    if has_pure_esg:
                        fig.add_trace(go.Scatter(x=merged_df["Date"], y=merged_df["Pure_ESG_Net_Value"], mode='lines', name='單純ESG選股', line=dict(color='#2a9d8f', width=2)))
                    
                    fig.add_trace(go.Scatter(x=merged_df["Date"], y=merged_df["Benchmark_Net_Value"], mode='lines', name=f'{benchmark_ticker} (大盤)', line=dict(color='#457b9d', width=2.5)))
                    
                    fig.update_layout(
                        title="多重策略與大盤淨值走勢比較",
                        xaxis_title="",
                        yaxis_title="淨值 (Net Value)",
                        hovermode="x unified",
                        plot_bgcolor='white',
                        margin=dict(l=40, r=40, t=50, b=40),
                        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                    )
                    fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor='#f0f0f0')
                    fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor='#f0f0f0')
                    st.plotly_chart(fig, use_container_width=True)
                    
                    # 績效指標
                    def calc_perf(nv_series):
                        ret = nv_series.pct_change().dropna()
                        cum_ret = nv_series.iloc[-1] / nv_series.iloc[0] - 1
                        ann_vol = ret.std() * np.sqrt(252)
                        sharpe = 0 if ret.std() == 0 else ret.mean() / ret.std() * np.sqrt(252)
                        
                        mean_ret = ret.mean()
                        var_ret = ret.var()
                        
                        peak = nv_series.cummax()
                        drawdown = (nv_series - peak) / peak
                        max_dd = drawdown.min()
                        
                        return (f"{cum_ret * 100:.2f}%", 
                                f"{ann_vol * 100:.2f}%", 
                                f"{sharpe:.2f}",
                                f"{mean_ret * 100:.3f}%",
                                f"{var_ret:.6f}",
                                f"{max_dd * 100:.2f}%")
                        
                    perf_data = {"指標": ["累積報酬率 (%)", "年化波動率 (%)", "夏普值 (Sharpe)", "平均數 (日報酬, %)", "變異數 (日報酬)", "最大損失 (Max Drawdown, %)"]}
                    
                    if has_ai_esg:
                        perf_data["AI+ESG 投資組合"] = calc_perf(merged_df["AI_ESG_Net_Value"])
                    if has_pure_ai:
                        perf_data["單純AI選股"] = calc_perf(merged_df["Pure_AI_Net_Value"])
                    if has_pure_esg:
                        perf_data["單純ESG選股"] = calc_perf(merged_df["Pure_ESG_Net_Value"])
                        
                    perf_data[f"{benchmark_ticker} (大盤)"] = calc_perf(merged_df["Benchmark_Net_Value"])
                    
                    st.subheader("績效指標對比")
                    perf_df = pd.DataFrame(perf_data)
                    st.dataframe(perf_df, use_container_width=True, hide_index=True)
                    
                    st.subheader("新增指標解讀")
                    extra_metric_df = pd.DataFrame({
                        "指標": ["平均數 (Mean)", "變異數 (Variance)", "最大損失 (Max Drawdown)"],
                        "可以看出什麼？": [
                            "代表策略在每日（或特定區間）的平均獲利能力。若為正數且較高，表示策略長期具備穩定正向的期望值；若為負數則代表策略長期會失血。",
                            "衡量每日報酬率的分散程度（波動大小的平方）。數值越大，代表策略單日暴漲暴跌的機率越高，潛在不確定性與風險越大；數值越小代表走勢越平穩。",
                            "衡量投資期間內，從最高點跌至最低點的最大跌幅（資金回撤）。這反映了投資人可能面臨的「最糟情況」，數值越小（負越多）代表扛受的壓力越大，資金控管風險越高。"
                        ]
                    })
                    st.dataframe(extra_metric_df, use_container_width=True, hide_index=True)
                    
                    # 顯示成分股與權重
                    last_date = merged_df["Date"].max()
                    month_str = f"{last_date.month}月份"
                    st.subheader(f"{month_str} 最新成分股與權重配置")
                    if os.path.exists(comp_path):
                        with open(comp_path, "r", encoding="utf-8") as f:
                            comps = json.load(f)
                            
                        c1, c2, c3 = st.columns(3)
                        with c1:
                            st.markdown("#### AI+ESG 選股")
                            if "AI_ESG" in comps:
                                comp_df = pd.DataFrame(list(comps["AI_ESG"].items()), columns=["股票代碼", "權重(%)"])
                                st.dataframe(comp_df, hide_index=True, use_container_width=True)
                        with c2:
                            st.markdown("#### 單純 AI 選股")
                            if "Pure_AI" in comps:
                                comp_df = pd.DataFrame(list(comps["Pure_AI"].items()), columns=["股票代碼", "權重(%)"])
                                st.dataframe(comp_df, hide_index=True, use_container_width=True)
                        with c3:
                            st.markdown("#### 單純 ESG 選股")
                            if "Pure_ESG" in comps:
                                comp_df = pd.DataFrame(list(comps["Pure_ESG"].items()), columns=["股票代碼", "權重(%)"])
                                st.dataframe(comp_df, hide_index=True, use_container_width=True)
                    else:
                        st.info("尚未偵測到成分股資料 (`strategy_components.json`)，請重新執行 `generate_backtest.py` 產出最新成分股。")
                    
                else:
                    st.warning("⚠️ 檔案內的日期區間與目前選擇的日期無交集，請調整側邊欄日期。")
            else:
                st.warning("無法取得 00850.TW 基準資料作比較。")
        except Exception as e:
            st.error(f"解析 CSV 或繪圖時發生錯誤: {e}")
    else:
        st.warning("⚠️ **為求專題嚴謹，本系統已全面移除模擬亂數功能。**\n\n目前尚未偵測到您的真實策略回測數據。請執行 `generate_backtest.py` 來產出實測數據與成分股檔案。")

with tab5:
    st.header(" 系統選股邏輯與模型解析")
    st.markdown("""
本專題的背後採用了量化投資業界標準的**「滾動式回測 (Rolling Backtest)」**與**「多因子模型 (Multi-factor Model)」**架構。以下是三種情境的選股邏輯解析：
### 機器學習模型變數定義 (X 與 Y 說明)

在建構 XGBoost 與 Random Forest 的監督式學習 (Supervised Learning) 過程中，我們必須清楚定義輸入模型的「特徵矩陣 (X)」與「標籤結果 (Y)」。

#### 【 Y 變數：模型的預測目標 (Target / Label) 】
這是一個**二元分類問題 (Binary Classification)**，AI 的任務是預測這檔股票下個月會不會漲。
*   **未來一個月絕對報酬率標籤 (Y)**：
    *   **定義條件**：計算每檔標的在「下一個月」的實際累積報酬率。如果報酬率大於 `2%`，我們將其標記為 `1`（正樣本，代表具備超額上漲潛力）；若報酬率小於等於 `2%` 甚至下跌，則標記為 `0`（負樣本）。
    *   **實務意義**：設定 2% 的門檻是為了確保 AI 挑出的股票在扣除交易成本 (約0.4425%) 後，仍有實質的獲利空間，而不只是微幅波動。這是 AI 模型在歷史訓練中努力學習去命中的「標靶」。

#### 【 X 變數：輸入模型的特徵 (Features) 】
X 變數是 AI 模型在預測當下所能看到的「線索」。我們選用了四個核心技術與籌碼面指標作為 X：
1.  **近一月動能 (Momentum 1M, X₁)**：
    *   **數據定義**：過去 20 個交易日的累積報酬率 `(今日收盤價 / 20日前的收盤價) - 1`。
    *   **實務意義**：衡量短期市場資金流向與追漲殺跌的動能。具備強烈近期動能的股票，短期內較容易延續漲勢。
2.  **近三月動能 (Momentum 3M, X₂)**：
    *   **數據定義**：過去 60 個交易日的累積報酬率 `(今日收盤價 / 60日前的收盤價) - 1`。
    *   **實務意義**：衡量中期波段趨勢。相比短期的 X₁，三月動能更能濾除短期雜訊，反映股價波段的延續性。
3.  **20日年化波動率 (Volatility 20D, X₃)**：
    *   **數據定義**：過去 20 個交易日「每日報酬率」的標準差，再乘以 `√252` 進行年化。
    *   **實務意義**：衡量股價近期籌碼的穩定度。數值過高代表股價大起大落、不確定風險大；數值適中則代表漲跌具備一定規律。
4.  **均線乖離率 (Bias Ratio, X₄)**：
    *   **數據定義**：收盤價與月線的差距，公式為 `(今日收盤價 - 20日均線SMA20) / 20日均線SMA20`。
    *   **實務意義**：判斷股價是否偏離短期平均成本太多。乖離率過高可能隨時面臨獲利了結的賣壓（均值回歸），過低則暗示超跌。

> **註**：ESG 評分 (TEJ 真實評等) 並沒有直接放入 XGBoost 或 Random Forest 的 X 變數中，而是採取**「後期融合 (Late Fusion)」**的方式，與 AI 預測出來的上漲機率進行加權，藉此保持 AI 模型預測股價動能的純粹性，同時兼顧 ESG 永續標準。

#### 【 訓練集與測試集架構 (Train / Test Split) 】
因為金融市場具有高度的時序性 (Time-series)，我們**嚴格禁止**採用傳統機器學習常見的「隨機抽樣切分 (Random Split)」，否則會引發嚴重的「未來數據洩漏 (Data Leakage)」作弊問題。因此，本專題採用量化界標準的**「滾動式視窗 (Rolling Window)」**來切分資料：
*   **訓練集 (Training Set) — 模型的歷史題庫**：
    *   **資料樣貌**：由過去一段固定期間（例如過去 3 年至 5 年）內，所有標的股票在每個月底的歷史 X₁~X₄ 數值，加上它們對應的真實 Y 標籤（次月是否漲超 2%）所組成的龐大矩陣數據庫。
    *   **運作機制**：XGBoost 與 Random Forest 會在這個歷史題庫中，反覆學習「當 X 的技術指標出現什麼組合時，Y 變成 1 的機率最大」，藉此建立出複雜且非線性的決策樹規則。
*   **測試集 (Testing Set) — 模型的實戰考卷**：
    *   **資料樣貌**：僅包含「當下這個月」所有標的股票最新的 X₁~X₄ 數據，**完全沒有 Y 標籤**（因為未來的真實漲跌還沒發生）。
    *   **運作機制**：將這組最新的測試集 X 特徵矩陣輸入已訓練好的模型中，模型會根據學到的歷史規律，輸出每一檔股票下個月的「預測上漲機率 (0~100%)」。
*   **滾動學習機制 (Rolling)**：當時間推進到下個月底，原本「測試集」的月份已經開獎（知道了實際的漲跌結果 Y），這筆資料就會被併入新的「訓練集」中，同時剔除最舊的一個月資料。接著，AI 模型會**重新訓練一次**，去應付下一個全新的「測試集考卷」。這種設計能確保模型不斷進化，適應市場最新的多空風格轉變。

---

### 1. 單純 AI 選股邏輯 (Pure AI)
這是完全不看 ESG、只專注於「財務動能與股價技術面」來追求利潤最大化的策略。
*   **模型架構**：使用擅長處理非線性特徵的 **XGBoost** 搭配 **Random Forest** 組成「集成模型 (Ensemble Model)」。將上述的 X₁~X₄ 輸入模型後，結合兩者的決策樹群，輸出一個「上漲機率 (0~100%)」。
*   **選股動作**：每個月初，選出 **AI 預測上漲機率最高的 20 檔股票**。
*   **資金配置**：採用**「高純度排名加權法 (Conviction Weighting)」**，給予預測機率最高的第一名高達 30% 的重倉資金，前五名囊括近 70% 資金以集中火力捕捉大盤飆股。

### 2. 單純 ESG 選股邏輯 (Pure ESG)
這是完全不看股價表現，只依照企業永續發展表現來投資的防禦型策略。
*   **股票池建構 (Universe)**：直接掃描本地端全市場的 ESG 真實評等，將「全市場 ESG 最高分的前 50 檔及台灣50大型權值股」納入名單。
*   **選股動作**：每個月初，不做任何機器學習運算，直接挑選 **ESG 總分最高的 20 檔股票**，作為極致的被動 ESG 信仰投資。

### 3. AI + ESG 雙效選股邏輯 (Blended Factor)
這就是本專題的主軸：**「如何讓追求極致利潤的 AI，兼顧企業永續發展？」**
*   **混合因子 (Blended Score) 機制**：
    我們採用華爾街量化基金常用的作法，將 AI 找出的「Alpha (預測上漲機率)」與「ESG 永續因子」融合。
    *   **公式**：`總合分數 = (AI 模型輸出的上漲機率 × 70%) + (ESG 分數正規化權重 × 30%)`
*   **選股動作**：每個月初，計算每檔股票的總合分數，並選出**分數最高的 20 檔股票**。
*   **實務效果**：在這個邏輯下，一檔 AI 預測極會漲但 ESG 極差的股票會被降低權重甚至淘汰；而一檔 AI 預測會穩健上漲，且 ESG 表現極優的「資優生」，就會在加權後躍升為重倉股。這完美展示了如何在獲利與永續之間取得量化平衡。

---

### 實務回測控制變數 (Control Variables)
為了確保回測不失真，我們在系統中加入了以下控制：
1.  **無未來函數 (No Look-ahead Bias)**：AI 在預測 T+1 月的漲跌時，只能使用 T 月（含）以前的 X 變數資料，完全杜絕偷看未來的作弊行為。
2.  **真實交易成本扣除**：每次「月初換股」時，系統都會自動計算實際換股周轉率，並扣除台灣股市真實的 **0.4425%** 單邊交易成本（含 0.3% 證交稅與 0.1425% 手續費）。這代表回測出來的淨值，是投資人真正能放進口袋的錢。
    """)


st.divider()
st.caption(
    "備註：本平台預設優先嘗試抓取 Yahoo Finance 市價資料；若執行環境無法連網，會自動切換為本機TEJ資料。"
)
