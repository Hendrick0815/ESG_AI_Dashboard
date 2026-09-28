"""全專案共用設定。路徑一律以專案根目錄為基準，從哪裡執行都不會找錯檔案。"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 公開網站（Streamlit Cloud）請設環境變數 ESG_ALLOW_UPDATE=0：
# 雲端主機會被證交所與 Yahoo 擋，而且不該讓任何訪客觸發爬蟲。
ALLOW_DATA_UPDATE = os.getenv("ESG_ALLOW_UPDATE", "1") != "0"
SITE_NOTICE = os.getenv("ESG_SITE_NOTICE", "")   # 網站底部要顯示的補充說明（選填）

DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
TEJ_DIR = RAW_DIR / "tej"            # TEJ TESG 下載檔（可放多期，檔名不拘）
LOCAL_DIR = RAW_DIR / "local"        # 自己準備的 CSV（stock_price / financials / esg_scores / etf_prices）
PROCESSED_DIR = DATA_DIR / "processed"  # 爬蟲整理後的資料（程式自動維護）
DEMO_DIR = DATA_DIR / "demo"         # 合成示範資料，絕不和真實資料混用
OUTPUT_DIR = ROOT / "outputs"

PRICES_FILE = PROCESSED_DIR / "prices.csv"
BENCH_FILE = PROCESSED_DIR / "benchmarks.csv"
VALUATION_FILE = PROCESSED_DIR / "valuation.csv"
LISTING_FILE = PROCESSED_DIR / "listing.csv"
UPDATE_LOG_FILE = PROCESSED_DIR / "update_log.csv"

# ---- 市場與交易 ----
TRADING_DAYS = 252
RISK_FREE_RATE = 0.01           # 年化無風險利率（Sharpe 使用）
COMMISSION = 0.001425           # 手續費（買、賣各一次）
SELL_TAX = 0.003                # 證交稅（僅賣出）

# 比較基準：^TWII 加權指數、0050 台灣50、00850 元大臺灣ESG永續、00878 國泰永續高股息
BENCHMARKS = ["^TWII", "0050.TW", "00850.TW", "00878.TW"]
BENCHMARK_NAMES = {
    "^TWII": "加權指數",
    "0050.TW": "元大台灣50",
    "00850.TW": "元大臺灣ESG永續",
    "00878.TW": "國泰永續高股息",
    "0056.TW": "元大高股息",
}

# 預設股票池：市值前 50 大（清單抓不到時也用這份）
CORE_UNIVERSE = [
    "2330.TW", "2317.TW", "2454.TW", "2308.TW", "2382.TW",
    "2881.TW", "2303.TW", "2882.TW", "2891.TW", "3711.TW",
    "2886.TW", "2884.TW", "1216.TW", "2002.TW", "2357.TW",
    "2892.TW", "2885.TW", "2890.TW", "5880.TW", "2345.TW",
    "3034.TW", "2379.TW", "2880.TW", "2395.TW", "2301.TW",
    "2207.TW", "3037.TW", "2887.TW", "2883.TW", "2412.TW",
    "3231.TW", "6669.TW", "1303.TW", "1301.TW", "2327.TW",
    "2408.TW", "4904.TW", "3045.TW", "2383.TW", "2912.TW",
    "1402.TW", "1101.TW", "1326.TW", "3702.TW", "2603.TW",
    "2409.TW", "2353.TW", "3481.TW", "2356.TW", "4938.TW",
]

# ---- 策略預設值 ----
DEFAULT_TOP_N = 10
DEFAULT_ESG_WEIGHT = 0.3        # AI+ESG 混合分數中 ESG 的比重
DEFAULT_N_ESTIMATORS = 100
RETRAIN_EVERY = 3               # 每 3 個月重新訓練一次模型（每月仍用最新模型選股）
CACHE_DIR = Path(os.getenv("ESG_CACHE_DIR", OUTPUT_DIR / "cache"))  # 回測結果存檔，重開網頁不用重算
HOLD_DAYS = 21                  # 每月調倉（每月最後一個交易日）；模型預測未來 21 個交易日的報酬
MIN_TRAIN_DAYS = 250            # 至少一年訓練資料；資料不足時改用前 50%

# 集中加權（原 generate_backtest.py）：第一名 30%，前五名約 69%
CONVICTION_WEIGHTS = [0.30, 0.15, 0.10, 0.08, 0.06, 0.05, 0.04, 0.04, 0.03, 0.03,
                      0.02, 0.02, 0.02, 0.01, 0.01, 0.01, 0.01, 0.01, 0.005, 0.005]

# ESG 相關欄位（「單純 AI」一律不使用）
ESG_COLS = ["esg_total", "e_score", "s_score", "g_score", "controversy_score", "carbon_intensity", "event_score"]

# ---- 選股條件（技術面＋籌碼面）----
MIN_DAILY_LOTS = 100            # 近 20 個交易日每天至少 100 張（排除成交量太小、容易被炒作的股票）
RANGE_MAX_WIDTH = 0.25          # 區間整理：過去 40 天最高／最低不超過 25%
BREAKOUT_BAND = 0.05            # 即將突破：收盤價距離區間高點 5% 以內
BREAKOUT_MAX_ABOVE = 0.03       # 已經突破超過 3% 就不算「即將」突破（避免追高）
VOLUME_RATIO_MIN = 1.1          # 稍微出量：5 日均量 / 20 日均量介於 1.1～2 倍
VOLUME_RATIO_MAX = 2.0          # 超過 2 倍屬於爆量，常見於炒作或出貨，不算「稍微」

# ---- 風險控制（目標：最大回撤 10% 以內）----
MAX_DD_TARGET = 0.10            # 回撤目標；持股比例 = min(1, 此值 ÷ 大盤年化波動)
MARKET_INDEX = "^TWII"          # 用加權指數的波動決定持股比例
EXPOSURE_STEP = 0.1             # 持股比例以 10% 為單位調整，避免每天小幅進出付手續費

INSTITUTIONAL_FILE = PROCESSED_DIR / "institutional.csv"   # 三大法人買賣超（證交所 T86）
