"""整理「下次繳交項目」：把六項繳交物放進同一個資料夾，並產生最終研究設定包（zip）與網站截圖彙整 PDF。

輸出：outputs/research/<run_id>/繳交資料/
  1_修訂後論文（修訂標示版）.pdf、1_修訂後論文（清稿）.pdf
  2_資料與交易時點稽核表.pdf
  3_下市與異常報酬查核附件.pdf（論文附錄 B 頁面）＋ 原始查核表 csv
  4_最終研究設定包.zip（設定檔、版本資訊、執行紀錄、輸出表格、程式執行說明與亂數種子）
  5_更新後網站截圖.pdf
  6_一頁式答辯摘要.pdf（答辯與重現資料第 1 頁）、6_答辯與重現資料（完整）.pdf
用法：python scripts/research/build_submission.py
"""
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from pypdf import PdfReader, PdfWriter

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from report_lib import Report  # noqa: E402

ROOT = HERE.parents[1]
CFG = json.loads((ROOT / "research_config.json").read_text(encoding="utf-8"))
RUN = ROOT / "outputs" / "research" / CFG["run_id"]
REP = RUN / "report"
AUD = ROOT / "outputs" / "research" / "audit_p1"
OUT = RUN / "繳交資料"
TAG = "thesis-v2-2026-10-20"


def pdf_pages(src, dst, start_text=None, first=None, last=None):
    rd = PdfReader(str(src))
    n = len(rd.pages)
    if start_text:
        first = next(i for i in range(n) if start_text in (rd.pages[i].extract_text() or ""))
        last = n - 1
    w = PdfWriter()
    for i in range(first, last + 1):
        w.add_page(rd.pages[i])
    with open(dst, "wb") as f:
        w.write(f)


def settings_pack():
    m = json.loads((RUN / "manifest.json").read_text(encoding="utf-8"))
    c = m["config"]
    readme = f"""# 最終研究設定包（{c['run_id']}）

版本標籤：{TAG}（GitHub：Hendrick0815/ESG_AI_Dashboard）｜資料截點：{c['data_cutoff']}｜原始基準版本：{c.get('baseline_run_id')}

## 內容
| 檔案 | 說明 |
|---|---|
| research_config.json | 研究設定檔（本版所有參數） |
| VERSION.md | 版本凍結紀錄：版本標籤、設定檔與執行紀錄雜湊值、各輸出表格雜湊值 |
| manifest.json | 執行紀錄：執行時間、Python 與套件版本、{len(m['data_files_sha256'])} 項輸入資料與 {len(m['code_sha256'])} 個程式檔之 SHA-256 |
| tables/*.csv | 論文第三、四章之輸出表格（論文數字皆由此讀取） |
| 執行說明.md | 本文件 |

## 亂數種子
| 用途 | 種子 | 程式位置 |
|---|---|---|
| 隨機森林模型 | random_state = 42 | src/models.py（固定為 42，與研究設定檔 random_seed 相同） |
| 全域 numpy 亂數 | np.random.seed({c['random_seed']}) | scripts/research/run_research.py |
| permutation importance | default_rng({c['random_seed']}) | scripts/research/run_research.py |
| 年化報酬區塊 bootstrap（區塊 20 日、2,000 次） | seed = 42 | src/research/stats.py bootstrap_ci_ann() |

## 程式執行說明
1. 取得程式：`git clone https://github.com/Hendrick0815/ESG_AI_Dashboard`，`git checkout {TAG}`。
2. 環境：Python {m['python']}；`pip install -r requirements.txt`（套件版本：{"、".join(f"{k} {v}" for k, v in m["packages"].items())}）。
3. 資料：data/raw/ 下之逐日行情、TEJ TESG、TEJ 股價（data/raw/tej/prices/）；以 manifest.json 之 SHA-256 核對。
4. 產生結果（版本已凍結，重現時請先把 research_config.json 的 run_id 改為新名稱）：
   - `python scripts/research/run_research.py`（主要分析，約 15 分鐘）
   - `python scripts/research/run_research.py --test-yahoo`（股票池對照：資料截點當時前 300 大）
   - `python scripts/research/descriptive_stats.py`（表 3-5 敘述統計）
   - `python scripts/research/run_market_state_tests.py`（表 4-15 探索性補充分析）
5. 產生文件：`build_report.py`（論文）→ `capture_web.py` → `build_report.py`（放入網站截圖）→ `capture_pages.py` → `build_code_doc.py`；
   另有 `build_timing_audit.py`（時點稽核表）、`build_defense_pack.py`（答辯與重現資料）、`mark_changes.py`（修訂標示版）。
6. 核對：新產出之 tables/*.csv 與 VERSION.md 所列雜湊值一致即完成重現。
"""
    z = OUT / "4_最終研究設定包.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as f:
        f.writestr("最終研究設定包/執行說明.md", readme)
        for name in ["research_config.json", "VERSION.md", "manifest.json"]:
            f.write(RUN / name, f"最終研究設定包/{name}")
        for t in sorted((RUN / "tables").glob("*.csv")):
            f.write(t, f"最終研究設定包/tables/{t.name}")
    return z


