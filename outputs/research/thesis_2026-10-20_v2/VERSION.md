# 研究版本凍結紀錄

| 項目 | 內容 |
|---|---|
| 版本標籤（git tag） | thesis-v2-2026-10-20 |
| 研究版本代號（run_id） | thesis_2026-10-20_v2 |
| 凍結日期 | 2026-11-23 |
| 資料截點 | 2026-10-20 |
| 主策略設定 | Random Forest、Top 20 等權、每 2 週調倉、T 日收盤後訊號、T+1 開盤成交、TEJ 除權息調整價格 |
| 原始基準版本 | thesis_2026-10-20（保留，不再修改） |
| 設定檔 SHA-256 | 56107c3c8ecd19c106b6ca44043dcee612423bdf444e747e1780730364790604 |
| manifest.json SHA-256 | d85f831f1348e82b411ed5ca729efa2e47b34b48ffaa37dc448694d3da23f027 |
| 輸入資料檔 | 16 項（雜湊值見 manifest.json） |
| 程式檔 | 32 個（雜湊值見 manifest.json） |
| 輸出表格 | 19 個（tables/） |

規則：
1. 本資料夾之結果即論文第三、四章所用之數字，不再覆寫；`run_research.py` 與 `run_market_state_tests.py` 偵測到本版本已存在時會拒絕執行（除非加 `--overwrite`）。
2. 任何程式、資料或設定之修改，一律在 research_config.json 改用新的 run_id 另行產出，並與本版本比較。
3. 事後新增之功能（大盤狀態特徵、短期轉弱減碼）僅屬探索性補充分析，不取代主策略。

## 輸出表格雜湊值
| 檔案 | SHA-256 |
|---|---|
| tables/table_3_3_universe_summary.csv | 617cd479dd6880bb6599f466482bedc48d246d38ee0ea0cc7dae8d21fd98cd0f |
| tables/table_3_5_descriptive.csv | 616018563fbd51f6e19466d8ee6a54ecd99338f91a82ccf7631c75ca91a26143 |
| tables/table_3_7_period_split.csv | 04ec62c455b9d4ba813fc9d8112b36b6c8b48e1a47e9e03b798ae9af684bd2ec |
| tables/table_3_8_parameter_trials.csv | fa3a4973fd21e759f12122bf843e3dce4f4e23ab4790af4cd8f9a7c942ab68d8 |
| tables/table_4_10_esg_quality.csv | c1f7043e915b13c31537111aacbc7476c46e066c32d9ed5984131f79fb7d474f |
| tables/table_4_11d_execution_timing.csv | 97a9e9d700bab6d33a4ed0ea8dfd930e6b1bf8ca67659ced482b96ce5b2aba81 |
| tables/table_4_15_market_state_tests.csv | f4df6582365423d63d514e7bb5505b11104ca52ee3806b1087b1014738d2cb3d |
| tables/table_4_1_performance.csv | 8ac46851d4adde63ba74d15dc98b86da80e6c0686983cd87c24024e26009cc0c |
| tables/table_4_2_yearly.csv | 073ee24aef5cd1965ffd1cb0d8b699f7fbc8e9ef57725a1a1d9432ccd73aa215 |
| tables/table_4_2b_survivorship_split.csv | 325bf45d91eab774e7e08c1ad3e92a1deebf74a720ac1150fcf3dd7d05207031 |
| tables/table_4_3_regimes.csv | 4d01f9b2851ba4a680384e1f93d5d935e0b8018d8beab3266137394933d5cf81 |
| tables/table_4_4_capture.csv | 798dbd68c726e4fe78f2f992bc0e5755bdab86fbf537c42de284d2dcf774fdcf |
| tables/table_4_5_capm_hac.csv | f1e57bf22b0e5ad9d76aadf7ca16bfea3575fdec23dd844252c2d6b746e103b6 |
| tables/table_4_6_diff_hac.csv | 55d2108b5fac4e98179a956ead15d638db819c916759c8d462349c2bcf9cf973 |
| tables/table_4_7_model_skill.csv | 5fc00ac599a8669ca3d240d4f181bea008b48695eed575752420df4916858aa2 |
| tables/table_4_8a_importance_distribution.csv | 4df99f2caa56fb45bda7d2fc7ee4b81550800a458ceba116bbf9b09cf620ba7b |
| tables/table_4_8b_permutation_importance.csv | ffe87baab89c3222a06d54ccaa97d8d02ba4d25de5bfe3ff4df532652e4f8eff |
| tables/table_4_9a_turnover_cost.csv | 7ff16e11394c5e2e891497d3c95de8ae274c9cd9ecfaa0946c6a2e38b7fd7a81 |
| tables/table_4_9b_slippage.csv | b7cddc0b2df5967cfee4b2f01b376dab04d814a08332001119d8d91a65ad90fa |
