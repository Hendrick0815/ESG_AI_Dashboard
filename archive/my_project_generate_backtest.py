import yfinance as yf
import pandas as pd
import numpy as np
from datetime import date, timedelta
import os
import json
import io
import traceback
import sys

# 強制設定 stdout 編碼，避免 PowerShell 印出中文時報錯直接閃退
sys.stdout.reconfigure(encoding='utf-8')

try:
    from sklearn.ensemble import RandomForestClassifier
    from xgboost import XGBClassifier
except ImportError:
    print("尚未安裝機器學習套件！請在終端機輸入: pip install scikit-learn xgboost")
    class DummyClassifier:
        def fit(self, *args): pass
        def predict_proba(self, X): return np.random.rand(len(X), 2)
        @property
        def feature_importances_(self): return np.random.rand(8)
    RandomForestClassifier = DummyClassifier
    XGBClassifier = DummyClassifier

def get_stock_data(tickers, start_date, end_date):
    print(f"正在下載 {len(tickers)} 檔權值股資料以供 AI 訓練...")
    data = yf.download(tickers, start=start_date, end=end_date, group_by='ticker', progress=False)
    
    df_list = []
    for ticker in tickers:
        try:
            if isinstance(data.columns, pd.MultiIndex):
                df = data[ticker].copy()
            else:
                if len(tickers) == 1: df = data.copy()
                else:
                    df = data[[c for c in data.columns if c.endswith(ticker)]].copy()
                    df.columns = [c.split('_')[0] for c in df.columns]

            if df.empty or df['Close'].isnull().all(): continue
            
            df = df.reset_index()
            if pd.api.types.is_datetime64tz_dtype(df['Date']):
                df['Date'] = df['Date'].dt.tz_localize(None)
                
            df['Ticker'] = ticker
            
            df['Return_1M'] = df['Close'].pct_change(20)
            df['Return_3M'] = df['Close'].pct_change(60)
            df['Volatility_20D'] = df['Close'].pct_change().rolling(20).std() * np.sqrt(252)
            df['MA_20'] = df['Close'].rolling(20).mean()
            df['Price_to_MA'] = df['Close'] / df['MA_20']
            
            df['Future_1M_Return'] = df['Close'].shift(-20) / df['Close'] - 1
            
            df_list.append(df.dropna(subset=['Return_1M', 'Return_3M', 'Volatility_20D', 'Price_to_MA']))
        except Exception as e:
            continue
            
    if not df_list: return pd.DataFrame()
    return pd.concat(df_list, ignore_index=True)

