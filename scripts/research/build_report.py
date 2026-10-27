"""由 outputs/research/<run_id>/ 的正式輸出產生論文（Word＋PDF）。數字全部從表格檔讀取，不手動輸入。
執行：python scripts/research/build_report.py   （需先執行 run_research.py；PDF 需安裝 LibreOffice）
"""
from __future__ import annotations

import json, os, re, shutil, subprocess, sys
from pathlib import Path

import numpy as np
import pandas as pd
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, Cm

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
from report_lib import Report, add_text, spacing  # noqa: E402

CFG = json.loads((ROOT / "research_config.json").read_text(encoding="utf-8"))
RUN = ROOT / "outputs" / "research" / (sys.argv[1] if len(sys.argv) > 1 else CFG["run_id"])
T = RUN / "tables"
OUT = RUN / "report"
OUT.mkdir(exist_ok=True)
TITLE = "AI選股結合ESG與現有ETF的比較"


def rd(name, **kw):
    f = T / f"{name}.csv"
    return pd.read_csv(f, **kw) if f.exists() else pd.DataFrame()


def pct(x, d=1, sign=False):
    if x is None or pd.isna(x):
        return "—"
    s = f"{x*100:+.{d}f}%" if sign else f"{x*100:.{d}f}%"
    return s.replace("-", "−")


def num(x, d=2):
    if x is None or pd.isna(x):
        return "—"
    return f"{x:.{d}f}".replace("-", "−")


def pv(p):
    if pd.isna(p):
        return "—"
    return "< 0.001" if p < 0.001 else f"{p:.3f}"


# ------------------------------------------------------------------ 讀資料
man = json.loads((RUN / "manifest.json").read_text(encoding="utf-8"))
t41 = rd("table_4_1_performance").set_index("投組")
t42 = rd("table_4_2_yearly", index_col=0)
t43 = rd("table_4_3_regimes")
t44 = rd("table_4_4_capture").set_index("portfolio")
t45 = rd("table_4_5_capm_hac").set_index("投組")
t46 = rd("table_4_6_diff_hac")
t47 = rd("table_4_7_model_skill")
t48a = rd("table_4_8a_importance_distribution", index_col=0)
t48b = rd("table_4_8b_permutation_importance")
t49a = rd("table_4_9a_turnover_cost").set_index("portfolio")
t49b = rd("table_4_9b_slippage")
t410 = rd("table_4_10_esg_quality", index_col=0)
t37 = rd("table_3_7_period_split")
t38 = rd("table_3_8_parameter_trials")
us = pd.read_csv(RUN / "universe_summary.csv", parse_dates=["date"])
pvd = pd.read_csv(RUN / "price_validation.csv")
chk = pd.read_csv(RUN / "availability_checks.csv")
mc = pd.read_csv(RUN / "manual_checks.csv")
eq = pd.read_csv(RUN / "esg_quality_by_rebalance.csv", parse_dates=["date"])
sr = pd.read_csv(RUN / "strategy_returns.csv", parse_dates=["date"])
STR = ["單純 AI", "AI+ESG", "規則式 ESG 篩選"]
SRC = (RUN / "price_source.txt").read_text(encoding="utf-8") if (RUN / "price_source.txt").exists() else ""
FM = "FinMind" in SRC
YA = "Yahoo Finance 逐檔" in SRC
N_FM = re.search(r"FinMind 逐檔行情（(\d+) 檔", SRC).group(1) if re.search(r"FinMind 逐檔行情（(\d+) 檔", SRC) else "0"
N_YA = re.search(r"Yahoo Finance 逐檔日資料（(\d+) 檔", SRC).group(1) if YA else "0"
ORDER = ["單純 AI", "AI+ESG", "規則式 ESG 篩選", "0050", "00850", "00878", "加權指數"]
first_rb, last_rb = man["summary"]["first_rebalance"], man["summary"]["last_rebalance"]
n_rb = man["summary"]["rebalances"]
start_eval = CFG["backtest_start"]; cut = CFG["data_cutoff"]
n_days = int(t41.loc["單純 AI", "交易日數"])
years = n_days / 252


def d46(s, b):
    r = t46[(t46["策略"] == s) & (t46["基準"] == b)]
    return r.iloc[0] if len(r) else None


def sig_word(p, est):
    if pd.isna(p):
        return "無法判斷"
    if p < 0.05:
        return "顯著為正" if est > 0 else "顯著為負"
    if p < 0.10:
        return "僅達 10% 水準"
    return "不顯著"


