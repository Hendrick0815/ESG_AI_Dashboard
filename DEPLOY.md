# 把這個專案變成公開網站（Streamlit Community Cloud）

這個程式本來就是網站，只是目前跑在你的電腦上（`localhost`）。以下步驟把它放上雲端，
變成一個任何人都能打開的網址，例如 `https://esg-ai-tw.streamlit.app`。全部免費。

---

## 一、先在本機準備好資料（10 分鐘）

網站上不會自己抓資料（雲端主機會被證交所和 Yahoo 擋），所以要先在自己電腦準備好，
連同程式一起上傳。

```powershell
cd C:\Users\hendr\OneDrive\Desktop\esg-dashboard

# 1. 抓最新股價（公開網站建議用 50 檔，檔案小、跑得快）
py scripts/update_data.py --universe core --start 2022-09-01

# 2. 先把預設設定的回測算好存檔，網站一打開就有結果，不用等
py scripts/run_backtest.py
```

> **股票池為什麼建議 50 檔？** 1,900 檔的 `prices.csv` 會超過 100 MB，GitHub 單檔上限就是 100 MB，
> 而且免費版雲端主機只有約 1 GB 記憶體，跑 1,900 檔容易當掉。50 檔的檔案約 4 MB，很安全。

---

## 二、上傳到 GitHub（第一次約 15 分鐘）

沒有 GitHub 帳號的話先到 [github.com](https://github.com) 註冊。

**方法 A：用 GitHub Desktop（不用打指令，推薦）**

1. 下載安裝 [GitHub Desktop](https://desktop.github.com) 並用 GitHub 帳號登入。
2. `File → Add local repository` → 選 `esg-dashboard` 資料夾 → 它會問要不要建立 repository，選 `create a repository`。
3. Name 填 `esg-ai-dashboard`，其他不用改，按 `Create repository`。
4. 左邊會列出所有檔案，下方 Summary 填 `first commit`，按 `Commit to main`。
5. 右上按 `Publish repository`。**把「Keep this code private」的勾拿掉**（Streamlit 免費版要公開的 repo），按 Publish。

**方法 B：用指令**

```powershell
cd C:\Users\hendr\OneDrive\Desktop\esg-dashboard
git init
git add .
git commit -m "first commit"
git branch -M main
git remote add origin https://github.com/<你的帳號>/esg-ai-dashboard.git
git push -u origin main
```

上傳前可以檢查一下：`data/raw/tej/`（ESG 評等）和 `data/processed/`（股價）這兩個資料夾應該都有被包含進去。

---

## 三、部署到 Streamlit Community Cloud（5 分鐘）

1. 到 [share.streamlit.io](https://share.streamlit.io)，用 GitHub 帳號登入並授權。
2. 按 `Create app` → `Deploy a public app from GitHub`。
3. 填寫：
   - **Repository**：`<你的帳號>/esg-ai-dashboard`
   - **Branch**：`main`
   - **Main file path**：`app.py`
   - **App URL**：自己取一個好記的，例如 `esg-ai-tw`
4. 點 **Advanced settings**：
   - **Python version** 選 `3.12`（比較穩定，套件都有現成的安裝檔）
   - **Secrets** 欄位貼上這一行，讓網站不顯示「更新資料」按鈕：
     ```toml
     ESG_ALLOW_UPDATE = "0"
     ```
5. 按 `Deploy`。第一次要等 3～5 分鐘安裝套件，之後網址就能用了。

---

## 四、以後要更新網站上的資料

```powershell
cd C:\Users\hendr\OneDrive\Desktop\esg-dashboard
py scripts/update_data.py            # 抓新的股價
py scripts/run_backtest.py           # 重算並存檔
```
然後用 GitHub Desktop 按 `Commit` → `Push`（或 `git add . && git commit -m "update data" && git push`）。
推上去之後網站會自動重新部署，大約一兩分鐘就會看到新資料。

TEJ 有新一期 TESG 時，把匯出的檔案丟進 `data/raw/tej/`，一樣重跑上面兩行再 push。

---

## 五、幾個要知道的事

| 事項 | 說明 |
|---|---|
| 網址 | 只能用 `xxx.streamlit.app`，免費版不支援自訂網域 |
| 休眠 | 超過幾天沒人開，網站會休眠。下次有人打開時會自動醒來，第一次載入約 30 秒 |
| 記憶體 | 免費版約 1 GB。50 檔股票很夠用；如果之後想放 1,900 檔，要改用付費方案或 Hugging Face Spaces |
| 程式碼公開 | 免費版要求 repo 是 public，所以程式碼和上傳的資料任何人都看得到 |
| TEJ 資料 | 你確認學校授權允許公開。如果之後改變主意，把 `.gitignore` 裡 `data/raw/tej/*` 那兩行的註解拿掉，再從 GitHub 刪掉該資料夾即可 |
| 免責聲明 | 首頁最下方已經加上「學術專題、非投資建議」的聲明 |

### 想加密碼保護？
在 Streamlit Cloud 的 Secrets 加一行 `APP_PASSWORD = "你的密碼"`，程式再加一段簡單的密碼檢查即可。
需要的話再說，我可以補上這段程式。

### 其他部署選項

| 平台 | 適合情況 | 費用 |
|---|---|---|
| **Streamlit Community Cloud** | 現在這個做法，最快最簡單 | 免費 |
| Hugging Face Spaces | 想放更多股票、需要較多記憶體 | 免費（規格較好），升級另計 |
| Render / Railway | 想用自訂網域、想讓網站自己定時抓資料 | 每月數美元起 |
