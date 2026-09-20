import time
import random
import io
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd
import plotly.express as px
import requests
import streamlit as st

# Optional ML imports
try:
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.metrics import mean_squared_error
    SKLEARN_AVAILABLE = True
except Exception:
    SKLEARN_AVAILABLE = False

try:
    import xgboost as xgb
    XGBOOST_AVAILABLE = True
except Exception:
    XGBOOST_AVAILABLE = False

try:
    import shap
    SHAP_AVAILABLE = True
except Exception:
    SHAP_AVAILABLE = False

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except Exception:
    YFINANCE_AVAILABLE = False


# ------------------------------------------------------------
# Page config
# ------------------------------------------------------------
st.set_page_config(
    page_title="ESG-AI Smart Portfolio Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ------------------------------------------------------------
# Constants
# ------------------------------------------------------------
DATA_DIR = Path("data")
STOCK_PRICE_FILE = DATA_DIR / "stock_price.csv"
ESG_FILE = DATA_DIR / "esg_scores.csv"
FINANCIAL_FILE = DATA_DIR / "financials.csv"
ETF_FILE = DATA_DIR / "etf_prices.csv"

DEFAULT_TOP_N = 10
DEFAULT_RF_TREES = 200
TRADING_DAYS = 252
RISK_FREE_RATE = 0.01
DEFAULT_ETFS = ["^TWII", "0050.TW", "0056.TW", "00878.TW"]
# ^TWII = 台灣加權指數（大盤）；0050 = 台灣50；00878 = 國泰永續高股息


# 本月份（9月）預設設定
CURRENT_MONTH = "2026年9月"
DEFAULT_START_DATE = "2026-09-01"
DEFAULT_END_DATE = pd.Timestamp.today().strftime("%Y-%m-%d")

# ------------------------------------------------------------
# 台灣股票代碼 → 中文公司名稱對照表
# ------------------------------------------------------------
COMPANY_NAMES = {
    # 半導體
    "2330.TW": "台積電",
    "2303.TW": "聯電",
    "2454.TW": "聯發科",
    "3711.TW": "日月光投控",
    "2379.TW": "瑞昱",
    "3034.TW": "聯詠",
    "2344.TW": "華邦電",
    "2408.TW": "南亞科",
    "3037.TW": "欣興",
    "2383.TW": "台光電",
    # 電子/科技
    "2317.TW": "鴻海",
    "2308.TW": "台達電",
    "2382.TW": "廣達",
    "2357.TW": "華碩",
    "2345.TW": "智邦",
    "2395.TW": "研華",
    "2395.TW": "研華",
    "2457.TW": "飛宏",
    "2409.TW": "友達",
    "2412.TW": "中華電",
    "2356.TW": "英業達",
    "2439.TW": "美律",
    "2327.TW": "國巨",
    "3702.TW": "大聯大",
    "2409.TW": "友達",
    "6669.TW": "緯穎",
    "2337.TW": "旺宏",
    "3231.TW": "緯創",
    "2301.TW": "光寶科",
    "2474.TW": "可成",
    "2353.TW": "宏碁",
    "2354.TW": "鴻準",
    # 金融
    "2881.TW": "富邦金",
    "2882.TW": "國泰金",
    "2886.TW": "兆豐金",
    "2891.TW": "中信金",
    "2884.TW": "玉山金",
    "2880.TW": "華南金",
    "2883.TW": "開發金",
    "2885.TW": "元大金",
    "2887.TW": "台新金",
    "2888.TW": "新光金",
    "2889.TW": "國票金",
    "2890.TW": "永豐金",
    "2892.TW": "第一金",
    "5880.TW": "合庫金",
    # 電信
    "4904.TW": "遠傳",
    "4938.TW": "和碩",
    # 傳產/其他
    "1301.TW": "台塑",
    "1303.TW": "南亞",
    "1326.TW": "台化",
    "2002.TW": "中鋼",
    "1402.TW": "遠東新",
    "2912.TW": "統一超",
    "2207.TW": "和泰車",
    "9940.TW": "信義房屋",
    "9933.TW": "中鼎",
    "8215.TW": "明基材",
    "1227.TW": "佳格",
    "2330.TW": "台積電",
    "2886.TW": "兆豐金",
}


def get_company_name(ticker: str) -> str:
    """回傳股票的中文公司名稱，找不到則回傳空字串"""
    return COMPANY_NAMES.get(str(ticker).strip().upper(), "")


def ticker_display(ticker: str) -> str:
    """回傳 '2330.TW　台積電' 格式字串（用於顯示）"""
    name = get_company_name(ticker)
    return f"{ticker}　{name}" if name else ticker


# ------------------------------------------------------------
# 自動抓取 00850 ESG ETF 成分股
# ------------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_00850_constituents() -> List[str]:
    """
    抓取 00850（元大台灣ESG永續）最新成分股 ticker 清單。
    依序嘗試三種方法：
      1. TWSE OpenAPI ESG 揭露資料（有揭露 ESG 的上市公司作為候選母池）
      2. WantGoo 持股清單爬蟲
      3. 備用硬編碼清單（2026/09 依市值排序前30大）
    """
    import re as _re
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Referer": "https://www.twse.com.tw/",
    }

    # ── 方法 1：TWSE OpenAPI — ESG 揭露公司清單（溫室氣體議題）──────────
    try:
        url1 = "https://openapi.twse.com.tw/v1/opendata/t187ap46_L_1"
        resp1 = requests.get(url1, headers=headers, timeout=12)
        if resp1.status_code == 200:
            data1 = resp1.json()
            if data1:
                df_esg = pd.DataFrame(data1)
                # 找代碼欄（可能叫 'Code', '公司代號', '股票代號' 等）
                code_col = next(
                    (c for c in df_esg.columns if any(k in c for k in ["Code", "代號", "代碼", "股票"])),
                    None
                )
                if code_col:
                    codes = df_esg[code_col].astype(str).str.strip()
                    tickers = [f"{c}.TW" for c in codes if _re.match(r"^\d{4}$", c)]
                    if len(tickers) >= 10:
                        return tickers
    except Exception:
        pass

    # ── 方法 2：WantGoo 爬蟲 — 00850 持股清單 ────────────────────────────
    try:
        from bs4 import BeautifulSoup
        url2 = "https://www.wantgoo.com/stock/etf/00850/top-holdings"
        hdrs2 = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "zh-TW,zh;q=0.9",
        }
        resp2 = requests.get(url2, headers=hdrs2, timeout=15)
        resp2.raise_for_status()
        soup = BeautifulSoup(resp2.text, "html.parser")
        links = soup.find_all("a", href=_re.compile(r"/stock/\d{4,6}"))
        tickers = []
        for link in links:
            m = _re.search(r"/stock/(\d{4,6})", link["href"])
            if m:
                tickers.append(f"{m.group(1)}.TW")
        tickers = list(dict.fromkeys(tickers))  # 去重保序
        if len(tickers) >= 5:
            return tickers
    except Exception:
        pass

    # ── 方法 3：備用硬編碼（2026/09 依市值排序前30大 00850 成分股）────────
    return [
        "2330.TW",  # 台積電
        "2454.TW",  # 聯發科
        "2308.TW",  # 台達電
        "2317.TW",  # 鴻海
        "3711.TW",  # 日月光投控
        "2303.TW",  # 聯電
        "2383.TW",  # 台光電
        "3037.TW",  # 欣興
        "2881.TW",  # 富邦金
        "2891.TW",  # 中信金
        "2882.TW",  # 國泰金
        "2886.TW",  # 兆豐金
        "2884.TW",  # 玉山金
        "2382.TW",  # 廣達
        "2357.TW",  # 華碩
        "2379.TW",  # 瑞昱
        "3034.TW",  # 聯詠
        "2345.TW",  # 智邦
        "2395.TW",  # 研華
        "6669.TW",  # 緯穎
        "2327.TW",  # 國巨
        "2301.TW",  # 光寶科
        "2474.TW",  # 可成
        "2412.TW",  # 中華電
        "4904.TW",  # 遠傳
        "2912.TW",  # 統一超
        "2207.TW",  # 和泰車
        "2002.TW",  # 中鋼
        "1301.TW",  # 台塑
        "1303.TW",  # 南亞
    ]


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_twse_all_stocks() -> List[str]:
    """
    從 TWSE ISIN 頁面抓取台灣大盤（全部上市普通股）ticker 清單。
    資料來源：https://isin.twse.com.tw/isin/C_public.jsp?strMode=2
    回傳格式：['2330.TW', '2317.TW', ...]，依代號排序（大型股優先）。
    若抓取失敗，回傳預設30大市值股。
    """
    import re as _re

    # ── 方法 1：TWSE ISIN 頁面（最完整）────────────────────────────────
    try:
        url = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = requests.get(url, headers=headers, timeout=20)
        resp.encoding = "big5"  # TWSE ISIN 頁為 Big5 編碼

        dfs = pd.read_html(resp.text, header=0)
        df = dfs[0]

        # 第一欄格式為「代號　公司名稱」（全形空格分隔）
        first_col = df.iloc[:, 0].astype(str)
        tickers = []
        names = {}
        for cell in first_col:
            parts = cell.split("\u3000")  # 全形空格
            if len(parts) >= 2 and _re.match(r"^\d{4}$", parts[0].strip()):
                code = parts[0].strip()
                name = parts[1].strip()
                ticker = f"{code}.TW"
                tickers.append(ticker)
                # 同時更新公司名稱字典
                COMPANY_NAMES[ticker] = name

        if len(tickers) >= 10:
            # 依已知市值排名的前50大權值股（確保 Yahoo Finance 抓得到資料）
            top_50 = [
                "2330.TW", "2317.TW", "2454.TW", "2308.TW", "2382.TW",
                "2881.TW", "2303.TW", "2882.TW", "2891.TW", "3711.TW",
                "2886.TW", "2884.TW", "1216.TW", "2002.TW", "2357.TW",
                "2892.TW", "2885.TW", "2890.TW", "5880.TW", "2345.TW",
                "3034.TW", "2379.TW", "2880.TW", "2395.TW", "2301.TW",
                "2207.TW", "3037.TW", "2887.TW", "2883.TW", "2412.TW",
                "3231.TW", "6669.TW", "1303.TW", "1301.TW", "2327.TW",
                "2408.TW", "4904.TW", "3045.TW", "2383.TW", "2912.TW",
                "1402.TW", "1101.TW", "1326.TW", "3702.TW", "2603.TW",
                "2409.TW", "2353.TW", "3481.TW", "2356.TW", "2457.TW"
            ]
            
            # 確保清單存在
            front = [t for t in top_50 if t in tickers]
            
            # 剩下的股票依代號排序（避免全部擠在前面）
            rest = sorted([t for t in tickers if t not in top_50], key=lambda t: int(t.split(".")[0]))
            
            return front + rest

    except Exception:
        pass

    # ── 方法 2：TWSE OpenAPI 上市公司清單 ────────────────────────────────
    try:
        url2 = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
        headers2 = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
        resp2 = requests.get(url2, headers=headers2, timeout=15)
        if resp2.status_code == 200:
            data2 = resp2.json()
            if data2:
                df2 = pd.DataFrame(data2)
                # 找代碼欄
                code_col2 = next(
                    (c for c in df2.columns if any(k in c for k in ["代號", "Code", "股票"])),
                    df2.columns[0]
                )
                codes = df2[code_col2].astype(str).str.strip()
                tickers = [f"{c}.TW" for c in codes if _re.match(r"^\d{4}$", c)]
                if len(tickers) >= 10:
                    return tickers
    except Exception:
        pass

    # ── 備用：30大市值股 ────────────────────────────────────────────────
    return [
        "2330.TW", "2454.TW", "2317.TW", "2308.TW", "3711.TW",
        "2303.TW", "2382.TW", "2881.TW", "2882.TW", "2891.TW",
        "2886.TW", "2884.TW", "2357.TW", "2379.TW", "2345.TW",
        "3037.TW", "2383.TW", "6669.TW", "2327.TW", "2395.TW",
        "2412.TW", "4904.TW", "2912.TW", "2207.TW", "2002.TW",
        "1301.TW", "1303.TW", "2301.TW", "2474.TW", "3034.TW",
    ]