def web_shots_pdf():
    from PIL import Image
    pages = REP / "pages"
    tmp = OUT / "_crops"
    tmp.mkdir(exist_ok=True)

    def crop(name, frac):
        im = Image.open(pages / f"{name}.png")
        w, h = im.size
        p = tmp / f"{name}.png"
        im.crop((0, 0, w, min(h, int(w * frac)))).save(p)
        return p

    items = [
        ("圖 1　首頁：展示型回測警語", crop("home", 0.62),
         "首頁頂端以黃色警示框標示「展示型回測，非本研究主要結果」，說明股票池為「目前」前 300 大、含存活者偏誤，並附「前往本研究主要結果：逐期股票池回測」連結；回測期間不再稱為樣本外。"),
        ("圖 2　側邊欄：實驗功能標示", pages / "sidebar_exploratory.png",
         "側邊欄之「風險控制」與「短期轉弱減碼」均標示為「探索性補充分析」，預設關閉；說明文字註明為事後新增之設定、不取代研究主策略、未經樣本外檢驗。"),
        ("圖 3　策略回測頁：展示型回測警語", crop("backtest_perf", 0.62),
         "策略回測頁同樣於頂端顯示展示型回測警語與主要結果頁連結；期間選項為「全部回測期間」。"),
        ("圖 4　逐期股票池回測頁（本研究主要結果）", crop("thesis", 0.75),
         "動態（逐期）股票池結果頁：頂端列出本研究主張，說明固定設定、探索性歷史回測期、T+1 開盤成交與 TEJ 價格，並註明 p 值僅作樣本內描述；表格與論文第三、四章相同。"),
        ("圖 5　策略回測頁方法說明：探索性補充分析標示", crop("backtest_method", 1.6),
         "方法說明分頁中，「風險控制」與「短期轉弱減碼」小節標題註明「選用；探索性補充分析，不取代主策略」，回測規則載明 T+1 開盤成交。"),
    ]
    R = Report()
    R.h(1, "更新後網站截圖")
    R.p(f"網站：esgaidashboard.streamlit.app｜截圖日期：2026-11-23｜程式版本：{TAG}", indent=False, size=10)
    for i, (cap, img, desc) in enumerate(items):
        if i:
            R.page_break()
        R.caption(cap)
        R.image(img, width_cm=15.5)
        R.p(desc, indent=False, size=10.5)
    docx = tmp / "5_更新後網站截圖.docx"
    R.save(docx)
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", str(OUT), str(docx)], capture_output=True)
    shutil.rmtree(tmp)


def main():
    OUT.mkdir(exist_ok=True)
    shutil.copy(REP / "AI選股結合ESG與現有ETF的比較_修訂標示版.pdf", OUT / "1_修訂後論文（修訂標示版）.pdf")
    shutil.copy(REP / "AI選股結合ESG與現有ETF的比較_修訂版.pdf", OUT / "1_修訂後論文（清稿）.pdf")
    shutil.copy(AUD / "資料與交易時點稽核表.pdf", OUT / "2_資料與交易時點稽核表.pdf")
    pdf_pages(REP / "AI選股結合ESG與現有ETF的比較_修訂版.pdf", OUT / "3_下市與異常報酬查核附件.pdf", start_text="表 B-1")
    for f in ["下市股票稽核.csv", "極端報酬查核.csv", "停牌與零成交稽核.csv", "原價格來源與TEJ差異.csv"]:
        shutil.copy(AUD / f, OUT / f"3_{f}")
    settings_pack()
    web_shots_pdf()
    pdf_pages(REP / "答辯與重現資料.pdf", OUT / "6_一頁式答辯摘要.pdf", first=0, last=0)
    shutil.copy(REP / "答辯與重現資料.pdf", OUT / "6_答辯與重現資料（完整）.pdf")
    for f in sorted(OUT.iterdir()):
        print(f.name)


if __name__ == "__main__":
    main()
