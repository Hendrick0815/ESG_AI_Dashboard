"""答辯與重現資料包：一頁答辯摘要、預期問答、設定清單、重現步驟、樣本外追蹤規劃。

數字全部由已凍結之研究版本（research_config.json 的 run_id）表格讀取，不手動輸入。
輸出：outputs/research/<run_id>/report/答辯與重現資料.docx／.pdf
用法：python scripts/research/build_defense_pack.py
"""
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.argv = sys.argv[:1]                       # build_report 以 argv[1] 指定版本；本程式一律用設定檔之 run_id
import build_report as B  # noqa: E402
from report_lib import Report  # noqa: E402

t41, CFG, man = B.t41, B.CFG, B.man
pct, num, pv = B.pct, B.num, B.pv
OUT = B.OUT


def main():
    a, ae, e = t41.loc["單純 AI"], t41.loc["AI+ESG"], t41.loc["規則式 ESG 篩選"]
    x_ai, x_ae, x_e = B.d46("單純 AI", "00850"), B.d46("AI+ESG", "00850"), B.d46("規則式 ESG 篩選", "00850")
    t411d = B.rd("table_4_11d_execution_timing")
    ce = t411d[t411d["成交時點"].str.contains("收盤")].set_index("投組")["年化報酬"] if len(t411d) else {}
    sl = B.t49b
    sk = B.t47.set_index("指標")
    base_id = CFG.get("baseline_run_id")
    b41 = None
    bp = B.ROOT / "outputs" / "research" / str(base_id) / "tables" / "table_4_1_performance.csv"
    if base_id and bp.exists():
        b41 = B.pd.read_csv(bp).set_index("投組").rename(index={"單純 ESG": "規則式 ESG 篩選"})

    R = Report()
    from docx.shared import Cm
    import report_lib
    sec = R.doc.sections[0]
    sec.left_margin = sec.right_margin = Cm(2.0)
    sec.top_margin = sec.bottom_margin = Cm(1.6)
    report_lib.TEXT_W = Cm(17.0)
    # ======================= 一、一頁答辯摘要
    R.h(1, "答辯與重現資料")
    R.p(f"研究題目：{B.TITLE}｜研究版本 {CFG['run_id']}（凍結於 2026-11-23，版本標籤 thesis-v2-2026-10-20）｜資料截點 {B.cut}", indent=False, size=10, after=2)
    R.h(2, "一、一頁答辯摘要")
    F = 10      # 字級（本頁須容納於一頁）
    from report_lib import spacing, rich, add_text
    from docx.shared import Pt

    def CB(items, size=F):          # 行距較緊之項目符號（本頁專用）
        for it in items:
            if not it:
                continue
            q = R.doc.add_paragraph()
            spacing(q, 0, 1, 1.25, left=Pt(18), hanging=Pt(12))
            add_text(q, "• ", size=size)
            rich(q, it, size=size)

    def HP(text):
        q = R.doc.add_paragraph()
        spacing(q, 4, 1, 1.25)
        rich(q, text, size=F)
    HP("**研究主張：**" + B.claim_txt())
    HP("**1. 研究貢獻**")
    CB([
        "建立一套可重現的 AI 加 ESG 選股回測架構：逐期重建股票池（含下市股）、資料依可得日對齊、T+1 開盤成交、TEJ 除權息調整價格，設定與資料版本凍結並可由程式重跑。",
        "以同一架構誠實比較 AI、ESG 篩選與市售 ESG ETF，並量化股票池建構、成交時點與交易成本對結論的影響。",
    ])
    HP(f"**2. 主要發現**（探索性歷史回測期 {B.start_eval}～{B.cut}，{B.n_days} 個交易日）")
    rows = []
    for k in B.ORDER:
        if k not in t41.index:
            continue
        r = t41.loc[k]
        x = B.d46(k, "00850") if k in B.STR else None
        rows.append([k, pct(r["年化報酬"]), num(r["Sharpe"]), pct(r["最大回撤"]), pv(x["p"]) if x is not None else "—"])
    R.table(["投組", "年化報酬", "Sharpe", "最大回撤", "相對 00850 p 值"], rows, [3.0, 1.8, 1.4, 1.8, 2.2], "lrrrr", size=9)
    CB([
        f"AI 與 ETF 差異不顯著（單純 AI p = {pv(x_ai['p'])}、AI+ESG p = {pv(x_ae['p'])}）；AI+ESG 持股加權 TESG {num(B.t410.loc['AI+ESG', 'esg_total'], 1)}，高於單純 AI 的 {num(B.t410.loc['單純 AI', 'esg_total'], 1)}；規則式 ESG 篩選 Beta {num(e['Beta'])}、回撤最小。",
        (f"以資料截點當時前 300 大回推股票池，單純 AI 年化 {pct(B.cu.loc['單純 AI', '年化報酬'])}（後見之明偏誤）；" if B.cu is not None else "")
        + (f"若以訊號日收盤成交則為 {pct(ce.get('單純 AI'))}；每邊 20 bps 滑價即落後 00850。" if len(ce) else ""),
    ])
    HP("**3. 不能主張的內容**")
    CB([
        "不能主張 AI 或 AI+ESG 優於 ETF、策略有效或具顯著超額報酬；p 值僅作樣本內描述，且未做多重比較校正。",
        "探索性歷史回測期曾參與模型與參數選擇，不是樣本外驗證；結果不代表未來可實現報酬。",
        "大盤狀態特徵與短期轉弱減碼為事後探索性補充分析，不取代主策略；網站展示頁（現存股票池）不是研究結果。",
    ])
    HP("**4. 研究限制**")
    CB([
        "參數選擇與回測期重疊；停牌期間假設價格不變仍可成交；未考慮開盤價格衝擊與容量限制。",
        "TEJ TESG 自 2022-11 起僅 8 期；ETF 歷史成分無法取得；加權指數不含股利。",
    ])
    HP("**5. 未來樣本外驗證計畫**")
    CB([
        "凍結版本 thesis-v2-2026-10-20 之模型與規則，自 2026-10-21 起每 2 週記錄一次，至少追蹤 1 年（約 26 次調倉）。",
        "事先只指定一項主要檢定：AI+ESG 相對 00850 日報酬差（Newey-West，雙尾 5%）；結果不論顯著與否皆完整報告（詳見第五節）。",
    ])
    R.page_break()

    # ======================= 二、預期問答
    R.h(2, "二、預期問答")
    s20 = sl[(sl["slippage_bps"] == 20) & (sl["投組"] == "單純 AI")]
    qa = [
        ("修訂後的報酬比上一版低，是否代表研究失敗？",
         "本研究發現績效對股票池、成本與資料時點敏感，因此我們已把動態股票池、下市股票、T+1 開盤成交、交易成本與統計檢定納入；"
         + (f"單純 AI 年化報酬由原始基準的 {pct(b41.loc['單純 AI', '年化報酬'])} 修正為 {pct(a['年化報酬'])}。" if b41 is not None else "")
         + "目前結果屬探索性證據，下一步將以凍結參數後的新資料進行樣本外追蹤。我們不為維持高報酬而淡化偏誤。"),
        ("評估期間為何不能稱為樣本外？",
         "模型種類、持股數、調倉頻率與特徵是在涵蓋 2022-11 之後的資料上比較後選定（表 3-9），此期間已間接影響設定，因此稱為「探索性歷史回測期」，p 值只作樣本內描述。真正的樣本外檢驗留待凍結參數後的新資料（第五節）。"),
        ("AI 報酬點估計與 ETF 接近，為何不說 AI 有效？",
         f"差異未達統計顯著（相對 00850 p = {pv(x_ai['p'])}），信賴區間很寬，且對成本與時點敏感；本研究只主張架構可重現與結果之敏感性，不作「策略有效」之確認性主張。"),
        ("如何處理存活者偏誤？",
         "股票池逐期依當時成交金額重建並保留之後下市的股票；附錄 B 列出 10 檔下市（櫃）股票，下市時皆未被持有，最後收盤價出場之假設未影響結果。"),
        ("為何改為 T+1 開盤成交？影響多大？",
         f"訊號用到 T 日收盤資訊，若再以 T 日收盤價成交會含前視偏誤。改為 T+1 開盤後，單純 AI 年化由 {pct(ce.get('單純 AI'))} 降至 {pct(a['年化報酬'])}" + (f"；修訂前原始基準為 {pct(b41.loc['單純 AI', '年化報酬'])}，已保留於表 4-11 供比較。" if b41 is not None else "。") if len(ce) else ""),
        ("為何股價改用 TEJ？",
         "原先混合 Yahoo、FinMind 與交易所價格，稽核發現來源切換日有漲跌幅重複計算、除息日未加回股利等問題（影響 0.1～0.2 個百分點）；改用 TEJ 除權息調整後單一來源，並以未調整價格與櫃買中心收盤價抽樣核對一致。"),
        ("p 值有沒有多重比較問題？",
         "有。第四章共 19 項檢定，p 值未校正；策略相對基準之 17 項皆未達 5% 顯著，校正後結論不變。唯一顯著的是模型前 20 檔超額報酬（未扣成本），Bonferroni 校正後仍顯著，但屬未扣成本之模型能力指標。"),
        ("交易成本會不會吃掉報酬？",
         f"AI 策略週轉率高；每邊 20 bps 滑價時單純 AI 年化降為 {pct(s20['年化報酬'].iloc[0])}，已落後 00850（表 4-13）。" if len(s20) else "AI 策略週轉率高，滑價 10～20 bps 即落後 00850（表 4-13）。"),
        ("模型真的有選股能力嗎？",
         f"平均 Rank IC {num(sk.loc['平均 Rank IC', 'est'], 4)}（p = {pv(sk.loc['平均 Rank IC', 'p'])}）不顯著；前 20 檔每期超額報酬為正且顯著，但未扣成本，扣成本並對標 ETF 後已不顯著。" if "平均 Rank IC" in sk.index else "見表 4-9。"),
        ("大盤狀態特徵與短期轉弱減碼為何沒有納入主策略？",
         "兩者為看過結果後才新增的設定，屬事後探索性補充分析：大盤特徵未改善 Beta 與 Rank IC；減碼可降低回撤但報酬下降。未經樣本外檢驗，因此不取代主策略。"),
        ("網站數字為何與論文不同？",
         "網站首頁、策略回測等展示頁以「目前」前 300 大回測，含存活者偏誤，頁首有警示；論文主要結果只看「逐期股票池回測」頁，該頁數字固定在資料截點。"),
        ("如何確定結果可以重現？",
         "設定集中於研究設定檔；每次執行記錄設定、輸入資料與程式之 SHA-256、套件版本（manifest.json）；版本已凍結，程式拒絕覆寫既有版本。重現步驟見第四節。"),
    ]
    for q, ans in qa:
        R.p(f"**問：{q}**", indent=False, after=0)
        R.p(f"答：{ans}", indent=False)

    # ======================= 三、設定清單
    R.h(2, "三、設定清單")
    c = CFG
    rows = [
        ["研究版本／原始基準", f"{c['run_id']}／{base_id}"],
        ["資料截點", c["data_cutoff"]],
        ["期間切分", f"開發期 {c['periods']['development'][0]}～{c['periods']['development'][1]}；參數比較期 {c['periods']['validation'][0]}～{c['periods']['validation'][1]}；"
                      f"探索性歷史回測期 {c['periods']['exploratory_evaluation'][0]}～{c['periods']['exploratory_evaluation'][1]}"],
        ["股票池", f"每日以近 {c['universe']['window_days']} 日平均成交金額排名前 {c['universe']['size']} 檔普通股（交易不足 {c['universe']['min_trading_days']} 天不納入），含之後下市股票"],
        ["模型", f"{c['model']}，{c['n_estimators']} 棵樹，隨機種子 {c['random_seed']}；每 {c['retrain_every_rebalances']} 次調倉重新訓練；預測未來 {c['hold_days']} 日相對報酬"],
        ["持股與調倉", f"Top {c['top_n']} {c['weighting']}；每 {c['rebalance_weeks']} 週調倉；AI+ESG 中 TESG 權重 {c['esg_weight']:.0%}"],
        ["成交與價格", "T 日收盤後形成訊號、T+1 日開盤成交；TEJ 除權息調整後開盤價、收盤價"],
        ["交易成本", f"手續費 {c['costs']['commission']:.4%}（買賣各一次）、證交稅 {c['costs']['sell_tax']:.1%}；滑價情境 " + "、".join(f"{v * 1e4:.0f}" for v in c["slippage_grid"]) + " bps"],
        ["比較基準", "加權指數（價格指數）、0050、00850、00878（還原收盤價）"],
        ["統計", f"Newey-West 標準誤；區塊 bootstrap（區塊 20 日、2,000 次）；無風險利率 {c['risk_free_annual']:.0%}"],
        ["執行環境", f"Python {man['python']}；" + "、".join(f"{k} {v}" for k, v in man["packages"].items())],
        ["輸入資料／程式", f"{len(man['data_files_sha256'])} 項輸入資料、{len(man['code_sha256'])} 個程式檔之 SHA-256 記錄於 manifest.json"],
    ]
    R.caption("表 2　研究設定清單")
    R.table(["項目", "設定"], rows, [2.6, 9.4], "ll", size=10)

    # ======================= 四、重現步驟
    R.h(2, "四、重現步驟")
    R.bullets([
        "**1. 取得程式與版本：**`git clone https://github.com/Hendrick0815/ESG_AI_Dashboard`，切換至版本標籤 `git checkout thesis-v2-2026-10-20`。",
        "**2. 安裝環境：**Python 3.13，`pip install -r requirements.txt`（套件版本見表 2）。",
        "**3. 準備資料：**data/raw/ 下之逐日行情、TEJ TESG 與 TEJ 股價檔（data/raw/tej/prices/），並以 manifest.json 之 SHA-256 核對檔案相同。",
        "**4. 產生結果：**`python scripts/research/run_research.py`（約 15 分鐘）；`python scripts/research/run_research.py --test-yahoo`（股票池對照）；"
        "`python scripts/research/run_market_state_tests.py`（表 4-15 探索性補充分析）。版本已存在時程式會拒絕執行，重現時請將設定檔之 run_id 改為新名稱。",
        "**5. 產生文件：**`python scripts/research/build_report.py`（論文）、`build_code_doc.py`（程式碼對照）、`build_timing_audit.py`（時點稽核表）、`build_defense_pack.py`（本文件）。",
        f"**6. 核對：**新產出之 tables/*.csv 應與凍結版本（outputs/research/{c['run_id']}/VERSION.md 所列雜湊值）一致；"
        f"例如單純 AI 年化報酬 {pct(a['年化報酬'])}、AI+ESG {pct(ae['年化報酬'])}、規則式 ESG 篩選 {pct(e['年化報酬'])}。",
    ])

    # ======================= 五、樣本外追蹤規劃
    R.h(2, "五、樣本外追蹤規劃")
    R.p("目的：以未參與任何模型或參數選擇之新資料，檢驗本研究之主要比較是否成立。規劃於追蹤開始前訂定，追蹤期間不得修改。", indent=False)
    R.caption("表 3　樣本外追蹤規劃")
    R.table(["項目", "規劃"], [
        ["凍結內容", f"研究版本 {c['run_id']} 之全部設定（表 2）與程式（版本標籤 thesis-v2-2026-10-20）；模型依原規則滾動重新訓練，但不得調整參數、特徵或股票池規則"],
        ["追蹤期間", f"資料截點次一交易日（2026-10-21）起，至少 1 年（約 26 次調倉）；之後每年更新一次"],
        ["紀錄頻率", "每次調倉（每 2 週）記錄持股、成交價與各投組及 ETF 之報酬；紀錄只追加、不回改"],
        ["主要檢定（事先指定）", "AI+ESG 相對 00850 之日報酬差，Newey-West 檢定，雙尾 5%；只此一項為主要檢定，以避免多重比較"],
        ["次要指標（描述性）", "單純 AI、規則式 ESG 篩選相對各基準之報酬差、Sharpe、最大回撤、Beta、持股加權 TESG、週轉率與 10～20 bps 滑價後報酬"],
        ["判斷原則", "無論結果顯著與否皆完整報告；若主要檢定不顯著，維持「未顯著優於 ETF」之結論；資料來源或交易規則如需變更，改用新版本代號並與凍結版本並列"],
        ["執行方式", "延長研究設定檔之資料截點、改用新 run_id 後執行 run_research.py；探索性歷史回測期與追蹤期分開計算與呈現"],
    ], [3.0, 9.0], "ll", size=10)

    docx = OUT / "答辯與重現資料.docx"
    R.save(docx)
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice:
        subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", str(OUT), str(docx)], capture_output=True)
    print("完成：", docx)


if __name__ == "__main__":
    main()
