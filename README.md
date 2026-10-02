# 🌿 ESG-AI 台股選股平台

合併自原本的 `esg-dashboard`（app_v4 / app_v5）與 `my_project`（個股分析、generate_backtest），
整理成一個專案：**爬蟲抓資料 → 與本機資料（含 TEJ ESG）合併 → AI 選股 → 回測 → 與大盤／ETF 比較**。

## 快速開始

```bash
pip install -r requirements.txt

# 1. 抓資料（第一次約 1–3 分鐘；之後只補抓缺少的日期）
py scripts/update_data.py

# 1b.（選用）回補三大法人買賣超，給「產業與籌碼」頁參考（第一次約 40 分鐘，可中斷續抓）
py scripts/update_data.py --flows

# 2. 開啟網頁（股價落後最近收盤日時，打開網頁會自動補抓，和 TEJ 無關）
py -m streamlit run app.py

# 3.（選用）指令列跑回測、輸出 CSV 到 outputs/
python scripts/run_backtest.py

# 4.（選用）測試
python tests/test_core.py
python tests/smoke_ui.py
```

沒有網路或只想看功能？在網頁左側把「資料來源」切到「合成示範資料」。

**不開網頁也每天自動更新**：雙擊 `scripts/install_schedule.bat`，會建立 Windows 排程，平日 14:45 執行
`scripts/update_daily.bat`（= `py scripts/update_data.py --auto`）。電腦要開機，紀錄在 `data/processed/auto_update.log`。
「最近收盤日」的判斷：台灣時間 14:30 以後算當天，之前算前一個交易日（盤中不會抓到還沒收盤的價格）。

## 頁面

| 頁面 | 內容 | 來源 |
|---|---|---|
| 首頁 | 資料狀態、自動／手動更新、最新三策略選股、目前持股比例、累積淨值 | v5 首頁 |
| 策略回測 | 績效表、淨值／回撤／風險報酬圖、每日持股比例、歷次持股、市場情境、換股成本、方法說明 | v5 + generate_backtest |
| 個股分析 | K 線、均線、波動、報酬分布、ESG 雷達圖、同業比較 | my_project/app.py |
| 模型解釋 | 特徵重要性、Rank IC、Top N 超額報酬、SHAP、訓練紀錄 | v5 模型解釋 |
| 產業與籌碼 | 產業趨勢排行、三大法人（主力）買賣超排行與產業分布（僅供參考，不影響選股） | 新增 |

左側的策略設定在各頁共用。每組設定第一次計算完會存到 `outputs/cache/`，之後打開（包括重開網頁、`run_backtest.py` 算過的設定）直接讀檔；
資料檔一更新存檔就自動失效。計算中請不要切換頁面或調整設定，否則會從頭重算。

## 資料

```
data/
├─ raw/
│  ├─ tej/          ← 把 TEJ TESG 下載檔放這裡（.xlsx 或 .csv，可多期、檔名不拘）
│  └─ local/        ← 自己準備的 CSV（格式見下方），和爬蟲資料合併
├─ processed/       ← 爬蟲資料（程式自動維護，不要手動改）
│  ├─ prices.csv        股價（Yahoo Finance，還原權息）
│  ├─ benchmarks.csv    ^TWII、0050、00850、00878
│  ├─ valuation.csv     本益比／股價淨值比／殖利率（證交所，每月底一筆）
│  ├─ listing.csv       上市櫃普通股清單＋產業（證交所 ISIN）
│  ├─ institutional.csv 三大法人每日買賣超（證交所 T86，僅上市）
│  └─ update_log.csv    更新紀錄
└─ demo/            ← 合成示範資料（不是真實行情，不會和真實資料混用）
```

**合併規則**
- 同一天同一檔股價有兩個來源時，爬蟲（還原權息）優先於本機 CSV。
- ESG 與財務資料一律依「公告日」對齊：某天只會用到當天以前已公告的資料。
  TEJ 用「TESG評等公告日」；`data/raw/local/` 裡的 CSV 用 `date` 欄（請填公告日）。
- 更新時只補抓缺少的日期（多抓 7 天重疊，順便修正除權息調整）。

**`data/raw/local/` 可放的檔案**（沿用 v5 格式）

| 檔名 | 欄位 |
|---|---|
| `stock_price.csv` | `date,ticker,close`（長表）或 `date,2330.TW,2317.TW,…`（寬表），可另有 open/high/low/volume |
| `etf_prices.csv` | 同上 |
| `esg_scores.csv` | `date,ticker,esg_total,e_score,s_score,g_score,controversy_score,carbon_intensity` |
| `financials.csv` | `date,ticker,roe,roa,pb,pe,debt_ratio,eps` |