def train_and_backtest_ai_model():
    print("="*60)
    print("啟動 AI-ESG 選股模型回測引擎")
    print("="*60)
    
    universe = [
        # 原本的 20 檔
        "2330.TW", "2317.TW", "2454.TW", "2881.TW", "2308.TW",
        "2882.TW", "2412.TW", "2891.TW", "1301.TW", "1303.TW",
        "2886.TW", "3231.TW", "2382.TW", "2884.TW", "1216.TW",
        "2002.TW", "1101.TW", "2892.TW", "2880.TW", "2885.TW",
        # 新增 30 檔台灣大型權值股 (湊齊約 50 檔)
        "2303.TW", "2883.TW", "2887.TW", "2890.TW", "2888.TW",
        "5880.TW", "1102.TW", "1402.TW", "2105.TW", "2207.TW",
        "2301.TW", "2324.TW", "2345.TW", "2357.TW", "2379.TW",
        "2395.TW", "2408.TW", "2603.TW", "2609.TW", "2615.TW",
        "2912.TW", "3008.TW", "3034.TW", "3045.TW", "3711.TW",
        "4904.TW", "4938.TW", "5871.TW", "6669.TW", "9910.TW"
    ]
    
    end_date = date.today()
    start_date = end_date - timedelta(days=365*4) 
    
    # 預先讀取本地 ESG 檔案，將全市場最高分的前 50 檔加入爬蟲股票池中
    esg_file = "taiwan_esg_data.csv"
    esg_top_tickers = []
    if os.path.exists(esg_file):
        with open(esg_file, "rb") as f:
            raw_data = f.read()
        try:
            decoded_data = raw_data.decode("utf-8-sig")
        except UnicodeDecodeError:
            decoded_data = raw_data.decode("cp950", errors="replace")
        df_esg_tmp = pd.read_csv(io.StringIO(decoded_data))
        col_map = {"代號": "Ticker", "公司代碼": "Ticker", "TESG分數": "ESG_Score", "總分": "ESG_Score"}
        df_esg_tmp = df_esg_tmp.rename(columns=col_map)
        if "Ticker" in df_esg_tmp.columns and "ESG_Score" in df_esg_tmp.columns:
            df_esg_tmp["Ticker"] = df_esg_tmp["Ticker"].astype(str).str.strip() + ".TW"
            top_esg = df_esg_tmp.groupby("Ticker")["ESG_Score"].last().nlargest(50)
            esg_top_tickers = top_esg.index.tolist()
            print(f"成功從本地 ESG 檔案提取 {len(esg_top_tickers)} 檔高分標的加入爬蟲名單！")
            
    # 合併原本的權值股與 ESG 菁英股，並去除重複
    universe = list(set(universe + esg_top_tickers))
    print(f"最終需下載的股票池總數: {len(universe)} 檔")
    
    df_all = get_stock_data(universe, start_date, end_date)
    if df_all.empty:
        print("資料下載失敗。")
        return
        
    # 整合真實 ESG 資料
    esg_file = "taiwan_esg_data.csv"
    if os.path.exists(esg_file):
        with open(esg_file, "rb") as f:
            raw_data = f.read()
        try:
            decoded_data = raw_data.decode("utf-8-sig")
        except UnicodeDecodeError:
            decoded_data = raw_data.decode("cp950", errors="replace")
        df_esg = pd.read_csv(io.StringIO(decoded_data))
        col_map = {"代號": "Ticker", "公司代碼": "Ticker", "TESG分數": "ESG_Score", "總分": "ESG_Score"}
        df_esg = df_esg.rename(columns=col_map)
        
        if "Ticker" in df_esg.columns and "ESG_Score" in df_esg.columns:
            df_esg["Ticker"] = df_esg["Ticker"].astype(str).str.strip() + ".TW"
            
            # 動態找尋日期欄位 (支援 TESG評等公告日、年月、日期、Date 等)
            date_col = next((c for c in df_esg.columns if "年月" in c or "日期" in c or "Date" in c or "公告日" in c), None)
            
            if date_col:
                print(f"找到 ESG 日期欄位: {date_col}，進行時間序列合併...")
                # 確保轉換為字串後再轉 datetime，避免格式錯誤
                df_esg[date_col] = df_esg[date_col].astype(str).str.replace(r'[^\d/:-]', '', regex=True)
                df_esg["Date"] = pd.to_datetime(df_esg[date_col], errors='coerce')
                df_esg = df_esg.dropna(subset=['Date'])
                
                def process_esg(group):
                    try:
                        ticker_name = group.name if hasattr(group, 'name') else None
                        group = group.set_index('Date').sort_index()
                        group_monthly = group.resample('MS').first()
                        today = pd.Timestamp(date.today())
                        if group_monthly.empty or pd.isna(group_monthly.index.min()):
                            return group.reset_index()
                            
                        full_date_range = pd.date_range(start=group_monthly.index.min(), end=today, freq='D')
                        group_filled = group_monthly.reindex(full_date_range).ffill()
                        group_filled.index.name = 'Date'
                        
                        if ticker_name is not None:
                            group_filled['Ticker'] = ticker_name
                        elif 'Ticker' in group.columns and not group.empty:
                            group_filled['Ticker'] = group['Ticker'].iloc[0]
                            
                        return group_filled.reset_index()
                    except Exception as e:
                        print(f"處理 ESG 發生錯誤: {e}")
                        return group.reset_index()

                if not df_esg.empty:
                    df_esg_filled = df_esg.groupby("Ticker", group_keys=False).apply(process_esg)
                    df_all['Date'] = pd.to_datetime(df_all['Date'])
                    df_all = pd.merge(df_all, df_esg_filled[['Date', 'Ticker', 'ESG_Score']], on=['Date', 'Ticker'], how='left')
                    
                    # 向下與向上填補缺失值 (確保過去的日期也能吃得到最新的 ESG 分數)
                    df_all['ESG_Score'] = df_all.groupby('Ticker')['ESG_Score'].ffill().bfill().fillna(50.0)
                else:
                    df_all['ESG_Score'] = 50.0
            else:
                print("未找到 ESG 日期欄位，使用單一最新分數...")
                esg_dict = df_esg.groupby("Ticker")["ESG_Score"].last().to_dict()
                df_all['ESG_Score'] = df_all['Ticker'].map(esg_dict).fillna(50.0)
        else:
            df_all['ESG_Score'] = 50.0
    else:
        df_all['ESG_Score'] = 50.0
    
    df_all['Target'] = (df_all['Future_1M_Return'] > 0.02).astype(int)
    
    features = ['Return_1M', 'Return_3M', 'Volatility_20D', 'Price_to_MA']
    features_esg = features + ['ESG_Score']
    
    df_all = df_all.sort_values('Date')
    
    split_idx = int(len(df_all) * 0.7)
    train_data = df_all.iloc[:split_idx]
    test_data = df_all.iloc[split_idx:]
    
    print("正在訓練 AI 模型 (XGBoost + Random Forest 集成)...")
    xgb_model = XGBClassifier(n_estimators=100, max_depth=3, learning_rate=0.1, random_state=42, eval_metric='logloss')
    rf_model = RandomForestClassifier(n_estimators=100, max_depth=5, random_state=42)
    
    xgb_model.fit(train_data[features], train_data['Target'])
    rf_model.fit(train_data[features], train_data['Target'])
    
    prob_xgb = xgb_model.predict_proba(test_data[features])[:, 1]
    prob_rf = rf_model.predict_proba(test_data[features])[:, 1]
    
    # 共同分析：將兩個模型的預測機率平均
    test_data['Prob_Pure_AI'] = (prob_xgb + prob_rf) / 2.0
    
    print("正在整合 AI 與 ESG 混合因子...")
    test_data['Prob_AI_ESG'] = test_data['Prob_Pure_AI'] * 0.7 + (test_data['ESG_Score'] / 100.0) * 0.3
    
    TRANSACTION_COST = 0.004425 
    
    df_all['Daily_Return'] = df_all.groupby('Ticker')['Close'].pct_change()
    test_daily = df_all.iloc[split_idx:].copy()
    
    returns_matrix = test_daily.pivot(index='Date', columns='Ticker', values='Daily_Return').fillna(0)
    ai_esg_prob = test_data.pivot(index='Date', columns='Ticker', values='Prob_AI_ESG').fillna(0)
    pure_ai_prob = test_data.pivot(index='Date', columns='Ticker', values='Prob_Pure_AI').fillna(0)
    esg_score_matrix = test_data.pivot(index='Date', columns='Ticker', values='ESG_Score').fillna(0)
    
    nv_ai_esg, nv_pure_ai, nv_pure_esg = 1.0, 1.0, 1.0
    net_values_ai_esg, net_values_pure_ai, net_values_pure_esg, dates = [], [], [], []
    
    # 儲存目前的權重配置與標的
    weights_ai_esg, weights_pure_ai, weights_pure_esg = {}, {}, {}
    
    for dt, row in ai_esg_prob.iterrows():
        is_rebalance_day = (dt.month != ai_esg_prob.index[ai_esg_prob.index.get_loc(dt)-1].month) if ai_esg_prob.index.get_loc(dt) > 0 else True
        
        if is_rebalance_day:
            # 取出前 20 名
            top_ai_esg_s = row.nlargest(20)
            top_pure_ai_s = pure_ai_prob.loc[dt].nlargest(20)
            top_pure_esg_s = esg_score_matrix.loc[dt].nlargest(20)
            
            # 權重配置 (高純度排名加權法：前幾名給予極高權重，後段班給予低權重)
            def calc_weights(series):
                if series.empty: return {}
                sorted_s = series.sort_values(ascending=False)
                # 為 20 檔股票設計的指數型遞減權重 (總和 1.0)
                # 第一名 30%，前五名囊括 69% 的資金，其餘作為防禦性配置
                w_list = [0.30, 0.15, 0.10, 0.08, 0.06, 0.05, 0.04, 0.04, 0.03, 0.03, 
                          0.02, 0.02, 0.02, 0.01, 0.01, 0.01, 0.01, 0.01, 0.005, 0.005]
                
                # 若遇到標的不足 20 檔的極端狀況，按比例重新正規化
                w_slice = w_list[:len(sorted_s)]
                w_sum = sum(w_slice)
                w_norm = [w / w_sum for w in w_slice]
                
                return {k: w_norm[i] for i, k in enumerate(sorted_s.index)}
                
            new_w_ai_esg = calc_weights(top_ai_esg_s)
            new_w_pure_ai = calc_weights(top_pure_ai_s)
            new_w_pure_esg = calc_weights(top_pure_esg_s)
            
            # 若為空則維持原本
            if not new_w_ai_esg: new_w_ai_esg = weights_ai_esg
            if not new_w_pure_ai: new_w_pure_ai = weights_pure_ai
            if not new_w_pure_esg: new_w_pure_esg = weights_pure_esg
            
            # 計算換股週轉率 (Turnover = sum(abs(新權重 - 舊權重)) / 2)
            def calc_turnover(old_w, new_w):
                if not old_w: return 1.0
                all_keys = set(old_w.keys()).union(new_w.keys())
                return sum(abs(new_w.get(k, 0) - old_w.get(k, 0)) for k in all_keys) / 2.0
                
            turn_ai_esg = calc_turnover(weights_ai_esg, new_w_ai_esg)
            turn_pure_ai = calc_turnover(weights_pure_ai, new_w_pure_ai)
            turn_pure_esg = calc_turnover(weights_pure_esg, new_w_pure_esg)
            
            nv_ai_esg *= (1 - turn_ai_esg * TRANSACTION_COST)
            nv_pure_ai *= (1 - turn_pure_ai * TRANSACTION_COST)
            nv_pure_esg *= (1 - turn_pure_esg * TRANSACTION_COST)
            
            weights_ai_esg, weights_pure_ai, weights_pure_esg = new_w_ai_esg, new_w_pure_ai, new_w_pure_esg
            
        # 依照權重計算每日報酬率
        def get_ret(w_dict, dt):
            return sum(returns_matrix.loc[dt, k] * v for k, v in w_dict.items()) if w_dict else 0.0
            
        ret_ai_esg = get_ret(weights_ai_esg, dt)
        ret_pure_ai = get_ret(weights_pure_ai, dt)
        ret_pure_esg = get_ret(weights_pure_esg, dt)
        
        nv_ai_esg *= (1 + ret_ai_esg)
        nv_pure_ai *= (1 + ret_pure_ai)
        nv_pure_esg *= (1 + ret_pure_esg)
        
        net_values_ai_esg.append(nv_ai_esg)
        net_values_pure_ai.append(nv_pure_ai)
        net_values_pure_esg.append(nv_pure_esg)
        dates.append(dt)
        
    output_df = pd.DataFrame({
        "Date": dates, 
        "AI_ESG_Net_Value": net_values_ai_esg,
        "Pure_AI_Net_Value": net_values_pure_ai,
        "Pure_ESG_Net_Value": net_values_pure_esg
    })
    output_df.to_csv("ai_strategy_returns.csv", index=False)
    
    components = {
        "AI_ESG": {t: round(w * 100, 2) for t, w in weights_ai_esg.items()},
        "Pure_AI": {t: round(w * 100, 2) for t, w in weights_pure_ai.items()},
        "Pure_ESG": {t: round(w * 100, 2) for t, w in weights_pure_esg.items()}
    }
    with open("strategy_components.json", "w", encoding="utf-8") as f:
        json.dump(components, f, ensure_ascii=False, indent=4)
        
    print("\n" + "="*60)
    print("成功產生最新回測數據與成分股 (ai_strategy_returns.csv, strategy_components.json)")

if __name__ == "__main__":
    try:
        print(">>> 程式已成功觸發，正在初始化...")
        train_and_backtest_ai_model()
    except Exception as e:
        print("\n[發生錯誤] 程式執行中斷，錯誤詳細資訊如下：")
        traceback.print_exc()
        with open("error_log.txt", "w", encoding="utf-8") as f:
            f.write(f"發生錯誤: {str(e)}\n")
            traceback.print_exc(file=f)
