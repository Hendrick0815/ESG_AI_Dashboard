# ESG-AI Smart Portfolio Dashboard

🌿 **台灣 ESG 智能選股平台** — v5

[![Streamlit App](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://share.streamlit.io)

---

## 功能特色

| 功能 | 說明 |
|------|------|
| 🏦 選股母池 | 台灣大盤全上市股（TWSE 自動抓取） |
| 🤖 AI 模型 | Random Forest / XGBoost 預測未來報酬 |
| 🌱 ESG 評分 | 爭議排除、ESG 中位數過濾、多因子排名 |
| 📊 績效比較 | 與台灣加權指數（^TWII）、0050 等 ETF 比較 |
| 🔍 模型解釋 | 特徵重要性、SHAP 分析 |
| 🗓️ 回測 | 樣本外期間、每 5 個交易日調倉，與 ETF 同起點比較 |

---

## 本機執行

```bash
# 安裝依賴
pip install -r requirements.txt

# 啟動
streamlit run app_v5.py
```

---

## 部署到 Streamlit Cloud

1. 將此資料夾上傳到 GitHub
2. 前往 [share.streamlit.io](https://share.streamlit.io)
3. 登入並選擇此 GitHub repository
4. 主程式選 `app_v5.py`，點 Deploy

---

## 資料說明

- **Yahoo Finance 模式**：自動從網路抓取股價（需網路連線）
- **本機 CSV 模式**：將 `data/` 資料夾放入以下檔案：
  - `stock_price.csv`
  - `esg_scores.csv`（選填）
  - `financials.csv`（選填）
  - `etf_prices.csv`（選填）

---

## 技術架構

```
Streamlit → Yahoo Finance (yfinance)
         → TWSE OpenAPI（上市股清單）
         → scikit-learn / XGBoost（AI 選股）
         → Plotly（互動圖表）
```
