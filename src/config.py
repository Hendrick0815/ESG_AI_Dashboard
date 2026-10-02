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

# 股票池大小：近 20 個交易日平均成交金額最大的 N 檔上市櫃普通股（一定包含下面的核心 50 檔）
UNIVERSE_SIZE = 300
UNIVERSE_FILE = PROCESSED_DIR / "universe.csv"     # 最近一次選出的股票池（含平均成交金額）

# 核心股票池：市值前 50 大（清單抓不到時也用這份）
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

# ---- 策略預設值（目標：最高報酬，不限制回撤）----
# 預設值來自 300 檔股票池、每 10 個交易日調倉、2024-01～2026-10 的參數比較（Random Forest、3 組隨機種子）：
# 等權 Top 20 的「單純 AI」年化平均約 119%（最差的種子 113%），Top 10～30 都在 116%～126%，不是單一參數巧合；
# 集中加權反而較差（約 90%），因為模型排名前幾名的把握沒有比第 10～20 名高多少。
DEFAULT_TOP_N = 20
DEFAULT_WEIGHTING = "等權"
DEFAULT_RISK_CONTROL = False    # 風險控制會把報酬從約 57% 壓到 45%，以報酬為目標時預設關閉
DEFAULT_ESG_WEIGHT = 0.3        # AI+ESG 混合分數中 ESG 的比重
DEFAULT_N_ESTIMATORS = 100
RETRAIN_EVERY = 3               # 每 3 次調倉（約 30 個交易日）重新訓練一次模型；比每 6 次（約一季）年化高約 10 個百分點
CACHE_DIR = Path(os.getenv("ESG_CACHE_DIR", OUTPUT_DIR / "cache"))  # 回測結果存檔，重開網頁不用重算
HOLD_DAYS = 10                  # 每 10 個交易日調倉一次；模型預測未來 10 個交易日的報酬
MIN_TRAIN_DAYS = 250            # 至少一年訓練資料；資料不足時改用前 50%

# 集中加權（原 generate_backtest.py）：第一名 30%，前五名約 69%
CONVICTION_WEIGHTS = [0.30, 0.15, 0.10, 0.08, 0.06, 0.05, 0.04, 0.04, 0.03, 0.03,
                      0.02, 0.02, 0.02, 0.01, 0.01, 0.01, 0.01, 0.01, 0.005, 0.005]

# ESG 相關欄位（「單純 AI」一律不使用）
ESG_COLS = ["esg_total", "e_score", "s_score", "g_score", "controversy_score", "carbon_intensity", "event_score"]

# ---- 風險控制（選用，預設關閉；開啟可降低最大回撤，但報酬會明顯變低）----
# 三條都是常見、沒有針對這段回測期間最佳化的設定；改參數追求更好看的回測數字容易過度擬合。
STOCK_TREND_MA = 200            # ① 不買跌破年線（200 日均線）的股票：避開長期下跌中的股票
VOL_CAP_QUANTILE = 0.8          # ② 排除近 60 日波動最高的 20% 股票：大跌時通常跌最兇
MARKET_INDEX = "^TWII"          # ③ 大盤濾網：加權指數跌破年線 → 持股減半，站回年線 → 恢復滿倉
MARKET_MA = 200
MARKET_WEAK_EXPOSURE = 0.5
EXPOSURE_STEP = 0.1             # 持股比例的最小調整單位

INSTITUTIONAL_FILE = PROCESSED_DIR / "institutional.csv"   # 三大法人買賣超（證交所 T86）