# ------------------------------------------------------------
# Utilities
# ------------------------------------------------------------
def to_csv_download(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")


def safe_read_csv(path: Path) -> Optional[pd.DataFrame]:
    if path.exists():
        try:
            return pd.read_csv(path)
        except Exception as e:
            st.warning(f"讀取檔案失敗：{path.name}，原因：{e}")
            return None
    return None


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    return df


def ensure_datetime(df: pd.DataFrame, col: str) -> pd.DataFrame:
    if col in df.columns:
        df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


def normalize_ticker_for_merge(ticker: str) -> str:
    if pd.isna(ticker):
        return ticker
    ticker = str(ticker).strip().upper()
    if ticker.endswith(".TW") or ticker.endswith(".TWO"):
        return ticker
    if ticker.isdigit() and len(ticker) == 4:
        return f"{ticker}.TW"
    return ticker


def infer_price_wide_or_long(df: pd.DataFrame, date_col: str = "date") -> pd.DataFrame:
    df = normalize_columns(df)
    df = ensure_datetime(df, date_col)

    if {"date", "ticker", "close"}.issubset(df.columns):
        df = df[["date", "ticker", "close"]].dropna()
        df["ticker"] = df["ticker"].astype(str).apply(normalize_ticker_for_merge)
        return df

    if date_col in df.columns:
        value_cols = [c for c in df.columns if c != date_col]
        long_df = df.melt(
            id_vars=[date_col],
            value_vars=value_cols,
            var_name="ticker",
            value_name="close"
        )
        long_df = long_df.rename(columns={date_col: "date"}).dropna()
        long_df["ticker"] = long_df["ticker"].astype(str).apply(normalize_ticker_for_merge)
        return long_df

    raise ValueError("價格資料必須包含 long format(date,ticker,close) 或 wide format(date, ticker1, ticker2, ...) 格式")


def preprocess_esg(df: pd.DataFrame) -> pd.DataFrame:
    df = normalize_columns(df)
    rename_map = {
        "stock_id": "ticker",
        "code": "ticker",
        "symbol": "ticker",
        "yearmonth": "date",
        "month": "date",
        "esg": "esg_total",
        "e": "e_score",
        "s": "s_score",
        "g": "g_score",
        "controversy": "controversy_score",
        "carbon": "carbon_intensity",
        "carbon_emission": "carbon_intensity",
    }
    df = df.rename(columns={c: rename_map.get(c, c) for c in df.columns})

    if "ticker" not in df.columns:
        raise ValueError("ESG 資料必須包含 ticker 欄位")

    if "date" in df.columns:
        df = ensure_datetime(df, "date")
    else:
        df["date"] = pd.NaT

    df["ticker"] = df["ticker"].astype(str).apply(normalize_ticker_for_merge)
    return df


def preprocess_financials(df: pd.DataFrame) -> pd.DataFrame:
    df = normalize_columns(df)
    rename_map = {
        "stock_id": "ticker",
        "code": "ticker",
        "symbol": "ticker",
        "yearmonth": "date",
        "month": "date",
        "pb": "pb",
        "pe": "pe",
        "debt_ratio": "debt_ratio",
        "lev": "debt_ratio",
    }
    df = df.rename(columns={c: rename_map.get(c, c) for c in df.columns})

    if "ticker" not in df.columns:
        raise ValueError("財務資料必須包含 ticker 欄位")

    if "date" in df.columns:
        df = ensure_datetime(df, "date")
    else:
        df["date"] = pd.NaT

    df["ticker"] = df["ticker"].astype(str).apply(normalize_ticker_for_merge)
    return df


def yahoo_ticker_format(ticker: str) -> str:
    ticker = str(ticker).strip().upper()
    if ticker.endswith(".TW") or ticker.endswith(".TWO"):
        return ticker
    if ticker.isdigit() and len(ticker) == 4:
        return f"{ticker}.TW"
    return ticker


def fetch_yahoo_prices(tickers: List[str], start: str, end: str) -> pd.DataFrame:
    if not YFINANCE_AVAILABLE:
        raise ImportError("尚未安裝 yfinance。請先 pip install yfinance")

    tickers = [yahoo_ticker_format(t) for t in tickers if str(t).strip()]
    if not tickers:
        raise ValueError("請至少輸入一個 ticker")

    all_rows = []
    failed = []
    progress = st.progress(0, text="開始從 Yahoo Finance 載入資料...")

    for idx, ticker in enumerate(tickers, start=1):
        success = False

        for attempt in range(3):
            try:
                df = yf.download(
                    tickers=ticker,
                    start=start,
                    end=end,
                    auto_adjust=True,
                    progress=False,
                    threads=False,
                    group_by="column",
                )

                if df is None or df.empty:
                    raise ValueError(f"{ticker} 沒有抓到資料")

                if "Close" in df.columns:
                    temp = df[["Close"]].reset_index().rename(
                        columns={"Date": "date", "Close": "close"}
                    )
                else:
                    close_candidates = []
                    for c in df.columns:
                        c_str = str(c)
                        if c_str == "Close" or "Close" in c_str:
                            close_candidates.append(c)

                    if not close_candidates:
                        raise ValueError(f"{ticker} 找不到 Close 欄位")

                    temp = df[[close_candidates[0]]].reset_index()
                    temp.columns = ["date", "close"]

                temp["ticker"] = ticker
                temp["date"] = pd.to_datetime(temp["date"], errors="coerce")
                temp["close"] = pd.to_numeric(temp["close"], errors="coerce")
                temp = temp.dropna(subset=["date", "close"])

                if temp.empty:
                    raise ValueError(f"{ticker} 抓回資料後為空")

                all_rows.append(temp[["date", "ticker", "close"]])
                success = True
                break

            except Exception:
                wait_sec = 2 + attempt * 3 + random.uniform(0.5, 1.5)
                time.sleep(wait_sec)

        if not success:
            failed.append(ticker)

        progress.progress(
            idx / len(tickers),
            text=f"Yahoo Finance 載入中... {idx}/{len(tickers)}  {ticker_display(ticker)}"
        )

        time.sleep(1.5 + random.uniform(0.2, 0.8))

    progress.empty()

    if failed:
        st.warning(f"以下 ticker 從 Yahoo Finance 抓取失敗：{', '.join(failed)}")

    if not all_rows:
        raise ValueError("Yahoo Finance 沒有回傳任何可用價格資料，請稍後再試，或改用本機 CSV。")

    out = pd.concat(all_rows, ignore_index=True)
    out["ticker"] = out["ticker"].astype(str).apply(normalize_ticker_for_merge)
    out = out.sort_values(["ticker", "date"]).reset_index(drop=True)
    return out


def compute_daily_returns(price_long: pd.DataFrame) -> pd.DataFrame:
    df = price_long.copy().sort_values(["ticker", "date"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["close"])
    df["ret_1d"] = df.groupby("ticker")["close"].pct_change()
    return df


def add_technical_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    短樣本可跑版：
    - 技術指標視窗縮短為 3 / 5
    - 預測目標改為未來 5 日報酬
    """
    df = df.copy().sort_values(["ticker", "date"])
    g = df.groupby("ticker")

    df["mom_3"] = g["close"].pct_change(3)
    df["mom_5"] = g["close"].pct_change(5)
    df["vol_3"] = g["ret_1d"].rolling(3).std().reset_index(level=0, drop=True) * np.sqrt(TRADING_DAYS)
    df["vol_5"] = g["ret_1d"].rolling(5).std().reset_index(level=0, drop=True) * np.sqrt(TRADING_DAYS)
    df["avg_close_5"] = g["close"].rolling(5).mean().reset_index(level=0, drop=True)

    # 短樣本預測目標
    df["fwd_ret_5"] = g["close"].shift(-5) / df["close"] - 1

    return df


def merge_features(price_df: pd.DataFrame, esg_df: Optional[pd.DataFrame], fin_df: Optional[pd.DataFrame]) -> pd.DataFrame:
    base = add_technical_features(compute_daily_returns(price_df))
    base["year_month"] = base["date"].dt.to_period("M").astype(str)

    if esg_df is not None and not esg_df.empty:
        esg_df = esg_df.copy()
        if esg_df["date"].isna().all():
            base = base.merge(esg_df.drop(columns=["date"]), on="ticker", how="left")
        else:
            esg_df["year_month"] = esg_df["date"].dt.to_period("M").astype(str)
            esg_monthly = esg_df.sort_values(["ticker", "date"]).drop_duplicates(["ticker", "year_month"], keep="last")
            base = base.merge(esg_monthly.drop(columns=["date"]), on=["ticker", "year_month"], how="left")

    if fin_df is not None and not fin_df.empty:
        fin_df = fin_df.copy()
        if fin_df["date"].isna().all():
            base = base.merge(fin_df.drop(columns=["date"]), on="ticker", how="left")
        else:
            fin_df["year_month"] = fin_df["date"].dt.to_period("M").astype(str)
            fin_monthly = fin_df.sort_values(["ticker", "date"]).drop_duplicates(["ticker", "year_month"], keep="last")
            base = base.merge(fin_monthly.drop(columns=["date"]), on=["ticker", "year_month"], how="left")

    return base


def apply_esg_rules(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    if "controversy_score" in out.columns:
        out = out[(out["controversy_score"].isna()) | (out["controversy_score"] <= 3)]

    if "eps" in out.columns:
        out = out[(out["eps"].isna()) | (out["eps"] >= 0)]

    if "esg_total" in out.columns:
        med = out.groupby("date")["esg_total"].transform("median")
        out = out[(out["esg_total"].isna()) | (out["esg_total"] >= med)]

    return out


def build_rule_based_portfolio(df: pd.DataFrame, top_n: int = DEFAULT_TOP_N) -> pd.DataFrame:
    data = apply_esg_rules(df)

    score_cols = [c for c in [
        "esg_total", "e_score", "s_score", "g_score",
        "roe", "roa", "mom_3", "mom_5"
    ] if c in data.columns]

    if not score_cols:
        raise ValueError("缺少可用於規則式 ESG 選股的欄位")

    rank_df = data[["date", "ticker", "close", "fwd_ret_5"] + score_cols].copy()

    for c in score_cols:
        rank_df[f"rank_{c}"] = rank_df.groupby("date")[c].rank(pct=True)

    rank_cols = [c for c in rank_df.columns if c.startswith("rank_")]
    rank_df["rule_score"] = rank_df[rank_cols].mean(axis=1)

    selected = (
        rank_df.sort_values(["date", "rule_score"], ascending=[True, False])
        .groupby("date")
        .head(top_n)
        .copy()
    )
    selected["weight"] = 1 / top_n
    selected["portfolio"] = "Rule-based ESG"
    return selected


def get_feature_columns(df: pd.DataFrame) -> List[str]:
    exclude = {"date", "ticker", "close", "ret_1d", "fwd_ret_5", "year_month"}
    return [c for c in df.columns if c not in exclude and pd.api.types.is_numeric_dtype(df[c])]


def fill_feature_na_with_median(df: pd.DataFrame, feature_cols: List[str]) -> pd.DataFrame:
    df = df.copy()
    for col in feature_cols:
        if col in df.columns and not df[col].isna().all():
            df[col] = df[col].fillna(df[col].median())
    return df


def build_ai_portfolio(df: pd.DataFrame, model_name: str, top_n: int, n_estimators: int):
    data = apply_esg_rules(df).dropna(subset=["fwd_ret_5"]).copy()
    feature_cols = get_feature_columns(data)

    if not feature_cols:
        raise ValueError("缺少可用於 AI 模型的特徵")

    data = fill_feature_na_with_median(data, feature_cols)
    data = data.dropna(subset=["fwd_ret_5"]).copy()

    if data.empty:
        raise ValueError("特徵資料在清理缺漏值後為空，請補充 ESG/財務資料或縮短特徵需求。")

    split_date = data["date"].quantile(0.8)
    train_df = data[data["date"] <= split_date].copy()
    test_df = data[data["date"] > split_date].copy()

    if train_df.empty or test_df.empty:
        raise ValueError("訓練集或測試集為空，請調整資料期間。")

    X_train = train_df[feature_cols]
    y_train = train_df["fwd_ret_5"]
    X_test = test_df[feature_cols]
    y_test = test_df["fwd_ret_5"]

    if model_name == "Random Forest":
        if not SKLEARN_AVAILABLE:
            raise ImportError("請安裝 scikit-learn")
        model = RandomForestRegressor(
            n_estimators=n_estimators,
            max_depth=6,
            min_samples_leaf=5,
            random_state=42,
            n_jobs=-1,
        )
    elif model_name == "XGBoost":
        if not XGBOOST_AVAILABLE:
            raise ImportError("請安裝 xgboost")
        model = xgb.XGBRegressor(
            n_estimators=n_estimators,
            max_depth=3,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            objective="reg:squarederror",
            random_state=42,
        )
    else:
        raise ValueError("不支援的模型")

    model.fit(X_train, y_train)

    eval_df = pd.DataFrame({
        "date": test_df["date"],
        "ticker": test_df["ticker"],
        "y_true": y_test,
        "y_pred": model.predict(X_test),
    })

    selected = test_df[["date", "ticker", "close", "fwd_ret_5"] + feature_cols].copy()
    selected["pred_score"] = model.predict(selected[feature_cols])
    selected = (
        selected.sort_values(["date", "pred_score"], ascending=[True, False])
        .groupby("date")
        .head(top_n)
        .copy()
    )
    selected["weight"] = 1 / top_n
    selected["portfolio"] = f"AI-ESG ({model_name})"

    return selected, model, feature_cols, eval_df


def compute_portfolio_returns(selected_df: pd.DataFrame) -> pd.DataFrame:
    if selected_df is None or selected_df.empty:
        return pd.DataFrame(columns=["date", "ret", "cum"])

    df = selected_df.copy()
    df["weighted_ret"] = df["weight"] * df["fwd_ret_5"]

    out = (
        df.groupby("date", as_index=False)["weighted_ret"]
        .sum()
        .rename(columns={"weighted_ret": "ret"})
    )
    out["cum"] = (1 + out["ret"].fillna(0)).cumprod()
    return out


def compute_etf_returns(etf_long: pd.DataFrame) -> pd.DataFrame:
    if etf_long is None or etf_long.empty:
        return pd.DataFrame(columns=["date", "portfolio", "ret", "cum"])

    rows = []
    for ticker, g in etf_long.groupby("ticker"):
        g = g.sort_values("date").copy()
        g["ret"] = g["close"].pct_change()
        g["cum"] = (1 + g["ret"].fillna(0)).cumprod()
        g["portfolio"] = ticker.upper()
        rows.append(g[["date", "portfolio", "ret", "cum"]])

    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=["date", "portfolio", "ret", "cum"])


def performance_summary(return_df: pd.DataFrame, ret_col: str = "ret") -> dict:
    r = return_df[ret_col].dropna()

    if len(r) == 0:
        return {
            "Cumulative Return": np.nan,
            "Annual Return": np.nan,
            "Annual Volatility": np.nan,
            "Sharpe": np.nan,
            "Max Drawdown": np.nan,
        }

    cum = (1 + r).prod() - 1
    ann_ret = (1 + r.mean()) ** TRADING_DAYS - 1
    ann_vol = r.std() * np.sqrt(TRADING_DAYS)
    sharpe = (ann_ret - RISK_FREE_RATE) / ann_vol if ann_vol > 0 else np.nan

    wealth = (1 + r).cumprod()
    drawdown = wealth / wealth.cummax() - 1

    return {
        "Cumulative Return": cum,
        "Annual Return": ann_ret,
        "Annual Volatility": ann_vol,
        "Sharpe": sharpe,
        "Max Drawdown": drawdown.min(),
    }


def fmt_pct(x: float) -> str:
    return "-" if pd.isna(x) else f"{x:.2%}"


def fmt_num(x: float) -> str:
    return "-" if pd.isna(x) else f"{x:.3f}"


def add_company_name_col(df: pd.DataFrame) -> pd.DataFrame:
    """在 DataFrame 中新增 company_name 欄位（中文公司名稱）"""
    df = df.copy()
    df.insert(
        df.columns.get_loc("ticker") + 1,
        "公司名稱",
        df["ticker"].apply(get_company_name)
    )
    return df


@st.cache_data(show_spinner=False)
def load_local_data():
    stock_raw = safe_read_csv(STOCK_PRICE_FILE)
    esg_raw = safe_read_csv(ESG_FILE)
    fin_raw = safe_read_csv(FINANCIAL_FILE)
    etf_raw = safe_read_csv(ETF_FILE)

    stock = infer_price_wide_or_long(stock_raw) if stock_raw is not None else None
    esg = preprocess_esg(esg_raw) if esg_raw is not None else None
    fin = preprocess_financials(fin_raw) if fin_raw is not None else None
    etf = infer_price_wide_or_long(etf_raw) if etf_raw is not None else None

    return stock, esg, fin, etf


# ------------------------------------------------------------
# Header
# ------------------------------------------------------------
st.title("📊 ESG-AI Smart Portfolio Dashboard")
st.caption(f"AI 選股 × ESG 因子 × 台灣大盤比較平台｜{CURRENT_MONTH}版（選股母池：台灣大盤上市股；基準：台灣加權指數 ^TWII）")


# ------------------------------------------------------------
# Sidebar controls
# ------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ 參數設定")
    data_mode = st.radio("資料來源模式", ["本機 CSV", "Yahoo Finance 自動下載"], index=1)

    model_name = st.selectbox("AI 模型", ["Random Forest", "XGBoost"])
    top_n = st.slider("Top N 選股數", 5, 20, DEFAULT_TOP_N, 1)
    n_estimators = st.slider("樹的數量", 50, 500, DEFAULT_RF_TREES, 50)

    st.markdown("---")
    st.markdown("**ETF 對照清單**")
    compare_etfs = st.multiselect(
        "比較 ETF",
        DEFAULT_ETFS,
        default=DEFAULT_ETFS
    )

    st.markdown("---")
    if data_mode == "Yahoo Finance 自動下載":
        st.caption("Yahoo Finance 容易限流，建議一次先抓 10–20 檔股票；展示時建議優先使用本機 CSV。")

        # 選股母池：台灣大盤
        use_twse_pool = st.checkbox("✅ 自動使用台灣大盤（全上市股）為選股母池", value=True)

        if use_twse_pool:
            with st.spinner("正在從 TWSE 抓取台灣大盤上市股清單..."):
                twse_stocks = fetch_twse_all_stocks()
            st.success(f"台灣大盤共 {len(twse_stocks)} 檔上市普通股")
            preview = ", ".join([
                f"{t}({get_company_name(t)})" for t in twse_stocks[:5]
            ])
            st.caption(f"前5檔：{preview} ...")

            max_stocks = st.slider(
                "抓取前 N 大股票（依市值排序，建議 20–50 檔）",
                min_value=5,
                max_value=min(100, len(twse_stocks)),
                value=min(30, len(twse_stocks)),
                step=5
            )
            selected_tickers = twse_stocks[:max_stocks]
            stock_input = ",".join(selected_tickers)
            st.text_area("已選股票（可手動修改）", value=stock_input, height=100)
        else:
            stock_input = st.text_area(
                "股票 ticker（逗號分隔）",
                value="2330.TW,2317.TW,2454.TW,2308.TW,3711.TW"
            )

        start_str = st.text_input("開始日期", value=DEFAULT_START_DATE)
        end_str = st.text_input("結束日期", value=DEFAULT_END_DATE)
        load_btn = st.button("🚀 從 Yahoo Finance 載入並重新評分")
    else:
        st.code("""data/stock_price.csv
data/esg_scores.csv
data/financials.csv
data/etf_prices.csv""")
        load_btn = st.button("載入本機資料")




# ------------------------------------------------------------
# Data loading logic
# ------------------------------------------------------------
stock_price = None
esg_scores = None
financials = None
etf_prices = None

if data_mode == "本機 CSV":
    if load_btn:
        try:
            stock_price, esg_scores, financials, etf_prices = load_local_data()

            st.session_state["loaded"] = True
            st.session_state["stock_price"] = stock_price
            st.session_state["esg_scores"] = esg_scores
            st.session_state["financials"] = financials
            st.session_state["etf_prices"] = etf_prices

            st.success("本機資料載入成功。")
        except Exception as e:
            st.error(f"本機資料載入失敗：{e}")

else:
    if load_btn:
        try:
            tickers = [x.strip() for x in stock_input.split(",") if x.strip()]

            st.info(f"📋 {CURRENT_MONTH}｜正在抓取 {len(tickers)} 檔成分股的 Yahoo Finance 價格資料...")
            stock_price = fetch_yahoo_prices(tickers, start_str, end_str)

            etf_prices = None
            if compare_etfs:
                try:
                    st.info(f"📈 正在抓取 {len(compare_etfs)} 檔 ETF 對照資料...")
                    etf_prices = fetch_yahoo_prices(compare_etfs, start_str, end_str)
                except Exception as e:
                    st.warning(f"ETF 價格抓取失敗：{e}")
                    etf_prices = None

            local_esg_raw = safe_read_csv(ESG_FILE)
            local_fin_raw = safe_read_csv(FINANCIAL_FILE)

            esg_scores = preprocess_esg(local_esg_raw) if local_esg_raw is not None else None
            financials = preprocess_financials(local_fin_raw) if local_fin_raw is not None else None

            if esg_scores is None:
                st.info("未找到本機 esg_scores.csv，系統將只使用價格與財務/技術因子進行 AI 評分。")

            if financials is None:
                st.info("未找到本機 financials.csv，系統將只使用價格與 ESG/技術因子。")

            st.session_state["loaded"] = True
            st.session_state["stock_price"] = stock_price
            st.session_state["esg_scores"] = esg_scores
            st.session_state["financials"] = financials
            st.session_state["etf_prices"] = etf_prices
            st.session_state["month_label"] = CURRENT_MONTH

            try:
                DATA_DIR.mkdir(parents=True, exist_ok=True)
                stock_price.to_csv(STOCK_PRICE_FILE, index=False, encoding="utf-8-sig")
                if etf_prices is not None and not etf_prices.empty:
                    etf_prices.to_csv(ETF_FILE, index=False, encoding="utf-8-sig")
                st.success(f"✅ {CURRENT_MONTH} 價格資料已載入，並已快取到 data/ 資料夾。")
            except Exception as cache_err:
                st.warning(f"資料已載入，但快取存檔失敗：{cache_err}")

        except Exception as e:
            st.error(f"Yahoo Finance 載入失敗：{e}")
            st.info("建議改用本機 CSV，或減少 ticker 數量後再試。")


if st.session_state.get("loaded", False):
    stock_price = st.session_state.get("stock_price")
    esg_scores = st.session_state.get("esg_scores")
    financials = st.session_state.get("financials")
    etf_prices = st.session_state.get("etf_prices")
    month_label = st.session_state.get("month_label", CURRENT_MONTH)
else:
    month_label = CURRENT_MONTH


if stock_price is None or stock_price.empty:
    st.info("請先在左側選擇資料來源並載入資料。")
    st.stop()

# ------------------------------------------------------------
# Raw data downloads
# ------------------------------------------------------------
st.markdown("### 原始資料下載")
col_d1, col_d2, col_d3, col_d4 = st.columns(4)

with col_d1:
    st.download_button(
        "下載股票價格 CSV",
        to_csv_download(stock_price),
        file_name="stock_price_export.csv",
        mime="text/csv"
    )

with col_d2:
    if esg_scores is not None and not esg_scores.empty:
        st.download_button(
            "下載 ESG CSV",
            to_csv_download(esg_scores),
            file_name="esg_scores_export.csv",
            mime="text/csv"
        )

with col_d3:
    if financials is not None and not financials.empty:
        st.download_button(
            "下載財務 CSV",
            to_csv_download(financials),
            file_name="financials_export.csv",
            mime="text/csv"
        )

with col_d4:
    if etf_prices is not None and not etf_prices.empty:
        st.download_button(
            "下載 ETF CSV",
            to_csv_download(etf_prices),
            file_name="etf_prices_export.csv",
            mime="text/csv"
        )

# ------------------------------------------------------------
# Main pipeline
# ------------------------------------------------------------
features_df = merge_features(stock_price, esg_scores, financials)

if features_df is None or features_df.empty:
    st.error("合併後的特徵資料為空，請檢查股票價格、ESG 與財務資料是否成功載入。")
    st.stop()

if "date" not in features_df.columns:
    st.error("features_df 中找不到 date 欄位，請檢查資料格式。")
    st.stop()

features_df["date"] = pd.to_datetime(features_df["date"], errors="coerce")
features_df = features_df.dropna(subset=["date"]).copy()

if features_df.empty:
    st.error("有效日期資料為空，請檢查 stock_price / ESG / financials 格式。")
    st.stop()

features_df = features_df.sort_values(["date", "ticker"]).copy()

min_date = features_df["date"].min()
max_date = features_df["date"].max()

if pd.isna(min_date) or pd.isna(max_date):
    st.error("日期範圍無法判定，請檢查資料中的 date 欄位。")
    st.stop()

selected_range = st.sidebar.date_input(
    "回測期間",
    value=(min_date.date(), max_date.date())
)

start_date = pd.to_datetime(selected_range[0])
end_date = pd.to_datetime(selected_range[1])

features_df = features_df[
    (features_df["date"] >= start_date) &
    (features_df["date"] <= end_date)
].copy()

if features_df.empty:
    st.warning("所選回測期間內沒有資料。")
    st.stop()

# Build portfolios
try:
    rule_port = build_rule_based_portfolio(features_df, top_n=top_n)
    ai_port, trained_model, feature_cols, eval_df = build_ai_portfolio(
        features_df, model_name, top_n, n_estimators
    )
except Exception as e:
    st.error(f"投組建構失敗：{e}")
    st.stop()

rule_ret = compute_portfolio_returns(rule_port)
rule_ret["portfolio"] = "Rule-based ESG"

ai_ret = compute_portfolio_returns(ai_port)
ai_ret["portfolio"] = f"AI-ESG ({model_name})"

portfolio_panel = pd.concat([rule_ret, ai_ret], ignore_index=True)

etf_panel = pd.DataFrame(columns=["date", "portfolio", "ret", "cum"])
if etf_prices is not None and not etf_prices.empty:
    etf_prices = etf_prices.copy()
    etf_prices["date"] = pd.to_datetime(etf_prices["date"], errors="coerce")
    etf_prices = etf_prices.dropna(subset=["date"])
    etf_prices = etf_prices[
        (etf_prices["date"] >= start_date) &
        (etf_prices["date"] <= end_date)
    ].copy()

    if not etf_prices.empty:
        etf_prices["ticker"] = etf_prices["ticker"].astype(str).apply(normalize_ticker_for_merge)
        etf_panel = compute_etf_returns(etf_prices)

all_series = pd.concat([portfolio_panel, etf_panel], ignore_index=True)

if all_series.empty:
    st.error("沒有可用的策略或 ETF 報酬資料。")
    st.stop()

# ------------------------------------------------------------
# Tabs
# ------------------------------------------------------------
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
    ["首頁總覽", "資料與選股邏輯", "AI 選股結果", "績效比較", "市場情境分析", "模型解釋"]
)

# ------------------------------------------------------------
# Tab 1
# ------------------------------------------------------------
with tab1:
    st.subheader(f"🗓️ {month_label} 最新成分股與權重配置")
    st.caption(f"選股母池：台灣大盤全上市股，透過 ESG 演算法篩出優質股；基準：台灣加權指數（^TWII）")


    ai_summary = performance_summary(ai_ret)
    rule_summary = performance_summary(rule_ret)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("AI-ESG 年化報酬", fmt_pct(ai_summary["Annual Return"]))
    c2.metric("AI-ESG Sharpe", fmt_num(ai_summary["Sharpe"]))
    c3.metric("AI-ESG 最大回撤", fmt_pct(ai_summary["Max Drawdown"]))
    c4.metric("Rule-based 年化報酬", fmt_pct(rule_summary["Annual Return"]))

    # 最新選股結果（三欄並排：AI+ESG、單純AI、單純ESG）
    st.markdown("---")
    st.markdown(f"#### {month_label} 最新成分股與權重配置")

    latest_date = ai_port["date"].max()

    col_ai_esg, col_ai_only, col_esg_only = st.columns(3)

    with col_ai_esg:
        st.markdown("**AI+ESG 選股**")
        ai_esg_picks = ai_port[ai_port["date"] == latest_date].sort_values("pred_score", ascending=False).copy()
        ai_esg_picks["權重(%)"] = (ai_esg_picks["weight"] * 100).round(1)
        ai_esg_display = ai_esg_picks[["ticker", "權重(%)"]].copy()
        ai_esg_display["公司名稱"] = ai_esg_display["ticker"].apply(get_company_name)
        st.dataframe(ai_esg_display[["ticker", "公司名稱", "權重(%)"]], use_container_width=True, hide_index=True)

    with col_ai_only:
        st.markdown("**單純 AI 選股**")
        # 單純AI：不考慮 ESG 規則過濾，直接用 pred_score 排序
        ai_only_picks = ai_port[ai_port["date"] == latest_date].sort_values("pred_score", ascending=False).copy()
        ai_only_picks["權重(%)"] = (ai_only_picks["weight"] * 100).round(1)
        ai_only_display = ai_only_picks[["ticker", "權重(%)"]].copy()
        ai_only_display["公司名稱"] = ai_only_display["ticker"].apply(get_company_name)
        st.dataframe(ai_only_display[["ticker", "公司名稱", "權重(%)"]], use_container_width=True, hide_index=True)

    with col_esg_only:
        st.markdown("**單純 ESG 選股**")
        rule_latest = rule_port[rule_port["date"] == rule_port["date"].max()].sort_values("rule_score", ascending=False).copy()
        rule_latest["權重(%)"] = (rule_latest["weight"] * 100).round(1)
        rule_display = rule_latest[["ticker", "權重(%)"]].copy()
        rule_display["公司名稱"] = rule_display["ticker"].apply(get_company_name)
        st.dataframe(rule_display[["ticker", "公司名稱", "權重(%)"]], use_container_width=True, hide_index=True)

    st.markdown("---")
    fig = px.line(
        all_series.sort_values("date"),
        x="date",
        y="cum",
        color="portfolio",
        title=f"{month_label} 累積報酬比較"
    )
    st.plotly_chart(fig, use_container_width=True)

# ------------------------------------------------------------
# Tab 2
# ------------------------------------------------------------
with tab2:
    st.subheader("資料與選股邏輯")
    st.write(f"目前模式：{data_mode}｜期間：{start_date.date()} ～ {end_date.date()}")

    c1, c2 = st.columns(2)

    with c1:
        st.markdown("#### 研究流程")
        st.markdown(
            "台灣大盤全上市股（TWSE）→ ESG/財務過濾 → 特徵工程 → AI 模型評分 → Top N 選股 → 投組回測 → 台灣加權指數（^TWII）比較"
        )


        st.markdown("#### Rule-based ESG 邏輯")
        rules = []
        if "controversy_score" in features_df.columns:
            rules.append("爭議事件分數過高者排除")
        if "eps" in features_df.columns:
            rules.append("EPS 為負者排除")
        if "esg_total" in features_df.columns:
            rules.append("ESG 總分低於當期中位數者排除")
        st.write(rules if rules else ["目前根據可用欄位進行過濾與排序（動量、波動度）"])

        st.markdown("#### 股票池資訊")
        tickers_in_pool = sorted(features_df["ticker"].unique())
        ticker_info = pd.DataFrame({
            "股票代碼": tickers_in_pool,
            "公司名稱": [get_company_name(t) for t in tickers_in_pool],
        })
        st.dataframe(ticker_info, use_container_width=True, hide_index=True)

    with c2:
        feat_df = pd.DataFrame({"feature": get_feature_columns(features_df)})
        st.markdown("#### 使用特徵欄位")
        st.dataframe(feat_df, use_container_width=True, height=320)

# ------------------------------------------------------------
# Tab 3
# ------------------------------------------------------------
with tab3:
    st.subheader("AI 選股結果")

    dates = sorted(ai_port["date"].dropna().unique())
    if dates:
        selected_date = st.selectbox(
            "選擇日期",
            dates,
            format_func=lambda x: pd.to_datetime(x).strftime("%Y-%m-%d")
        )

        picks = ai_port[ai_port["date"] == selected_date].sort_values(
            "pred_score", ascending=False
        ).copy()

        # 加入中文公司名稱
        picks.insert(1, "公司名稱", picks["ticker"].apply(get_company_name))

        show_cols = ["ticker", "公司名稱"] + [c for c in [
            "pred_score", "weight",
            "esg_total", "e_score", "s_score", "g_score",
            "roe", "roa", "mom_3", "mom_5", "vol_3", "vol_5"
        ] if c in picks.columns]

        st.dataframe(picks[show_cols], use_container_width=True, height=420)

        st.download_button(
            "下載當期 AI 選股結果",
            to_csv_download(picks[show_cols]),
            file_name=f"ai_picks_{pd.to_datetime(selected_date).strftime('%Y%m%d')}.csv",
            mime="text/csv"
        )

# ------------------------------------------------------------
# Tab 4
# ------------------------------------------------------------
with tab4:
    st.subheader("績效比較")

    rows = []
    for name, sub in all_series.groupby("portfolio"):
        s = performance_summary(sub)
        s["Portfolio"] = name
        rows.append(s)

    perf_table = pd.DataFrame(rows)[[
        "Portfolio", "Cumulative Return", "Annual Return",
        "Annual Volatility", "Sharpe", "Max Drawdown"
    ]]

    st.dataframe(
        perf_table.style.format({
            "Cumulative Return": "{:.2%}",
            "Annual Return": "{:.2%}",
            "Annual Volatility": "{:.2%}",
            "Sharpe": "{:.3f}",
            "Max Drawdown": "{:.2%}",
        }),
        use_container_width=True,
    )

    st.download_button(
        "下載績效比較表",
        to_csv_download(perf_table),
        file_name="performance_comparison.csv",
        mime="text/csv"
    )

    fig = px.scatter(
        perf_table,
        x="Annual Volatility",
        y="Annual Return",
        text="Portfolio",
        title="風險報酬散點圖"
    )
    fig.update_traces(textposition="top center")
    st.plotly_chart(fig, use_container_width=True)

# ------------------------------------------------------------
# Tab 5
# ------------------------------------------------------------
with tab5:
    st.subheader("市場情境分析")

    regime_options = {
        "全部期間": (start_date, end_date),
        "前半段": (start_date, start_date + (end_date - start_date) / 2),
        "後半段": (start_date + (end_date - start_date) / 2, end_date),
    }

    regime_name = st.selectbox("市場情境", list(regime_options.keys()))
    r_start, r_end = regime_options[regime_name]

    regime_df = all_series[
        (all_series["date"] >= r_start) & (all_series["date"] <= r_end)
    ].copy()

    if regime_df.empty:
        st.info("此情境區間沒有可用資料。")
    else:
        regime_df["cum_regime"] = regime_df.groupby("portfolio")["ret"].transform(
            lambda x: (1 + x.fillna(0)).cumprod()
        )
        fig = px.line(
            regime_df,
            x="date",
            y="cum_regime",
            color="portfolio",
            title=f"{regime_name} 累積報酬"
        )
        st.plotly_chart(fig, use_container_width=True)

# ------------------------------------------------------------
# Tab 6
# ------------------------------------------------------------
with tab6:
    st.subheader("模型解釋")

    if hasattr(trained_model, "feature_importances_"):
        importance_df = pd.DataFrame({
            "feature": feature_cols,
            "importance": trained_model.feature_importances_
        }).sort_values("importance", ascending=False)

        fig = px.bar(
            importance_df.head(15),
            x="feature",
            y="importance",
            title="特徵重要性 Top 15"
        )
        st.plotly_chart(fig, use_container_width=True)

        st.download_button(
            "下載特徵重要性",
            to_csv_download(importance_df),
            file_name="feature_importance.csv",
            mime="text/csv"
        )

    if eval_df is not None and not eval_df.empty and SKLEARN_AVAILABLE:
        try:
            rmse = mean_squared_error(eval_df["y_true"], eval_df["y_pred"], squared=False)
        except TypeError:
            # sklearn >= 1.4 已移除 squared 參數
            import math
            rmse = math.sqrt(mean_squared_error(eval_df["y_true"], eval_df["y_pred"]))
        st.metric("測試集 RMSE", fmt_num(rmse))

        st.download_button(
            "下載模型預測結果",
            to_csv_download(eval_df),
            file_name="model_predictions.csv",
            mime="text/csv"
        )

    if SHAP_AVAILABLE and hasattr(trained_model, "predict"):
        with st.expander("SHAP 分析（可能較慢）"):
            try:
                sample_df = apply_esg_rules(features_df).dropna(subset=["fwd_ret_5"]).copy()
                sample_df = fill_feature_na_with_median(sample_df, get_feature_columns(sample_df))
                sample_df = sample_df.tail(min(200, len(sample_df)))

                X_sample = sample_df[get_feature_columns(sample_df)]
                explainer = shap.Explainer(trained_model, X_sample)
                shap_values = explainer(X_sample)

                shap_df = pd.DataFrame(
                    np.abs(shap_values.values).mean(axis=0),
                    index=X_sample.columns,
                    columns=["mean_abs_shap"]
                ).sort_values("mean_abs_shap", ascending=False).reset_index()
                shap_df.columns = ["feature", "mean_abs_shap"]

                fig = px.bar(
                    shap_df.head(15),
                    x="feature",
                    y="mean_abs_shap",
                    title="SHAP 重要性 Top 15"
                )
                st.plotly_chart(fig, use_container_width=True)

                st.download_button(
                    "下載 SHAP 重要性",
                    to_csv_download(shap_df),
                    file_name="shap_importance.csv",
                    mime="text/csv"
                )

            except Exception as e:
                st.warning(f"SHAP 分析失敗：{e}")
    else:
        st.caption("若已安裝 shap，可顯示更完整的模型解釋。")

st.markdown("---")
st.caption(f"ESG-AI Smart Portfolio Dashboard｜{CURRENT_MONTH}版｜選股母池：台灣大盤（TWSE 全上市股）｜基準：台灣加權指數（^TWII）")