### TEJ ESG 歷史資料
目前 `data/raw/tej/` 有 2022/12 ～ 2026/06 共 8 期 TESG 評等（半年一期，公告日約每年 5 月初、11 月初），
約 1,850～1,970 家公司。回測時每個調倉日只會用到「當時最新已公告」的那一期。
之後有新一期，從 TEJ Pro 匯出（.xlsx 直接放即可）丟進 `data/raw/tej/`，重複的期別會自動去除。
在 2022-11-01 以前的回測期間沒有 ESG：AI+ESG 等同單純 AI、單純 ESG 持有現金（畫面會提示）。
進階設定中的「用最新一期回填」可以當對照組，但它有前視偏差，不能當正式結果。

## 方法摘要

| 項目 | 做法 |
|---|---|
| 股票池 | 預設近 20 個交易日平均成交金額前 300 大（含市值前 50 大，清單存在 data/processed/universe.csv）；`--universe core` 只抓前 50 大；`--universe tej` 為所有有 TEJ 評等的上市櫃普通股（排除 ETF、權證、特別股） |
| 特徵 | 5/20/60 日動能、20 日波動、月線／季線乖離、本益比、淨值比、殖利率（＋本機財報欄位） |
| 預測目標 | 未來 21 個交易日（一個月）報酬減去當天全體平均 |
| 模型 | Random Forest / XGBoost / 兩者平均，**滾動式訓練**（每 3 個月重訓），只用訓練當天已知結果的樣本 |
| 單純 AI | 預測分數最高的 N 檔（預設 15 檔） |
| AI+ESG | 排除爭議分數 > 3、EPS < 0 後，(1−w)×AI 排名 + w×ESG 排名（w 預設 0.3） |
| 單純 ESG | 排除條件後 ESG 總分最高的 N 檔 |
| 風險控制 | ① 不買跌破年線（200 日均線）的股票 ② 不買近 60 日波動最高的 20% ③ 加權指數跌破年線時持股減半（每天收盤檢查）④ 預設分散到 15 檔。可在左側關閉比較 |
| 回測 | **固定每月**最後一個交易日收盤換股、隔天起算報酬、持有期間權重漂移；等權或集中加權；**一律扣**手續費 0.1425%×2 + 證交稅 0.3% |
| 績效 | 累積／幾何年化報酬、年化波動、Sharpe（扣無風險利率 1%）、最大回撤、日報酬平均與變異數 |

## 專案結構

```
app.py                  首頁
pages/                  其他頁面
src/
├─ config.py            路徑、常數、預設值
├─ crawlers/            twse.py（清單、估值）、yahoo.py（股價，批次下載）
├─ loaders/             tej.py、local.py
├─ store.py             增量更新、合併、Dataset
├─ features.py          技術指標、依公告日對齊
├─ models.py            模型與滾動訓練
├─ backtest.py          選股規則、回測引擎、交易成本
├─ pipeline.py          串起整個流程（網頁與指令列共用）
├─ analysis.py          產業趨勢、法人排行、條件檢查表
├─ metrics.py           統一的績效計算
└─ ui/                  共用側邊欄、快取、圖表
scripts/                update_data.py、run_backtest.py、auto_push.py（改動自動推上網站）、各種 .bat 捷徑
tests/                  test_core.py（邏輯與前視偏差檢查）、smoke_ui.py（每頁跑一遍）
archive/                舊版程式（僅供對照，不再使用）
```

## 和舊版的主要差異

- 修正前視偏差：ESG 不再往回填到公告以前；選股後隔天才開始算報酬；訓練資料不含測試期結果。
- 爬蟲改成批次下載＋增量更新，不再每次覆蓋 `stock_price.csv`。
- 股票清單排除 ETF（舊版會把 0050、0056 當成個股）。
- 三套績效公式統一成一套。
- 「方法說明」由程式依當下設定自動產生，內容和實際做法一致。

## 變成公開網站

完整步驟見 **[DEPLOY.md](DEPLOY.md)**（GitHub → Streamlit Community Cloud，免費）。重點：

1. 先在本機跑 `update_data.py` 和 `run_backtest.py`，資料與回測存檔會一起上傳，網站一打開就有結果。
2. 雲端主機會被證交所與 Yahoo 擋，所以網站不自己抓資料：在 Streamlit Cloud 的 Secrets 設 `ESG_ALLOW_UPDATE = "0"`，畫面就不會出現「更新資料」按鈕。
3. 公開網站用 300 檔股票池（prices.csv 約 30 MB，低於 GitHub 單檔 100 MB 上限）；1,900 檔會超過上限，免費版記憶體也不夠。
4. 要更新網站資料：本機重跑上面兩個指令，再 `git push`，網站會自動重新部署。