# ------------------------------------------------------------------ 圖
def figures():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    for f in ["Noto Sans CJK TC", "Microsoft JhengHei", "DFKai-SB"]:
        if any(f in x.name for x in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = f
            break
    plt.rcParams["axes.unicode_minus"] = False
    w = sr.pivot_table(index="date", columns="portfolio", values="ret").sort_index()
    w = w[w.index >= pd.Timestamp(start_eval)]
    nav = (1 + w.fillna(0)).cumprod()
    fig, ax = plt.subplots(figsize=(8.2, 4.0), dpi=200)
    sty = {"單純 AI": ("#1f3864", "-", 2.0), "AI+ESG": ("#2e75b6", "-", 2.0), "規則式 ESG 篩選": ("#548235", "-", 1.8),
           "0050": ("#7f7f7f", "--", 1.2), "00850": ("#bf9000", "--", 1.2), "00878": ("#c55a11", ":", 1.4), "加權指數": ("#000000", ":", 1.2)}
    for c in ORDER:
        if c in nav:
            col, ls, lw = sty[c]
            ax.plot(nav.index, nav[c], color=col, ls=ls, lw=lw, label=c)
    ax.set_yscale("log")
    ax.set_ylabel("淨值（起點 = 1，對數刻度）")
    ax.grid(alpha=0.25, which="both")
    ax.legend(ncol=4, fontsize=8, frameon=False, loc="upper left")
    fig.tight_layout()
    fig.savefig(OUT / "fig_nav.png"); plt.close(fig)
    e = eq[eq["date"] >= pd.Timestamp(start_eval)].pivot_table(index="date", columns="portfolio", values="esg_total")
    fig, ax = plt.subplots(figsize=(8.2, 3.4), dpi=200)
    for c, col in [("規則式 ESG 篩選", "#548235"), ("AI+ESG", "#2e75b6"), ("股票池等權", "#7f7f7f"), ("單純 AI", "#1f3864")]:
        if c in e:
            ax.plot(e.index, e[c], color=col, lw=1.8 if c != "股票池等權" else 1.4, ls="-" if c != "股票池等權" else "--", label=c)
    ax.set_ylabel("持股加權 TESG 分數")
    ax.grid(alpha=0.25)
    ax.legend(ncol=4, fontsize=8, frameon=False, loc="lower left")
    fig.tight_layout()
    fig.savefig(OUT / "fig_esg.png"); plt.close(fig)


# ------------------------------------------------------------------ 本文
def compose(R: Report, pages: dict):
    D = R.doc
    # ---------- 封面
    def C(text, size, bold=False, before=0, after=0):
        p = D.add_paragraph(); spacing(p, before, after, 1.5, align=WD_ALIGN_PARAGRAPH.CENTER); add_text(p, text, bold=bold, size=size)
    C("逢甲大學 財務金融學系", 28); C("115學年度", 28); C("專題製作報告書", 28)
    p = D.add_paragraph(); spacing(p, 14, 0, 1.0); _border(p, "bottom")
    C(TITLE, 26, bold=True, before=8, after=2)
    C("（修訂版）", 16, after=8)
    p = D.add_paragraph(); spacing(p, 0, 26, 1.0); _border(p, "top")
    t = D.add_table(rows=7, cols=2)
    from report_lib import borders
    borders(t, none=True)
    t.alignment = 1
    for i, (a, b) in enumerate([("指導教授：", "王鈺仁 老師"), ("班　　級：", "財金系 三年乙班"), ("組　　長：", "陳東杰 D1280673"),
                                 ("組　　員：", "陳亭翰 D1209072"), ("", "陳治嘉 D1222280"), ("", "黃彥霖 D1240092"), ("", "張建民 D1240121")]):
        for j, v in enumerate((a, b)):
            c = t.cell(i, j); c.width = Cm(4.2 if j == 0 else 7.0)
            spacing(c.paragraphs[0], 0, 0, 1.4); add_text(c.paragraphs[0], v, size=18)
    C("中華民國 115 年 5 月 18 日（修訂：115 年 10 月 25 日）", 16, before=40)

    # ---------- 前言（羅馬頁碼）
    R.new_section(fmt="lowerRoman", start=1)
    R.h(1, "致謝")
    R.p("感謝指導教授 王鈺仁教授一年來的細心指導與教誨，並不時花費時間在觀念上進行討論，使本專題得以順利完成，且在報告撰寫過程中費心指出許多問題，讓報告的基礎得以成型，而不論在研究態度與待人接物方面均受益良多，並常提供一些日常生活中的經驗談，在此謹致上最誠摯之敬意與謝忱。")
    R.p("另外，特別感謝系上老師們的指導與鞭策。更有賴許多朋友在精神上給予鼓勵與支持，甚或實質協助，我們才能順利完成專題。")
    R.p("最後要感謝我們的父母與家人，若不是他們長久以來的支持，不可能有今天的小小成果，僅以此篇報告表達內心最誠摯的感激。")
    R.h(1, "摘要")
    a, ae, e = t41.loc["單純 AI"], t41.loc["AI+ESG"], t41.loc["規則式 ESG 篩選"]
    R.p(f"本研究以自建的「ESG-AI 台股選股平台」為工具，比較「單純 AI」、「AI+ESG」與「規則式 ESG 篩選投組」三種策略與加權指數、0050、00850、00878 的歷史回測表現。股票池在每個調倉日依當時可得的近 20 日成交金額重新排名前 {CFG['universe']['size']} 檔，並納入之後下市的股票；所有資料依實際公告日或可使用日對齊，交易成本含手續費與證交稅，另做 10、20、30 bps 滑價敏感度分析。")
    R.p(f"在 {start_eval} 至 {cut}（{n_days} 個交易日）的評估期間，單純 AI 年化報酬 {pct(a['年化報酬'])}（95% 區塊 bootstrap 信賴區間 {pct(a['年化報酬95%CI下限'])}～{pct(a['年化報酬95%CI上限'])}），AI+ESG {pct(ae['年化報酬'])}，規則式 ESG 篩選 {pct(e['年化報酬'])}，00850 {pct(t41.loc['00850','年化報酬'])}。以 Newey-West 標準誤並經 Holm 多重比較調整後，{_abstract_tests()}AI+ESG 投組的持股加權 TESG 分數平均 {num(t410.loc['AI+ESG','esg_total'],1)}，高於股票池等權的 {num(t410.loc['股票池等權','esg_total'],1)} 與單純 AI 的 {num(t410.loc['單純 AI','esg_total'],1)}。")
    if cu is not None:
        R.p(f"若沿用平台網站的做法、以資料截點當時的前 300 大股票回頭建構整段期間的股票池，單純 AI 年化報酬會高達 {pct(cu.loc['單純 AI','年化報酬'])}，顯示初稿的高報酬主要來自股票池的後見之明偏誤。")
    R.p("由於模型與參數是在包含上述期間的資料上比較後選定，本研究將這段結果定位為探索性分析；研究設定已於 115 年 10 月 25 日鎖定，之後的新資料將作為真正未接觸的保留測試。結論應理解為：在本研究所使用的股票樣本、資料截點與交易假設下的歷史回測表現，不能代表未來可實現的報酬。")
    p = D.add_paragraph(); spacing(p, 6, 0, 1.5); add_text(p, "關鍵詞：ESG、機器學習選股、隨機森林、ESG ETF、Newey-West 檢定、存活者偏誤", size=12)
    R.h(1, "目錄")
    R.toc(pages)

    # ---------- 本文（阿拉伯頁碼）
    R.new_section(fmt="decimal", start=1)
    ch1(R); ch2(R); ch3(R); ch4(R); ch5(R); refs(R); appendix(R)


def _abstract_tests():
    s = []
    a00850 = d46("單純 AI", "00850"); ae00850 = d46("AI+ESG", "00850"); e00850 = d46("規則式 ESG 篩選", "00850")
    s.append(f"單純 AI 相對 00850 的日報酬差{sig_word(a00850['p_holm'], a00850['est'])}（調整後 p = {pv(a00850['p_holm'])}）")
    s.append(f"AI+ESG 相對 00850 {sig_word(ae00850['p_holm'], ae00850['est'])}（p = {pv(ae00850['p_holm'])}）")
    s.append(f"規則式 ESG 篩選與 00850 的差異{sig_word(e00850['p_holm'], e00850['est'])}（p = {pv(e00850['p_holm'])}）")
    return "；".join(s) + "。"


def _border(p, side):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    pPr = p._p.get_or_add_pPr(); b = OxmlElement("w:pBdr"); e = OxmlElement(f"w:{side}")
    e.set(qn("w:val"), "single"); e.set(qn("w:sz"), "12"); e.set(qn("w:space"), "1"); e.set(qn("w:color"), "000000")
    b.append(e); pPr.append(b)


# ------------------------------------------------------------------ 第一章
def ch1(R):
    R.h(1, "第一章　緒論")
    R.h(2, "一、研究背景與動機")
    R.p("隨著科技快速發展，人工智慧（AI）已從過去想像中的未來技術，逐漸成為推動現代社會與金融市場的重要核心力量。特別是在金融領域中，AI 憑藉其強大的非線性資料分析能力，正在逐步改變傳統投資決策模式。同時，全球資本市場也正在經歷一場從「追求獲利最大化」轉向「兼顧永續價值」的轉變。投資人不再只關注企業短期財務績效，而是開始將環境（Environmental）、社會（Social）及公司治理（Governance）等 ESG 指標納入投資評估，希望透過永續投資降低長期風險並提升投資穩定性。")
    R.p("在這個趨勢下，ESG ETF 快速崛起，例如「00850 元大臺灣 ESG 永續」與「00878 國泰永續高股息」受到市場高度關注。然而多數 ESG 評分依據企業定期揭露的永續報告書與歷史資料，具有資訊滯後性；不同評級機構的衡量標準也不一致，且可能出現「漂綠」問題。若只依賴 ESG 評分建構投資組合，未必能充分反映市場的即時資訊。")
    R.p("AI 模型可以每天讀入最新的股價、成交量與估值資料並定期重新訓練，也能捕捉技術面、估值與報酬之間的非線性關係，因此有機會改善 ESG 投資的資訊落後問題。另一方面，機器學習選股也伴隨資料探勘偏誤、存活者偏誤與交易成本被低估等風險（Sullivan et al., 1999；Harvey et al., 2016；Novy-Marx & Velikov, 2016）。本研究以自行建置、每日自動更新的「ESG-AI 台股選股平台」為工具，在可重現的研究設定下比較 AI 選股、ESG 篩選與市售 ETF，並同時檢視報酬、風險與投組本身的永續品質。")
    R.h(2, "二、研究目的")
    R.bullets(["**檢驗 ESG 評分的投資價值：**以 TEJ TESG 總分建構「規則式 ESG 篩選投組」，觀察高 ESG 企業能否帶來優於大盤或 00850 的報酬，或主要提供較低風險。",
               "**檢驗 AI 能否提升 ESG 投資的效率：**以隨機森林預測個股未來 10 個交易日的相對報酬，並與 ESG 排名結合成「AI+ESG」投組，比較報酬、風險與統計顯著性。",
               "**檢驗永續品質是否得以維持：**比較各投組持股加權的 TESG、環境／社會／治理分數、低 ESG 持股比例與產業集中度，確認 AI+ESG 的永續屬性不只是名目上的。",
               "**建立可重現的研究流程：**以獨立研究設定檔、資料快照雜湊值與產表程式，讓論文每一張表都能追溯到同一版本的程式與資料。"])
    R.h(2, "三、研究問題與假說")
    R.caption("表 1-1　研究問題與假說")
    R.table(["研究問題（RQ）", "研究假說（H）"], [
        ["RQ1　ESG 評分是否具有報酬預測能力？", "H1：規則式 ESG 篩選投組的日報酬顯著高於加權指數與 00850。"],
        ["RQ2　AI 是否能優化 ESG 選股？", "H2：AI+ESG 投組的日報酬顯著高於規則式 ESG 篩選投組。"],
        ["RQ3　AI+ESG 是否優於市售 ESG ETF？", "H3：AI+ESG 投組相對 00850 具有正向且顯著的 CAPM Alpha 與日報酬差（經多重比較調整）。"],
        ["RQ4　不同市場情境下表現是否不同？", "H4：依事前規則劃分的多頭、盤整、高波動、空頭情境中，各策略的相對表現不同。"],
        ["RQ5　AI+ESG 是否保有永續品質？", "H5：AI+ESG 投組的持股加權 TESG 高於股票池等權與單純 AI，且低 ESG 持股比例較低。"]],
        [3.6, 6.4])
    R.h(2, "四、研究範圍與限制說明")
    R.p(f"本研究以台灣上市櫃普通股為母體，訓練資料自 {CFG['history_start']} 起，正式評估期間為 {start_eval}（TEJ TESG 首次公告日）至資料截點 {cut}。由於模型與主要參數曾在涵蓋此期間的資料上比較，本研究將此期間定位為「探索性評估」，並於 115 年 10 月 25 日鎖定全部設定，之後的新資料作為保留測試（詳見第三章第七節）。所有結論均以本研究的股票樣本、資料截點與交易假設為前提。")


# ------------------------------------------------------------------ 第二章
def ch2(R):
    R.h(1, "第二章　文獻回顧")
    R.h(2, "一、ESG 指標與企業績效")
    R.p("Friede et al.（2015）整合超過 2,200 篇實證研究，發現約九成研究呈現非負向的 ESG 與財務績效關係，且正向結果自 1990 年代中期以來相當穩定。然而 Pedersen et al.（2021）的理論模型指出，ESG 對報酬的影響方向取決於 ESG 資訊是否已被市場反映，以及偏好 ESG 的資金是否推高價格；當大量資金追逐高 ESG 資產時，其未來預期報酬反而可能下降，因此「ESG 越高報酬越好」並非必然。")
    R.p("在台灣市場，鄭雅萍（2025）以機器學習分類模型檢視台灣上市櫃公司，發現 ESG 表現與長期績效呈正向關聯，且公司治理分數的解釋力最強；Shen（2024）以模糊粗糙集方法分析台灣權值股，指出 ESG 評等與 ROE 等財務指標共同有助於解釋股票報酬。這些研究提供 ESG 資訊在台股具參考價值的證據，但多以年度或橫斷面資料為主，較少與市售 ESG ETF 在相同條件下比較。")
    R.h(2, "二、ESG 基金與 ETF 的配置限制")
    R.p("Friede et al.（2015）指出，相較於企業層級研究，ESG 投資組合研究的結果較常呈現中性，部分原因在於投資組合的系統風險與實施成本侵蝕了 ESG 溢酬。Pedersen et al.（2021）亦提醒，單純排除低 ESG 股票的篩選策略可能降低分散化效果。市售 ESG ETF 多採半年定審、市值或殖利率加權，並有個股權重上限（如 00850 單一個股上限 30%、00878 上限 10%），其建構方式與學術研究中常見的等權投組不同，比較時需特別說明差異。")
    R.h(2, "三、機器學習於資產定價與選股")
    R.p("Gu et al.（2020）系統性比較多種機器學習方法在美股報酬預測上的表現，發現樹狀模型與神經網路能捕捉非線性與交互作用，預測力明顯優於線性模型，且主要的有效訊號為動能、流動性與波動度等價格類特徵。隨機森林（Breiman, 2001）以多棵決策樹平均降低過度擬合，梯度提升樹（Chen & Guestrin, 2016）則以逐步修正殘差提高預測精度。Carlei et al.（2025）以 CatBoost 排序模型結合 ESG 風險分數與股價資料建構 S&P 500 動態投組，回測中產生顯著的風險調整後超額報酬。")
    R.h(2, "四、資料探勘偏誤、存活者偏誤與交易成本")
    R.p("Sullivan et al.（1999）指出，在同一份歷史資料上反覆嘗試交易規則，最佳規則的績效可能只是運氣，需以考慮多重比較的方法檢驗；Harvey et al.（2016）進一步主張因子研究應提高顯著性門檻。Brown et al.（1992）說明只使用存活樣本會高估歷史績效。Novy-Marx & Velikov（2016）發現許多高週轉的異常報酬在扣除交易成本後大幅縮小甚至消失。這些文獻提醒本研究：必須區分參數選擇與績效評估的期間、使用逐期可得的股票池、報告多重比較調整後的檢定結果，並對交易成本做敏感度分析。")
    R.h(2, "五、AI 與 ESG 的整合")
    R.p("Pedersen et al.（2021）提出「ESG 效率前緣」，說明投資人需在風險、報酬與 ESG 之間權衡。鄭雅萍（2025）以 KNN 與分類迴歸樹選股，結果優於以 ESG 為目標的傳統基金；Carlei et al.（2025）則顯示機器學習排序可依投資人偏好調整 ESG 門檻。然而，若主張 AI 與 ESG 結合具有永續效果，除了比較報酬外，也應直接衡量投組的 ESG 品質，否則可能出現報酬提升、但持股永續程度下降的情形。")
    R.h(2, "六、文獻缺口與本研究定位")
    R.p("綜合上述，現有研究較少同時做到：(1) 在台股以逐期可得資料重建股票池並納入下市股票；(2) 與實際交易的 ESG ETF 在相同期間、扣除成本後比較；(3) 以考慮自我相關與多重比較的方法檢定超額報酬；(4) 比較投組本身的 ESG 品質。本研究以可重現的研究流程補足上述面向，並明確區分探索性結果與保留測試。")


# ------------------------------------------------------------------ 第三章
def ch3(R):
    R.h(1, "第三章　研究方法")
    R.h(2, "一、研究版本與重現方式")
    R.p("論文所有結果來自同一個研究版本：參數集中存放於獨立的研究設定檔 research_config.json，執行 scripts/research/run_research.py 即依此設定重新建立股票池、訓練模型、回測並輸出表 3-3、3-7、3-8 與表 4-1 至表 4-10；scripts/research/build_report.py 再由這些表格檔產生本文中的數字。每次執行都會產生 manifest.json，記錄設定、資料檔與程式檔的 SHA-256 雜湊值、Python 與套件版本及執行時間（附錄 A）。")
    pk = man["packages"]
    R.caption("表 3-1　研究正式版本設定")
    rows = [["研究版本代號", CFG["run_id"]], ["資料截點", cut], ["設定鎖定日", CFG["locked_on"]],
            ["訓練資料起點", CFG["history_start"]], ["正式評估期間", f"{start_eval} ～ {cut}（{n_rb} 次調倉）"],
            ["股票池", f"每個交易日以近 {CFG['universe']['window_days']} 個交易日平均成交金額排名前 {CFG['universe']['size']} 檔普通股（交易天數不足 {CFG['universe']['min_trading_days']} 天不納入）"],
            ["模型", f"{CFG['model']}，{CFG['n_estimators']} 棵樹，隨機種子 {CFG['random_seed']}"],
            ["重新訓練", f"每 {CFG['retrain_every_rebalances']} 次調倉；訓練樣本每 {CFG['train_sample_every_days']} 個交易日取一天"],
            ["持股與權重", f"Top {CFG['top_n']}，{CFG['weighting']}；每 {CFG['hold_days']} 個交易日調倉"],
            ["AI+ESG 權重", f"AI 排名 {1-CFG['esg_weight']:.0%}、TESG 排名 {CFG['esg_weight']:.0%}"],
            ["交易成本", f"手續費 {CFG['costs']['commission']:.4%}（買賣各一次）、證交稅 {CFG['costs']['sell_tax']:.1%}（賣出）；基準情境滑價 0"],
            ["風險控制／產業限制", "不使用（不設停損、不限制同產業檔數、不排除產業）"],
            ["執行環境", f"Python {man['python']}；pandas {pk['pandas']}、scikit-learn {pk['scikit-learn']}、statsmodels {pk['statsmodels']}"],
            ["程式版本", man.get("git_commit") or "見 manifest.json 程式檔雜湊值"]]
    R.table(["項目", "設定"], rows, [2.4, 7.6], "ll")
    R.note("註：平台網站的預設值與本表一致（README 與 src/config.py 已同步為 Top 20）；網站每日更新的數字會隨新資料改變，論文以本表版本為準。")

    R.h(2, "二、資料來源與可得日")
    R.p("所有資料一律依「可以被使用的日期」對齊：某一個調倉日只會用到當天收盤以前已經公布的資料。表 3-2 列出各資料的來源、頻率與可得日規則；完整欄位說明見附錄 B 資料字典。")
    R.caption("表 3-2　資料來源與可得日規則")
    R.table(["資料", "來源", "價格型態／頻率", "可得日規則"], [
        (["上市個股日資料", f"Yahoo Finance（{N_YA} 檔現存股票）；FinMind（{N_FM} 檔 Yahoo 未收錄、多為已下市，資料源為證交所）", "每日；Yahoo 用還原收盤價計算含權息報酬，成交金額以收盤價 × 成交股數近似；FinMind 以漲跌價差回推參考價", "當日收盤"]
         if YA else ["上市個股日資料（含已下市）", "臺灣證券交易所 MI_INDEX", "每日全市場；以漲跌價差回推參考價計算含權息報酬", "當日收盤"]),
        ["上櫃個股日資料（含已下市）", "櫃買中心 dailyQuotes", "每日全市場；以次日參考價計算含權息報酬；現存 300 檔改用 Yahoo 還原收盤價報酬", "當日收盤"],
        ["比較基準（0050、00850、00878）", "Yahoo Finance", "每日還原收盤價（含配息再投入；ETF 經理費、保管費已反映於淨值）", "當日收盤"],
        ["加權指數（^TWII）", "Yahoo Finance", "每日價格指數（不含股利）", "當日收盤"],
        ["本益比、股價淨值比、殖利率", "證交所 BWIBBU（僅上市）", "每月底", "資料日期當日（上櫃股以訓練集中位數補值）"],
        ["ESG 評等（總分、E／S／G、事件雷達）", "TEJ TESG", "半年一期，共 8 期", "TESG 評等公告日（8 期皆有公告日，最早 2022-11-01）"],
        ["產業別", "證交所、櫃買中心公司清單；TEJ", "靜態", "僅用於 ESG 品質分析，不作為選股依據"]], [2.6, 2.4, 3.0, 2.0], "llll")
    R.note("註：加權指數為價格指數，未含現金股利，與含權息的策略報酬比較時會對策略有利（年約 3%～4%）；因此本研究同時以含息的 0050、00850、00878 作為比較基準。")

    R.h(2, "三、逐期股票池")
    lst = us["listed_common"]; sel = us["selected"]
    R.p(f"平台網站為了更新速度，只下載「目前」成交金額前 300 檔的股價；若直接用於回測，過去曾經熱門但之後下市或排名下滑的股票會被遺漏，產生存活者偏誤（Brown et al., 1992）。為此，本研究另外下載 2017 年 7 月至 {cut} 每個交易日的全市場行情（{'上櫃股票取自櫃買中心每日全部行情；上市股票因證交所限制大量下載，改以 Yahoo Finance 逐檔下載研究期間曾掛牌的上市普通股，Yahoo 未收錄者（多為已下市）再以 FinMind 補齊' if YA else '證交所與櫃買中心每日全部行情'}，均含之後下市的股票），並在每個交易日以「當天（含）往前 20 個交易日的平均成交金額」重新排名，取前 {CFG['universe']['size']} 檔作為當天的股票池；新上市未滿 15 個交易日者不納入。模型的訓練樣本與每次選股都只使用當天股票池內的股票，已持有的股票若之後掉出股票池或下市，仍依實際報酬計算至下次調倉（下市後視為以最後收盤價持有現金）。")
    R.caption("表 3-3　逐期股票池概況（各調倉日）")
    R.table(["項目", "平均", "最小", "最大"], [
        ["掛牌普通股檔數", f"{lst.mean():,.0f}", f"{lst.min():,.0f}", f"{lst.max():,.0f}"],
        ["入選股票池檔數", f"{sel.mean():,.0f}", f"{sel.min():,.0f}", f"{sel.max():,.0f}"],
        ["入選門檻（第 300 名 20 日均成交金額，億元）", num(us['min_avg_value'].mean()/1e8, 2), num(us['min_avg_value'].min()/1e8, 2), num(us['min_avg_value'].max()/1e8, 2)],
        ["入選股票中之後下市的檔數", f"{us['later_delisted'].mean():.1f}", f"{us['later_delisted'].min():.0f}", f"{us['later_delisted'].max():.0f}"]],
        [5.0, 1.6, 1.6, 1.6], "lrrr")
    R.note(f"註：普通股以代號規則判斷（4 碼、不以 0 開頭、排除 91xx 存託憑證），因此也適用已下市股票。研究期間曾進入股票池的股票共 {man['summary']['universe_tickers_ever']} 檔。逐期名單見 outputs/research/{CFG['run_id']}/universe_history.csv。")
    v = pvd
    R.p(f"為檢查以交易所參考價計算的報酬是否正確，本研究將{"櫃買中心資料" if YA else "交易所資料"}算出的報酬與 Yahoo Finance 還原收盤價報酬比對（{len(v)} 檔重疊股票、各至少 250 個交易日）：日報酬相關係數中位數 {num(v['corr'].median(),4)}，日報酬平均絕對差中位數 {num(v['mean_abs_diff'].median()*1e4,1)} bps，年化報酬差距中位數 {pct((v['ann_ret_exchange']-v['ann_ret_yahoo']).median(),2)}（絕對差距中位數 {pct((v['ann_ret_exchange']-v['ann_ret_yahoo']).abs().median(),2)}）。為避免除權息「不比價」日造成的誤差，平台現存的 300 檔股票一律改用 Yahoo 還原收盤價計算日報酬，其餘股票（多為已下市或排名下滑者）才使用交易所報酬。")

    R.h(2, "四、投組與比較基準")
    R.p("三個策略每次都從當期股票池中選出 20 檔、每檔 5% 等權持有，差別只在排序依據（表 3-4）。原規劃以「排除爭議分數大於 3 與 EPS 為負的公司」作為 ESG 前置篩選，但現有 TEJ 資料只有事件雷達轉換計分、沒有 EPS 欄位，程式實際上並未套用這兩項排除條件；本修訂版已更正描述，三個策略皆不做排除。")
    R.caption("表 3-4　三種投組的建構方式")
    R.table(["投組", "排序依據", "權重與調倉", "主要對照"], [
        ["單純 AI", "隨機森林預測的未來 10 日相對報酬", "前 20 檔等權；每 10 個交易日", "0050、加權指數"],
        ["AI+ESG", "70% × AI 預測排名＋30% × TESG 排名", "同上", "00850、00878"],
        ["規則式 ESG 篩選投組", "TEJ TESG 總分由高到低", "同上（TESG 半年更新，持股變動小）", "00850"]], [2.2, 3.4, 2.6, 1.8], "llll")
    R.p("規則式 ESG 篩選投組是本研究自行建構的對照組，與 00850、00878 的建構方式有多項差異（表 3-5），因此兩者的報酬差異不能全部歸因於「ESG 篩選本身」。")
    R.caption("表 3-5　規則式 ESG 篩選投組與市售 ESG ETF 的差異")
    R.table(["項目", "規則式 ESG 篩選投組", "00850 元大臺灣 ESG 永續", "00878 國泰永續高股息"], [
        ["ESG 資料", "TEJ TESG 總分", "FTSE4Good 新興市場指數成分（富時 ESG 評估）", "MSCI ESG 評級 BB 以上、爭議分數 3 以上"],
        ["選股範圍與條件", "當期成交金額前 300 大上市櫃普通股", "上市股票；剔除近 12 個月 ROE < 0 或未編製永續報告書者", "MSCI 臺灣指數大中型股；依殖利率計分"],
        ["成分股數", "20 檔", "非固定（2026 年 9 月調整後 110 檔）", "30 檔"],
        ["權重", "等權", "可投資市值加權，單一個股上限 30%", "殖利率相關加權，單一個股上限 10%"],
        ["再平衡", "每 10 個交易日（權重回到等權）", "每年 6 月、12 月定審", "每年 5 月、11 月定審"],
        ["股利處理", "含權息報酬（股利再投入）", "季配息；本研究用還原價（股利再投入）", "季配息；本研究用還原價（股利再投入）"],
        ["費用", "僅計交易成本", "經理費 0.30%～0.45%、保管費 0.035%（反映於淨值）", "經理費 0.25%～0.30%、保管費 0.03%（反映於淨值）"],
        ["產業限制", "無", "無（僅個股上限）", "無（僅個股上限）"]], [1.6, 2.6, 2.9, 2.9], "llll")
    R.note("資料來源：元大投信 00850 產品頁、國泰投信 00878 相關說明（2026 年 10 月查詢）。ETF 歷史成分股與權重無法取得，因此第四章的 ESG 品質比較以「股票池等權」作為市場代理，不直接比較 ETF。")

    R.h(2, "五、研究流程")
    for i, s in enumerate(["**資料蒐集：**下載交易所逐日行情（含下市股票）、比較基準、估值與 TEJ TESG；依資料截點裁切。",
                           "**逐期股票池：**每個交易日以近 20 日平均成交金額排名前 300 檔。",
                           "**特徵工程：**為每檔股票、每天計算 14 個技術面、見頂訊號與估值特徵，ESG 與估值依可得日對齊。",
                           "**滾動訓練：**以隨機森林學習「特徵 → 未來 10 日相對報酬」，每 3 次調倉重新訓練，只使用訓練當天已知結果的資料。",
                           "**選股與回測：**每 10 個交易日依三種排序各選 20 檔等權持有，以收盤價換股，扣除手續費與證交稅。",
                           "**績效與檢定：**計算報酬、風險、CAPM 與差異檢定（Newey-West 標準誤、Holm 調整），並做滑價敏感度、市場情境與 ESG 品質分析。",
                           "**輸出與版本紀錄：**所有表格與中間檔寫入 outputs/research/，並記錄資料與程式雜湊值。"], 1):
        p = R.doc.add_paragraph(); spacing(p, 0, 3, 1.5, left=Pt(24), hanging=Pt(18), align=WD_ALIGN_PARAGRAPH.JUSTIFY)
        add_text(p, f"{i}. ", size=12); from report_lib import rich; rich(p, s)

    R.h(2, "六、模型與變數")
    R.p("本研究以隨機森林（Breiman, 2001）作為主要模型：100 棵決策樹、每棵最多 6 層、葉節點至少 20 筆、每次分裂隨機使用 70% 的特徵、每棵樹抽取 50% 的樣本，以限制模型複雜度。XGBoost（Chen & Guestrin, 2016）與兩者平均僅作為參數試驗中的比較對象。")
    R.p("預測目標為每檔股票「未來 10 個交易日報酬減去同一天股票池平均報酬」，模型的任務是排序股票而非預測大盤漲跌。輸入特徵共 14 個（表 3-6）；ESG 分數不放入模型，而是在選股階段才與 AI 排名結合，以便分別觀察 AI 與 ESG 的貢獻。")
    R.caption("表 3-6　模型特徵")
    R.table(["類別", "特徵", "計算方式"], [
        ["技術面", "近 5／20／60 日報酬", "今日收盤價 ÷ N 日前收盤價 − 1"],
        ["技術面", "20 日年化波動率", "近 20 日日報酬標準差 × √252"],
        ["技術面", "月線、季線乖離率", "收盤價 ÷ 20／60 日均價 − 1"],
        ["見頂訊號", "距 20 日最高價跌幅、高點距今天數", "收盤價 ÷ 近 20 日最高價 − 1；最高價是幾天前"],
        ["見頂訊號", "連續下跌天數、量能比、短期反轉", "連續收黑天數；5 日均量 ÷ 60 日均量；近 5 日報酬 × 近 60 日報酬"],
        ["估值", "本益比、股價淨值比、殖利率", "證交所每月底資料（上櫃股以中位數補值）"]], [1.4, 3.6, 5.0], "lll")

    R.h(2, "七、期間切分與參數選擇紀錄")
    R.p("為避免把參數選擇的結果當成樣本外績效，本研究將期間切分為開發期、驗證期、探索性評估期與保留測試期（表 3-7）。必須說明的是：表 3-8 的參數試驗是在 2026 年 10 月進行，當時已使用到 2022-11 至 2026-10 的資料，因此該期間雖然在時間上位於訓練資料之後，但已參與模型與參數的選擇，不能宣稱為完全未接觸的樣本外測試，本研究將其結果列為探索性分析。研究設定已於 2026-10-25 鎖定，2026-10-21 之後的資料作為保留測試，由平台每日自動延伸追蹤，不再修改任何參數。")
    rows = []
    names = {"development": "開發期", "validation": "驗證期", "exploratory_evaluation": "探索性評估期", "locked_holdout": "保留測試期"}
    use = {"development": "模型訓練；訓練樣本累積", "validation": "訓練延伸；觀察單純 AI 的表現",
           "exploratory_evaluation": "三策略與 ETF 比較（本文主要結果）", "locked_holdout": "設定鎖定後的真正測試（進行中）"}
    for k, (s0, s1) in CFG["periods"].items():
        sub = t37[(t37["period"] == k) & (t37["投組"] == "單純 AI")] if len(t37) else pd.DataFrame()
        sub2 = t37[(t37["period"] == k) & (t37["投組"] == "加權指數")] if len(t37) else pd.DataFrame()
        ai = pct(sub["ann_return"].iloc[0]) if len(sub) else "—"
        tw = pct(sub2["ann_return"].iloc[0]) if len(sub2) else "—"
        rows.append([names[k], f"{s0} ～ {s1 or '持續追蹤'}", use[k], ai, tw])
    R.caption("表 3-7　期間切分")
    R.table(["期間", "日期", "用途", "單純 AI 年化", "加權指數年化"], rows, [1.6, 2.6, 3.4, 1.2, 1.2], "lllrr")
    R.note(f"註：開發期與驗證期的報酬來自同一套滾動訓練、自 {CFG['long_backtest_start']} 起的長期間回測（ESG 資料自 2022-11 才有，因此只列單純 AI）；開發期前段為模型暖機，未計入。此長期間回測的調倉日期網格與正式版本不同，因此探索性評估期的數字與表 4-1 不同（差異見表 4-2 對照 2）。")
    if len(t38):
        R.caption("表 3-8　參數試驗紀錄（探索性）")
        R.table(["日期", "項目", "比較內容", "評估期間", "結果", "選定"],
                t38[["試驗日期", "試驗項目", "比較內容", "評估期間", "結果（單純 AI 年化報酬）", "選定"]].astype(str).values.tolist(),
                [1.3, 1.4, 2.4, 1.8, 2.3, 1.2], "llllll", size=9.5)
        R.note("註：試驗結果為當時平台版本（以 Yahoo 現存 300 檔為股票池）的數字，與本研究正式版本不同，僅用來說明參數如何被選出。由於試驗期間與探索性評估期重疊，正式結果可能因參數選擇而偏樂觀。")

    R.h(2, "八、回測與交易假設")
    R.caption("表 3-9　交易與價格假設")
    R.table(["項目", "假設"], [
        ["成交時點", "調倉日以收盤價換股，報酬自下一個交易日起算（假設能以收盤價成交，實務上可能無法完全做到）"],
        ["個股價格", "交易所收盤價；以參考價回推含權息日報酬；當日無成交記為 0；不比價（X）日記為 0"],
        ["ETF 價格", "Yahoo 還原收盤價（含配息再投入，經理費與保管費已反映於淨值）"],
        ["初始建倉", "第一次調倉即買進全部持股並支付買進成本"],
        ["交易成本", "買進 0.1425%；賣出 0.1425% ＋ 證交稅 0.3%"],
        ["滑價", "基準情境 0；敏感度分析每邊 10、20、30 bps"],
        ["流動性門檻", "股票池為 20 日平均成交金額前 300 大（表 3-3 列出入選門檻）；未另設單筆成交量上限"],
        ["下市與停牌", "持有期間無報價視為 0 報酬；下市後以最後收盤價持有至下次調倉"],
        ["資金運用", "永遠滿倉，不設停損、不因大盤轉弱減碼"]], [2.0, 8.0], "ll")

    R.h(2, "九、績效評估與統計方法")
    R.p("績效指標包括累積與年化報酬、年化波動、夏普值（無風險利率 1%）與最大回撤；年化報酬另以移動區塊 bootstrap（區塊 20 日、2,000 次；Künsch, 1989）估計 95% 信賴區間。CAPM 以日頻資料估計 (Rp − Rf) = α + β (Rm − Rf) + ε，市場以加權指數代表（Jensen, 1968）；策略與比較基準的差異以日報酬差對常數迴歸檢定。所有標準誤採 Newey & West（1987）的異質變異與自我相關一致估計，落後期數依 Newey & West（1994）取 floor(4(T/100)^(2/9))。")
    R.p("由於同時比較三個策略與四個基準，本研究以 Holm（1979）方法調整 p 值，控制整體型一錯誤率；文中所稱「顯著」皆指 Holm 調整後 p < 0.05。效果量報告年化報酬差與年化資訊比率（日報酬差平均 ÷ 標準差 × √252）。")
    R.caption("表 3-10　市場情境分類規則（事前訂定）")
    rr = CFG.get("regime_rules") or {}
    R.table(["情境", "規則（以前一交易日為止的加權指數資料判斷）"], [
        ["空頭", "60 日報酬 ≤ −10%，或距 250 日高點回撤 ≤ −15%"],
        ["高波動", "非空頭，且 20 日年化波動率 ≥ 25%"],
        ["多頭", "非空頭、非高波動，且 60 日報酬 ≥ +5%"],
        ["盤整", "其餘日期"]], [1.6, 8.4], "ll")
    R.note("註：規則在檢視策略績效之前訂定，並套用到評估期間的每一個交易日；以前一交易日的資料分類，避免用到當天資訊。")


# ------------------------------------------------------------------ 第四章
CU = ROOT / "outputs" / "research" / (CFG["run_id"] + "_current_universe") / "tables" / "table_4_1_performance.csv"
cu = pd.read_csv(CU).set_index("投組") if CU.exists() else None
sv = rd("table_4_2b_survivorship_split")


def lead_lag(x, ref):
    return "高於" if x > ref else "低於"


def ch4(R):
    R.h(1, "第四章　實證結果")
    R.p(f"本章先說明資料與樣本概況，再呈現績效、穩健性、統計檢定與敏感度分析。除另有說明，結果皆為探索性評估期 {start_eval} 至 {cut}（{n_days} 個交易日、{n_rb} 次調倉）、扣除手續費與證交稅後的數字；每張表下註明資料來源檔。" + ("表 3-3、3-7、3-8 與本章的表格、圖為本研究平台網站「論文正式版本」頁面（pages/5_論文正式版本.py）的截圖，網站直接讀取同一批研究輸出檔，數字與資料檔一致。" if R.shots else ""))
    # 一
    R.h(2, "一、資料與樣本概況")
    bad = int(chk["esg_score_mismatch_total"].iloc[0]) if "esg_score_mismatch_total" in chk else 0
    inu = (chk["holdings_in_universe"] == chk["holdings_total"]).mean()
    R.p(f"每個調倉日平均約有 {us['listed_common'].mean():,.0f} 檔掛牌普通股，其中前 300 大進入股票池；入選股票中平均 {us['later_delisted'].mean():.1f} 檔（最多 {us['later_delisted'].max():.0f} 檔）在資料截點前已下市，這些股票在回測中被保留。資料可得日檢查（availability_checks.csv）顯示：各調倉日使用的 ESG 最新公告日皆不晚於調倉日；規則式 ESG 篩選投組的持股分數與「調倉日前已公告的最新 TESG」逐筆核對，不一致筆數為 {bad}；{inu:.0%} 的調倉日持股全部屬於當期股票池。附錄 C 列出三個調倉日的人工核對範例。")
    # 二
    R.h(2, "二、整體績效")
    R.caption(f"表 4-1　績效比較（{start_eval} ～ {cut}）")
    rows = []
    for c in ORDER:
        r = t41.loc[c]
        rows.append([c, pct(r["累積報酬"]), pct(r["年化報酬"]), f"{pct(r['年化報酬95%CI下限'],0)}～{pct(r['年化報酬95%CI上限'],0)}",
                     pct(r["年化波動"]), num(r["Sharpe"]), pct(r["最大回撤"]), num(r.get("Beta")), num(r.get("R2"))])
    R.table(["投組", "累積報酬", "年化報酬", "年化 95% CI", "年化波動", "Sharpe", "最大回撤", "Beta", "R²"], rows,
            [2.2, 1.3, 1.2, 1.7, 1.1, 1.25, 1.25, 0.8, 0.7], "lrrrrrrrr", size=9.5)
    R.note("註：年化 95% CI 為移動區塊 bootstrap（區塊 20 日、2,000 次）。Beta 與 R² 以加權指數為市場、日頻 CAPM 估計。來源：tables/table_4_1_performance.csv。")
    a, ae, e = t41.loc["單純 AI"], t41.loc["AI+ESG"], t41.loc["規則式 ESG 篩選"]
    rank = t41["年化報酬"].sort_values(ascending=False)
    R.p(f"評估期間年化報酬由高到低依序為：{'、'.join(f'{k}（{pct(v)}）' for k, v in rank.items())}。單純 AI 年化 {pct(a['年化報酬'])}，{lead_lag(a['年化報酬'], t41.loc['0050','年化報酬'])} 0050、{lead_lag(a['年化報酬'], t41.loc['00850','年化報酬'])} 00850；AI+ESG 年化 {pct(ae['年化報酬'])}；規則式 ESG 篩選年化 {pct(e['年化報酬'])}。三個策略的夏普值分別為 {num(a['Sharpe'])}、{num(ae['Sharpe'])}、{num(e['Sharpe'])}，都低於 0050（{num(t41.loc['0050','Sharpe'])}）與 00850（{num(t41.loc['00850','Sharpe'])}）；單純 AI 與 AI+ESG 的最大回撤（{pct(a['最大回撤'])}、{pct(ae['最大回撤'])}）也明顯深於 ETF。年化報酬的 95% 信賴區間相當寬（單純 AI 為 {pct(a['年化報酬95%CI下限'],0)}～{pct(a['年化報酬95%CI上限'],0)}），反映約 {years:.1f} 年的樣本對報酬估計的不確定性很大。")
    R.image(*fig_path("fig_nav.png", "fig-4-1"))
    R.caption("圖 4-1　累積淨值（對數刻度）")
    # 三 穩健性
    R.h(2, "三、股票池建構與調倉日期的影響")
    R.p("為了解股票池的建構方式與調倉日期對結果的影響，本研究在其他設定完全相同的情況下，另外執行兩個對照（表 4-2）：(1) 股票池改用平台網站的做法，即「資料截點當時」成交金額前 300 大的現存股票套用到整段歷史；(2) 調倉日期網格改從 2019-01-02 起算（長期間回測），使調倉日與模型重新訓練的時點和正式版本不同。")
    lr = t37[t37["period"] == "exploratory_evaluation"].set_index("投組")["ann_return"] if len(t37) else pd.Series(dtype=float)
    rows = [["正式版本：逐期股票池（含下市股）、調倉自評估期起點", pct(a["年化報酬"]), pct(ae["年化報酬"]), pct(e["年化報酬"])]]
    if cu is not None:
        rows.append(["對照 1：股票池＝資料截點當時的前 300 大（平台網站做法）", pct(cu.loc["單純 AI", "年化報酬"]), pct(cu.loc["AI+ESG", "年化報酬"]), pct(cu.loc["規則式 ESG 篩選", "年化報酬"])])
    if len(lr):
        rows.append(["對照 2：逐期股票池，調倉日期網格自 2019-01-02 起算", pct(lr.get("單純 AI")), pct(lr.get("AI+ESG")), pct(lr.get("規則式 ESG 篩選"))])
    R.caption("表 4-2　股票池與調倉日期對年化報酬的影響（評估期間）")
    R.table(["設定", "單純 AI", "AI+ESG", "規則式 ESG 篩選"], rows, [5.8, 1.4, 1.4, 1.6], "lrrr")
    R.note(f"註：比較基準不受影響（0050 年化 {pct(t41.loc['0050','年化報酬'])}、00850 年化 {pct(t41.loc['00850','年化報酬'])}）。對照 1 由 run_research.py --test-yahoo 產生（outputs/research/{CFG['run_id']}_current_universe/）；對照 2 來自 strategy_returns_long.csv。")
    if len(sv):
        s_ai = sv[sv["portfolio"] == "單純 AI"].set_index("in_current_top300")
        if True in s_ai.index and False in s_ai.index:
            share = s_ai.loc[False, "count"] / s_ai["count"].sum()
            R.p(f"對照 1 的年化報酬遠高於正式版本，主要原因是後見之明偏誤：用「現在」的熱門股回頭建構過去的股票池，等於事先排除了之後表現不佳或下市的股票。正式版本中，單純 AI 的持股有 {share:.0%} 不在資料截點當時的前 300 大名單內，這些持股的平均每期（10 個交易日）報酬為 {pct(s_ai.loc[False,'mean'],2)}，其餘持股為 {pct(s_ai.loc[True,'mean'],2)}（holding_period_returns.csv）。對照 2 則顯示，僅改變調倉日期網格，單純 AI 的年化報酬就變動約 {abs(lr.get('單純 AI', np.nan) - a['年化報酬'])*100:.0f} 個百分點，說明結果對調倉時點相當敏感。平台網站目前沿用對照 1 的股票池，其顯示的報酬應視為高估。")
    # 四 年度
    R.h(2, "四、年度報酬")
    yr = t42.copy()
    rows = [[str(int(i)) + ("（11～12 月）" if int(i) == 2022 else "（至 10/20）" if int(i) == 2026 else "")] + [pct(yr.loc[i, c]) for c in ORDER] for i in yr.index]
    R.caption("表 4-3　各年度報酬")
    R.table(["年度"] + ORDER, rows, [1.9, 1.15, 1.15, 1.35, 1.05, 1.05, 1.05, 1.15], "lrrrrrrr", size=9.5)
    R.note("來源：tables/table_4_2_yearly.csv。")
    beat = [int(i) for i in yr.index if 2023 <= int(i) <= 2025 and yr.loc[i, "單純 AI"] > max(yr.loc[i, b] for b in ["0050", "00850", "00878", "加權指數"])]
    lose = [int(i) for i in yr.index if 2023 <= int(i) <= 2025 and yr.loc[i, "單純 AI"] < yr.loc[i, "加權指數"]]
    R.p(f"完整年度（2023～2025）中，單純 AI 報酬高於加權指數與三檔 ETF 的年度為 {('、'.join(map(str, beat)) or '無')}，低於加權指數的年度為 {('、'.join(map(str, lose)) or '無')}；各策略的年度表現起伏都很大，沒有任何策略每年穩定領先。")
    # 五 情境
    R.h(2, "五、市場情境與參與率")
    reg = t43.set_index("regime")
    rows = []
    for g in ["多頭", "盤整", "高波動", "空頭"]:
        if g in reg.index:
            rows.append([g, f"{int(reg.loc[g,'days'])}"] + [pct(reg.loc[g, f"{c}|ann_mean"], 0) for c in ORDER])
    R.caption("表 4-4　各市場情境的平均年化報酬（事前規則分類）")
    R.table(["情境", "日數"] + ORDER, rows, [1.1, 0.8, 1.2, 1.2, 1.4, 1.05, 1.05, 1.05, 1.15], "lrrrrrrrr", size=9.5)
    R.note("註：數值為該情境日報酬平均 × 252（算術年化），用於比較相對表現，非實際可得報酬；空頭情境天數少且多為急跌後的反彈期，估計誤差大。來源：tables/table_4_3_regimes.csv、regimes.csv。")
    R.caption("表 4-5　上漲日／下跌日參與率")
    rows = [[c, num(t44.loc[c, "up_capture"]), num(t44.loc[c, "down_capture"])] for c in ORDER if c in t44.index]
    R.table(["投組", "上漲日參與率", "下跌日參與率"], rows, [3.0, 2.0, 2.0], "lrr")
    R.note("註：參與率 = 加權指數上漲（下跌）日的策略平均日報酬 ÷ 加權指數平均日報酬。來源：tables/table_4_4_capture.csv。")
    lead = [g for g in ["多頭", "盤整", "高波動", "空頭"] if g in reg.index and reg.loc[g, "單純 AI|ann_mean"] > reg.loc[g, "00850|ann_mean"]]
    lag = [g for g in ["多頭", "盤整", "高波動", "空頭"] if g in reg.index and g not in lead]
    R.p(f"以 00850 為對照，單純 AI 在{('、'.join(lead) or '任何')}情境的平均報酬較高，在{('、'.join(lag) or '任何')}情境較低。參與率方面，單純 AI 上漲日 {num(t44.loc['單純 AI','up_capture'])}、下跌日 {num(t44.loc['單純 AI','down_capture'])}，漲跌都比大盤放大；規則式 ESG 篩選分別為 {num(t44.loc['規則式 ESG 篩選','up_capture'])} 與 {num(t44.loc['規則式 ESG 篩選','down_capture'])}，漲跌都比大盤小，呈現防禦性。")
    # 六 檢定
    R.h(2, "六、統計檢定")
    R.caption("表 4-6　CAPM 估計（日頻，Newey-West 標準誤）")
    rows = []
    for c in ["單純 AI", "AI+ESG", "規則式 ESG 篩選", "0050", "00850", "00878"]:
        r = t45.loc[c]
        rows.append([c, f"{int(r['n'])}", f"{r['alpha_d']*1e4:.2f}".replace("-", "−"), f"{r['alpha_se']*1e4:.2f}",
                     f"[{r['alpha_ci_lo']*1e4:.2f}, {r['alpha_ci_hi']*1e4:.2f}]".replace("-", "−"), pv(r["alpha_p"]), pv(r["alpha_p_holm"]),
                     f"{r['beta']:.2f}（{r['beta_se']:.2f}）", f"{r['r2']:.2f}"])
    R.table(["投組", "n", "日 α (bps)", "HAC 標準誤", "95% CI", "p", "Holm p", "β (標準誤)", "R²"], rows,
            [2.0, 0.6, 1.2, 1.1, 1.9, 0.8, 0.8, 1.8, 0.6], "lrrrrrrrr", size=9.5)
    R.note(f"註：市場為加權指數（價格指數，不含股利，因此含息 ETF 的 α 會偏正），無風險利率年 1%；落後期數 {int(t45['lags'].iloc[0])}。Holm 調整涵蓋本表 6 個 α 檢定。來源：tables/table_4_5_capm_hac.csv。")
    R.caption("表 4-7　日報酬差異檢定（策略 − 基準，Newey-West 標準誤）")
    rows = []
    for _, r in t46.iterrows():
        rows.append([f"{r['策略']} − {r['基準']}", f"{r['est']*1e4:.2f}".replace("-", "−"), f"{r['se']*1e4:.2f}",
                     f"[{r['ci_lo']*1e4:.2f}, {r['ci_hi']*1e4:.2f}]".replace("-", "−"), pct(r["ann_diff"], 1, True),
                     num(r["ir_ann"]), pv(r["p"]), pv(r["p_holm"])])
    R.table(["比較", "日差（bps）", "HAC 標準誤", "95% CI", "年化差", "資訊比率", "p", "Holm p"], rows,
            [3.0, 1.1, 1.1, 1.8, 1.1, 1.0, 0.8, 0.9], "lrrrrrrr", size=9.5)
    R.note(f"註：n = {int(t46['n'].iloc[0])} 個交易日。Holm 調整涵蓋本表全部 {len(t46)} 個比較。年化差 = 日差 × 252；資訊比率 = 日差平均 ÷ 日差標準差 × √252。來源：tables/table_4_6_diff_hac.csv。")
    sig = t46[t46["p_holm"] < 0.05]
    raw = t46[(t46["p"] < 0.05) & (t46["p_holm"] >= 0.05)]
    txt = "以 Holm 調整後 p < 0.05 為準，" + ("、".join(f"{r['策略']} 相對 {r['基準']}" for _, r in sig.iterrows()) + " 達到顯著；" if len(sig) else "沒有任何比較達到顯著：")
    txt += f"三個策略相對加權指數與各 ETF 的日報酬差，點估計有正有負，95% 信賴區間皆包含 0。CAPM 方面，三個策略的 α 都不顯著（Holm p 分別為 {pv(t45.loc['單純 AI','alpha_p_holm'])}、{pv(t45.loc['AI+ESG','alpha_p_holm'])}、{pv(t45.loc['規則式 ESG 篩選','alpha_p_holm'])}）。"
    if len(raw):
        txt += "另有" + "、".join(f"{r['策略']}相對 {r['基準']}（年化差 {pct(r['ann_diff'],1,True)}，未調整 p = {pv(r['p'])}）" for _, r in raw.iterrows()) + "在未調整時 p < 0.05，但經多重比較調整後不顯著。"
    R.p(txt + "因此本研究不能宣稱任何策略「顯著優於」市售 ETF。")
    # 七 成本
    R.h(2, "七、交易成本與滑價敏感度")
    R.caption("表 4-8　換股與交易成本")
    rows = [[c, f"{int(t49a.loc[c,'rebalances'])}", pct(t49a.loc[c, "avg_turnover"]), pct(t49a.loc[c, "total_cost"])] for c in STR if c in t49a.index]
    R.table(["投組", "調倉次數", "平均週轉率（單邊）", "累計交易成本"], rows, [3.0, 1.6, 2.4, 2.4], "lrrr")
    R.note("註：累計交易成本為各次換股成本的加總（占當時淨值比例）。來源：tables/table_4_9a_turnover_cost.csv。")
    R.caption("表 4-9　滑價敏感度（每邊額外成本）")
    rows = []
    for sb in sorted(t49b["slippage_bps"].unique()):
        for c in STR:
            r = t49b[(t49b["slippage_bps"] == sb) & (t49b["投組"] == c)]
            if len(r):
                r = r.iloc[0]
                rows.append([f"{int(sb)} bps", c, pct(r["年化報酬"]), num(r["Sharpe"]), pct(r["相對00850年化差"], 1, True), num(r["相對00850_HAC_t"])])
    R.table(["滑價", "投組", "年化報酬", "Sharpe", "相對 00850 年化差", "HAC t 值"], rows, [1.2, 2.6, 1.5, 1.2, 2.0, 1.3], "llrrrr")
    R.note("註：使用相同持股，只改變每次換股的成本重新計算（未重新訓練模型）。來源：tables/table_4_9b_slippage.csv。")
    s30 = t49b[(t49b["slippage_bps"] == 30)].set_index("投組")
    R.p(f"AI 策略每次調倉約換掉 {pct(t49a.loc['單純 AI','avg_turnover'],0)} 的持股，評估期間累計交易成本約 {pct(t49a.loc['單純 AI','total_cost'],0)}，對成本非常敏感：每邊加 30 bps 滑價後，單純 AI 年化報酬降至 {pct(s30.loc['單純 AI','年化報酬'])}、AI+ESG 降至 {pct(s30.loc['AI+ESG','年化報酬'])}，相對 00850 的差距轉為 {pct(s30.loc['單純 AI','相對00850年化差'],1,True)} 與 {pct(s30.loc['AI+ESG','相對00850年化差'],1,True)}；規則式 ESG 篩選因持股變動少，幾乎不受影響。此外，本研究假設能以收盤價成交，實務上下單時點、價格衝擊與資金規模都會進一步降低可實現報酬。")
    # 八 ESG
    R.h(2, "八、投組 ESG 品質")
    cols = [("esg_total", "TESG"), ("e_score", "E"), ("s_score", "S"), ("g_score", "G"), ("event_score", "事件雷達"), ("low_esg_share", "低 ESG 比例"), ("industry_hhi", "產業 HHI"), ("top_industry_share", "最大產業比重"), ("esg_coverage", "資料涵蓋率")]
    rows = []
    for c in ["單純 AI", "AI+ESG", "規則式 ESG 篩選", "股票池等權"]:
        r = t410.loc[c]
        rows.append([c] + [num(r[k], 1) if k in ("esg_total", "e_score", "s_score", "g_score", "event_score") else (num(r[k], 3) if k == "industry_hhi" else pct(r[k], 0)) for k, _ in cols])
    R.caption("表 4-10　投組 ESG 品質（各調倉日平均）")
    R.table(["投組"] + [b for _, b in cols], rows, [2.2, 0.9, 0.8, 0.8, 0.8, 1.1, 1.2, 1.1, 1.3, 1.2], "lrrrrrrrrr", size=9.5)
    R.note("註：分數為各調倉日持股權重加權平均（TEJ TESG 0～100）；低 ESG 比例 = TESG 位於當期股票池後 1/3 的持股權重；產業 HHI = 各產業權重平方和（越高越集中）。「股票池等權」為當期 300 檔等權，作為市場代理；ETF 歷史成分股取不到，未直接比較；碳強度資料未取得，未納入。來源：tables/table_4_10_esg_quality.csv、esg_quality_by_rebalance.csv。")
    q = eq[eq["date"] >= pd.Timestamp(start_eval)].pivot_table(index="date", columns="portfolio", values="esg_total")
    share = (q["AI+ESG"] > q["股票池等權"]).mean()
    share2 = (q["AI+ESG"] > q["單純 AI"]).mean()
    R.p(f"AI+ESG 的持股加權 TESG 平均 {num(t410.loc['AI+ESG','esg_total'],1)}，高於股票池等權的 {num(t410.loc['股票池等權','esg_total'],1)} 與單純 AI 的 {num(t410.loc['單純 AI','esg_total'],1)}；逐期比較，有 {share:.0%} 的調倉日高於股票池等權、{share2:.0%} 高於單純 AI。低 ESG 持股比例方面，AI+ESG 為 {pct(t410.loc['AI+ESG','low_esg_share'],0)}，單純 AI 為 {pct(t410.loc['單純 AI','low_esg_share'],0)}。三個策略的產業集中度（HHI {num(t410.loc['單純 AI','industry_hhi'],2)}～{num(t410.loc['規則式 ESG 篩選','industry_hhi'],2)}）都高於股票池等權（{num(t410.loc['股票池等權','industry_hhi'],2)}），20 檔持股的分散程度有限。事件雷達分數各投組差異不大，本研究不據此推論爭議風險的差異。")
    R.image(*fig_path("fig_esg.png", "fig-4-2"))
    R.caption("圖 4-2　各調倉日持股加權 TESG 分數")
    # 九 模型
    R.h(2, "九、模型選股能力與特徵重要性")
    rows = []
    for _, r in t47.iterrows():
        isic = "IC" in r["指標"]
        rows.append([r["指標"], f"{r['est']:.4f}" if isic else pct(r["est"], 2), f"{r['se']:.4f}" if isic else pct(r["se"], 2),
                     f"[{r['ci_lo']:.3f}, {r['ci_hi']:.3f}]" if isic else f"[{pct(r['ci_lo'],2)}, {pct(r['ci_hi'],2)}]",
                     pv(r["p"]), pct(r["positive_share"], 0), f"{int(r['n'])}"])
    R.caption("表 4-11　模型選股能力（每次調倉，Newey-West 標準誤）")
    R.table(["指標", "平均", "HAC 標準誤", "95% CI", "p", "大於 0 比例", "期數"], rows, [3.2, 1.1, 1.2, 1.8, 0.8, 1.1, 0.8], "lrrrrrr", size=9.5)
    R.note("註：Rank IC = 每次調倉預測排名與實際 10 日報酬排名的 Spearman 相關；超額報酬為前 20 檔平均減股票池平均。來源：tables/table_4_7_model_skill.csv。")
    FEAT = {"bias_20": "月線乖離率", "dd_high20": "距 20 日高點跌幅", "vol_20": "20 日波動率", "mom_20": "近 20 日報酬", "gap_ma60": "季線乖離率",
            "reversal": "短期反轉", "vol_ratio": "量能比", "mom_60": "近 60 日報酬", "mom_5": "近 5 日報酬", "pe": "本益比", "pb": "股價淨值比",
            "dividend_yield": "殖利率", "down_streak": "連續下跌天數", "days_since_high20": "高點距今天數"}
    if len(t48a):
        top = t48a.head(10)
        perm = t48b.set_index("feature") if len(t48b) else pd.DataFrame()
        rows = [[FEAT.get(f, f), pct(r["mean"], 1), pct(r["sd"], 1), f"{pct(r['min'],0)}～{pct(r['max'],0)}", pct(r["top3_share"], 0),
                 (f"{perm.loc[f,'ic_drop_mean']:.4f}".replace("-", "−") if len(perm) and f in perm.index else "—")] for f, r in top.iterrows()]
        R.caption("表 4-12　特徵重要性：各次訓練的分布與 permutation importance")
        R.table(["特徵", "平均重要性", "標準差", "範圍", "前三名比例", "Permutation（IC 下降）"], rows, [2.6, 1.4, 1.2, 1.6, 1.4, 1.8], "lrrrrr", size=9.5)
        ev = t48b["eval_dates"].iloc[0] if len(t48b) else ""
        bic = t48b["base_ic"].iloc[0] if len(t48b) else np.nan
        R.note(f"註：內建重要性為 {int(top['n_trainings'].iloc[0])} 次訓練的分布；permutation importance 另以 {t48b['train_end'].iloc[0] if len(t48b) else ''} 以前的資料訓練模型，在之後的調倉日（{ev}）逐一在同日內打亂某特徵，計算 Rank IC 平均下降（10 次平均；該模型在評估窗的 Rank IC 為 {bic:.4f}）。重要性只描述模型使用特徵的程度，不代表因果關係。來源：tables/table_4_8a_importance_distribution.csv、table_4_8b_permutation_importance.csv。")
    ic, tp = t47.iloc[0], t47.iloc[1]
    f3 = "、".join(FEAT.get(f, f) for f in t48a.index[:3])
    R.p(f"平均 Rank IC 為 {ic['est']:.4f}（HAC p = {pv(ic['p'])}），{pct(ic['positive_share'],0)} 的調倉日為正，模型的整體排序能力{'幾乎為零、統計上不顯著' if ic['p'] >= 0.05 else '為正且顯著'}；前 20 檔每期平均超額報酬 {pct(tp['est'],2)}（未扣成本，HAC p = {pv(tp['p'])}），顯示模型對排名最前段的股票略有辨識力，但扣除每期約 {pct(t49a.loc['單純 AI','total_cost']/t49a.loc['單純 AI','rebalances'],2)} 的交易成本後所剩無幾。內建重要性在各次訓練中相當穩定，{f3}在多數訓練中居前三，價格類特徵遠比估值重要，與 Gu et al.（2020）的發現一致；但 permutation 評估窗內模型本身幾乎沒有排序能力，因此特徵重要性只能描述模型如何使用資料，不能解讀為預測報酬的可靠因子。")
    # 十 假說
    R.h(2, "十、假說檢驗彙整")
    h = []
    e_tw, e_850 = d46("規則式 ESG 篩選", "加權指數"), d46("規則式 ESG 篩選", "00850")
    h.append(["H1　規則式 ESG 篩選優於大盤與 00850", "支持" if max(e_tw["p_holm"], e_850["p_holm"]) < 0.05 and min(e_tw["est"], e_850["est"]) > 0 else "未獲支持",
              f"相對加權指數年化差 {pct(e_tw['ann_diff'],1,True)}（Holm p = {pv(e_tw['p_holm'])}）、相對 00850 {pct(e_850['ann_diff'],1,True)}（p = {pv(e_850['p_holm'])}）；主要特色是低 Beta 與較小回撤"])
    x = d46("AI+ESG", "規則式 ESG 篩選")
    h.append(["H2　AI+ESG 優於規則式 ESG 篩選", "支持" if x["p_holm"] < 0.05 and x["est"] > 0 else ("點估計為正但不顯著" if x["est"] > 0 else "未獲支持"),
              f"年化差 {pct(x['ann_diff'],1,True)}，Holm p = {pv(x['p_holm'])}；報酬提升伴隨波動與回撤上升"])
    y = d46("AI+ESG", "00850"); al = t45.loc["AI+ESG"]
    h.append(["H3　AI+ESG 相對 00850 有顯著超額報酬", "支持" if y["p_holm"] < 0.05 and al["alpha_p_holm"] < 0.05 and y["est"] > 0 else "未獲支持",
              f"日報酬差年化 {pct(y['ann_diff'],1,True)}（Holm p = {pv(y['p_holm'])}）；CAPM α Holm p = {pv(al['alpha_p_holm'])}"])
    h.append(["H4　不同情境表現不同", "描述性支持",
              f"相對 00850，單純 AI 在{('、'.join(lead) or '—')}情境較佳、在{('、'.join(lag) or '—')}情境較差；情境天數不均，未做正式檢定"])
    h.append(["H5　AI+ESG 保有永續品質", "支持（描述性）" if t410.loc["AI+ESG", "esg_total"] > t410.loc["股票池等權", "esg_total"] else "未獲支持",
              f"持股加權 TESG {num(t410.loc['AI+ESG','esg_total'],1)}，股票池 {num(t410.loc['股票池等權','esg_total'],1)}、單純 AI {num(t410.loc['單純 AI','esg_total'],1)}；{share:.0%} 的調倉日高於股票池"])
    R.caption("表 4-13　假說檢驗彙整")
    R.table(["假說", "結果", "依據"], h, [3.0, 1.8, 5.2], "lll")


# ------------------------------------------------------------------ 第五章
def ch5(R):
    a, ae, e = t41.loc["單純 AI"], t41.loc["AI+ESG"], t41.loc["規則式 ESG 篩選"]
    R.h(1, "第五章　結論與建議")
    R.h(2, "一、研究發現")
    R.p(f"在本研究所使用的股票樣本（逐期成交金額前 300 大、含之後下市的股票）、資料截點（{cut}）與交易假設（收盤價成交、手續費與證交稅）下：")
    x = d46("單純 AI", "00850")
    cu_txt = f"若改用資料截點當時的前 300 大作為整段期間的股票池，單純 AI 年化報酬會變成 {pct(cu.loc['單純 AI','年化報酬'])}，" if cu is not None else ""
    R.bullets([f"**修正股票池後，AI 選股不再明顯領先 ETF：**單純 AI 年化 {pct(a['年化報酬'])}（95% CI {pct(a['年化報酬95%CI下限'],0)}～{pct(a['年化報酬95%CI上限'],0)}），0050 為 {pct(t41.loc['0050','年化報酬'])}、00850 為 {pct(t41.loc['00850','年化報酬'])}；相對 00850 的日報酬差 Holm p = {pv(x['p_holm'])}。夏普值 {num(a['Sharpe'])} 低於 ETF，最大回撤 {pct(a['最大回撤'])}。",
               f"**股票池的後見之明偏誤是先前高報酬的主要來源：**{cu_txt}平台網站與本研究初稿採用的就是這種做法，其顯示的高報酬應視為高估。",
               f"**ESG 評分的價值偏向風險控制：**規則式 ESG 篩選投組年化 {pct(e['年化報酬'])}，和大盤及 00850 都沒有顯著差異，但 Beta {num(e['Beta'])}、回撤較小、交易成本極低。",
               f"**AI+ESG 保有較高的永續品質，但報酬未顯著提升：**年化 {pct(ae['年化報酬'])}，持股加權 TESG {num(t410.loc['AI+ESG','esg_total'],1)} 高於股票池與單純 AI；相對 00850 與規則式 ESG 篩選的差異均不顯著。",
               f"**交易成本與時點敏感：**AI 策略平均週轉率約 {pct(t49a.loc['單純 AI','avg_turnover'],0)}，每邊 20 bps 滑價即讓單純 AI 落後 00850（AI+ESG 在無滑價時已落後）；僅改變調倉日期網格，年化報酬就有明顯差異。"])
    R.h(2, "二、影響結論的條件與研究限制")
    R.bullets(["**參數選擇與測試期重疊：**模型、持股數、調倉頻率與特徵是在涵蓋評估期的資料上比較後選定，評估期結果屬探索性，可能因資料探勘而偏樂觀；真正的保留測試從 2026-10-21 才開始。",
               "**存活者偏誤已降低但未完全排除：**股票池已改為逐期重建並保留下市股票，但下市後以最後收盤價計算，未反映下市前的流動性折價；上市股票的成交金額以 Yahoo 收盤價 × 成交量近似；上櫃股缺少估值資料。",
               "**交易可執行性：**假設以收盤價成交、無資金容量限制；未設單筆成交量上限。",
               "**ETF 可比性：**00850、00878 的成分、權重、再平衡與費用皆與本研究投組不同；ETF 歷史成分無法取得，ESG 品質比較只能以股票池代理。",
               "**比較基準：**加權指數為價格指數（不含股利），會讓含息投組相對大盤的超額報酬偏高，因此主要比較以含息 ETF 為準。",
               "**ESG 資料期數有限：**TEJ TESG 自 2022-11 起僅 8 期、半年更新；原規劃的爭議與 EPS 排除條件因欄位不足未能套用。"])
    R.h(2, "三、結論表述")
    R.p("綜合上述，本研究的主要結論為：「在本研究所使用的逐期股票樣本（含已下市股票）、資料截點與交易假設下，AI 與 ESG 結合策略維持了較高的持股 ESG 分數，但其歷史回測報酬並未顯著優於市售 ESG ETF；先前以現存熱門股建構股票池所得的高報酬，主要來自後見之明偏誤。結果不能代表未來可實現報酬。」")
    R.h(2, "四、管理意涵")
    R.bullets(["評估任何 AI 選股回測時，應優先確認股票池是否逐期建構、是否含下市股、參數選擇期間與交易成本假設；本研究顯示這些設定足以改變結論。",
               "對重視永續與穩定的投資人，ESG ETF 或規則式 ESG 篩選投組以較低成本提供相近報酬與較低波動。",
               "AI+ESG 可在不犧牲太多報酬的情況下提高持股 ESG 品質，但高週轉帶來的成本是實務上的主要障礙，可考慮降低調倉頻率或加入換手限制。"])
    R.h(2, "五、後續研究")
    R.bullets(["以鎖定設定追蹤 2026-10-21 之後的保留測試，至少累積一年後再評估。",
               "將平台網站的股票池也改為逐期建構，並以本研究的檢定方式定期更新。",
               "加入換手率限制、較長持有期或成交量限制，檢驗降低交易成本後的淨報酬。",
               "以 Fama-French 或台灣多因子模型拆解報酬來源；取得 ETF 歷史成分、碳排放與爭議事件資料，直接比較永續品質。"])


# ------------------------------------------------------------------ 參考文獻、附錄
REFS = [
    "鄭雅萍（2025）。機器學習下 ESG 選股之投資績效探討〔碩士論文，國立勤益科技大學〕。臺灣博碩士論文知識加值系統。https://hdl.handle.net/11296/m62b99",
    "Breiman, L. (2001). Random forests. Machine Learning, 45(1), 5–32. https://doi.org/10.1023/A:1010933404324",
    "Brown, S. J., Goetzmann, W., Ibbotson, R. G., & Ross, S. A. (1992). Survivorship bias in performance studies. The Review of Financial Studies, 5(4), 553–580. https://doi.org/10.1093/rfs/5.4.553",
    "Carlei, V., Furia, D., Ceccarelli, A., & Cascioli, P. (2025). Outperforming ESG stocks portfolio: A machine learning ranking model with catboots regressor. The North American Journal of Economics and Finance, 80, 102517. https://doi.org/10.1016/j.najef.2025.102517",
    "Chen, T., & Guestrin, C. (2016). XGBoost: A scalable tree boosting system. Proceedings of the 22nd ACM SIGKDD International Conference on Knowledge Discovery and Data Mining, 785–794. https://doi.org/10.1145/2939672.2939785",
    "Friede, G., Busch, T., & Bassen, A. (2015). ESG and financial performance: Aggregated evidence from more than 2000 empirical studies. Journal of Sustainable Finance & Investment, 5(4), 210–233. https://doi.org/10.1080/20430795.2015.1118917",
    "Gu, S., Kelly, B., & Xiu, D. (2020). Empirical asset pricing via machine learning. The Review of Financial Studies, 33(5), 2223–2273. https://doi.org/10.1093/rfs/hhaa009",
    "Harvey, C. R., Liu, Y., & Zhu, H. (2016). … and the cross-section of expected returns. The Review of Financial Studies, 29(1), 5–68. https://doi.org/10.1093/rfs/hhv059",
    "Holm, S. (1979). A simple sequentially rejective multiple test procedure. Scandinavian Journal of Statistics, 6(2), 65–70.",
    "Jensen, M. C. (1968). The performance of mutual funds in the period 1945–1964. The Journal of Finance, 23(2), 389–416. https://doi.org/10.1111/j.1540-6261.1968.tb00815.x",
    "Künsch, H. R. (1989). The jackknife and the bootstrap for general stationary observations. The Annals of Statistics, 17(3), 1217–1241. https://doi.org/10.1214/aos/1176347265",
    "Newey, W. K., & West, K. D. (1987). A simple, positive semi-definite, heteroskedasticity and autocorrelation consistent covariance matrix. Econometrica, 55(3), 703–708. https://doi.org/10.2307/1913610",
    "Newey, W. K., & West, K. D. (1994). Automatic lag selection in covariance matrix estimation. The Review of Economic Studies, 61(4), 631–653. https://doi.org/10.2307/2297912",
    "Novy-Marx, R., & Velikov, M. (2016). A taxonomy of anomalies and their trading costs. The Review of Financial Studies, 29(1), 104–147. https://doi.org/10.1093/rfs/hhv063",
    "Pedersen, L. H., Fitzgibbons, S., & Pomorski, L. (2021). Responsible investing: The ESG-efficient frontier. Journal of Financial Economics, 142(2), 572–597. https://doi.org/10.1016/j.jfineco.2020.11.001",
    "Shen, K.-Y. (2024). Fuzzy–rough analysis of ESG ratings and financial and growth ratios on the stock returns of blue-chip stocks in Taiwan. Mathematics, 12(16), 2511. https://doi.org/10.3390/math12162511",
    "Sullivan, R., Timmermann, A., & White, H. (1999). Data-snooping, technical trading rule performance, and the bootstrap. The Journal of Finance, 54(5), 1647–1691. https://doi.org/10.1111/0022-1082.00163",
    "元大證券投資信託（2026）。元大臺灣 ESG 永續 ETF（00850）產品資訊。https://www.yuantaetfs.com/product/detail/00850/（2026 年 10 月 25 日查詢）",
    "國泰證券投資信託（2026）。國泰永續高股息 ETF（00878）產品資訊。https://www.cathaysite.com.tw/（2026 年 10 月 25 日查詢）",
]


def refs(R):
    R.h(1, "參考文獻")
    for r in REFS:
        p = R.doc.add_paragraph(); spacing(p, 0, 8, 1.5, left=Pt(0), hanging=Pt(24)); add_text(p, r, size=11)


def appendix(R):
    R.h(1, "附錄 A　研究版本與重現方式")
    R.p("在乾淨環境重現本論文的步驟：")
    for s in ["git clone https://github.com/Hendrick0815/ESG_AI_Dashboard.git 並切換到 manifest.json 記錄的 commit",
              "pip install -r requirements-lock.txt（固定版本）",
              "python scripts/backfill_daily_quotes.py 2017-07-03 2026-10-20 tpex（上櫃逐日行情；上市年度檔已存於 data/raw/daily_quotes_twse/）",
              "python scripts/research/run_research.py（約 30～60 分鐘；輸出 outputs/research/" + CFG["run_id"] + "/）",
              "python scripts/research/build_report.py（由表格檔產生本論文 Word／PDF 與網站表格檔）",
              "python scripts/research/capture_web.py（啟動網站並截取「論文正式版本」頁面的表格與圖），再執行一次 build_report.py 放入截圖",
              "pytest tests/（核心邏輯測試）"]:
        p = R.doc.add_paragraph(); spacing(p, 0, 3, 1.4, left=Pt(24), hanging=Pt(14)); add_text(p, "• " + s, size=11)
    R.caption("表 A-1　本次執行的版本紀錄")
    rows = [["執行時間", f"{man['started']} ～ {man['finished']}"], ["程式 commit", man.get("git_commit") or "（見程式檔雜湊值）"],
            ["Python／套件", f"Python {man['python']}；" + "、".join(f"{k} {v}" for k, v in man["packages"].items())],
            ["隨機種子", str(CFG["random_seed"])], ["訓練次數", str(man["summary"]["trainings"])]]
    for k, v in list(man["data_files_sha256"].items())[:8]:
        rows.append([k, v[:16] + "…"])
    R.table(["項目", "內容"], rows, [3.6, 6.4], "ll", size=9.5)
    R.note("註：完整 SHA-256 雜湊值見 manifest.json。")

    R.h(1, "附錄 B　資料字典")
    R.table(["檔案", "欄位", "說明與可得日"], [
        ["data/raw/daily_quotes/*.csv、daily_quotes_twse/*.csv.gz", "date, code, name, volume, value, close, sign, change, next_ref", "交易所逐日行情；當日收盤可得；含已下市股票"],
        ["data/processed/benchmarks.csv", "date, ticker, close…", "Yahoo 還原收盤價（ETF）與加權指數價格指數"],
        ["data/processed/valuation.csv", "available_date, ticker, pe, pb, dividend_yield", "證交所 BWIBBU 月底資料；資料日期當日可得"],
        ["data/raw/tej/*.csv", "代號、TESG評等季度、TESG評等公告日、TESG分數、E／S／G、事件雷達轉換計分", "以 TESG 評等公告日作為可得日"],
        ["outputs/research/…/universe_history.csv", "date, ticker, avg_value, n_days, rank", "逐期股票池（調倉日）"],
        ["outputs/research/…/holdings.csv", "date, portfolio, ticker, weight, score", "每次調倉持股"],
        ["outputs/research/…/strategy_returns.csv", "date, portfolio, ret, nav", "每日策略與基準報酬"],
        ["data/demo/", "—", "合成示範資料，僅供網站展示，未用於論文"]], [3.4, 3.6, 3.0], "lll", size=9.5)

    R.h(1, "附錄 C　人工核對範例")
    rows = [[str(r["rebalance_date"]), f"{r['ticker']} {r['name'] if isinstance(r['name'], str) else ''}", num(r["ai_score"], 4), f"{int(r['universe_rank'])}" if not pd.isna(r["universe_rank"]) else "—",
             num(r["avg_value_20d_億"], 1), str(r["esg_announce"])[:10] if isinstance(r["esg_announce"], str) else "—", num(r["esg_total"], 1)] for _, r in mc.iterrows()]
    R.table(["調倉日", "股票", "AI 分數", "股票池排名", "20 日均成交（億）", "TESG 公告日", "TESG"], rows, [1.6, 2.6, 1.1, 1.1, 1.4, 1.5, 0.9], "llrrrlr", size=9.5)
    R.note("註：每個調倉日列出單純 AI 分數最高的 5 檔，核對其股票池排名與使用的 TESG 公告日皆不晚於調倉日。來源：manual_checks.csv。")

    R.h(1, "附錄 D　指導教授修訂建議對照")
    R.table(["修訂建議", "處理方式", "位置"], [
        ["固定正式版本並重產表格", "研究設定檔、manifest、產表與產文程式；README 與 config 統一為 Top 20；資料截點 2026-10-20", "第三章第一節、附錄 A"],
        ["修正股票池與資料可得日", "以交易所逐日行情逐期重建前 300 大（含下市股）；可得日檢查表與人工核對", "第三章第二、三節；第四章第一節；附錄 C"],
        ["重新界定模型選擇與測試期間", "期間切分、參數試驗紀錄；評估期改列探索性；設定鎖定後保留測試", "第三章第七節"],
        ["補足統計檢定與交易假設", "Newey-West 標準誤、CAPM α／β／R²、信賴區間、效果量、Holm 調整；價格與交易假設表；10／20／30 bps 滑價", "第三章第八、九節；第四章第六、七節"],
        ["證明永續品質差異", "持股加權 TESG／E／S／G／事件雷達、低 ESG 比例、產業集中度、涵蓋率；ETF 成分不可得已註明", "第四章第八節"],
        ["市場情境事前規則", "60 日報酬、20 日波動、回撤門檻；涵蓋全部日期並報告天數", "表 3-10、表 4-4、表 4-5"],
        ["文獻補齊", "全部附 DOI；更正 S&P 500 文獻為 Carlei et al.（2025）；補台灣 ESG、機器學習資產定價、資料探勘、交易成本文獻", "第二章、參考文獻"],
        ["名詞與 ETF 差異", "「單純 ESG」改稱「規則式 ESG 篩選投組」；列出與 00850、00878 的差異", "表 3-4、表 3-5"],
        ["模型解釋", "各次訓練重要性分布＋permutation importance；避免因果敘述", "表 4-11、表 4-12"]], [2.6, 5.2, 2.2], "lll", size=9.5)


# ------------------------------------------------------------------ 產出
# 用網站「論文正式版本」頁面截圖取代的表格與圖（scripts/research/capture_web.py 產生 report/web/*.png）
WEB = OUT / "web"
SHOOT = {"3-3", "3-7", "3-8"} | {f"4-{i}" for i in range(1, 13)}


def web_shots():
    if os.environ.get("WEB_SHOTS", "1") == "0" or not WEB.exists():
        return {}
    return {k: WEB / f"{k}.png" for k in SHOOT if (WEB / f"{k}.png").exists()}


def fig_path(name, web_name):
    w = WEB / f"{web_name}.png"
    return (w, Report.shot_width(w)) if web_shots() and w.exists() else (OUT / name, 15.5)


def build(pages):
    R = Report(shots=web_shots())
    # 先收集標題（第一次組版）
    R.toc_items = getattr(build, "items", [])
    compose(R, pages)
    items = [(l, t) for l, t in R.headings if l in (1, 2) and t not in ("致謝", "摘要", "目錄")]
    return R, items


def find_pages(pdf, items):
    n = int(re.search(r"Pages:\s+(\d+)", subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout).group(1))
    T_ = [re.sub(r"\s+", "", subprocess.run(["pdftotext", "-f", str(k), "-l", str(k), str(pdf), "-"], capture_output=True, text=True).stdout) for k in range(1, n + 1)]
    start = next(k for k in range(n) if T_[k].startswith("第一章"))
    res, k = {}, start
    for i, (lvl, t) in enumerate(items):
        key = re.sub(r"\s+", "", t)
        j = k
        while j < n and key not in T_[j]:
            j += 1
        if j == n:
            j = k
        res[i] = j - start + 1; k = j
    return res


def main():
    figures()
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    build.items = []
    R, items = build({})
    build.items = items
    docx = OUT / f"{TITLE}_修訂版.docx"
    pages = {}
    for _ in range(3):
        R, items = build(pages)
        R.save(docx)
        if not soffice:
            break
        subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", str(OUT), str(docx)], capture_output=True)
        newp = find_pages(OUT / (docx.stem + ".pdf"), items)
        if newp == pages:
            break
        pages = newp
    # 表格內容另存一份給網站頁面（pages/5_論文正式版本.py）
    (OUT / "web_tables.json").write_text(json.dumps(R.web_tables, ensure_ascii=False, indent=1), encoding="utf-8")
    print("完成：", docx, "｜網站截圖", len(R.shots), "張")


if __name__ == "__main__":
    main()
