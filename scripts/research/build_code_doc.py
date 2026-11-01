"""產生獨立的「程式碼與網站內容對照」Word 檔（供指導教授檢查程式）。
內容：系統架構、程式檔清單、網站各頁截圖＋畫面區塊與程式位置對照＋關鍵程式碼、核心選股與回測程式、資料更新與部署、論文研究程式、測試。
程式碼與行號在產生時直接由程式檔讀取；截圖由 capture_pages.py 產生。

執行（在專案根目錄）：
    python scripts/research/capture_pages.py        # 先截網站各頁（需要時）
    python scripts/research/build_code_doc.py       # 產生 Word（有 LibreOffice 時另產生 PDF 以計算目錄頁碼）
輸出：outputs/research/<run_id>/report/ESG-AI平台_程式碼與網站內容對照.docx
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from docx.enum.text import WD_ALIGN_PARAGRAPH

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
from report_lib import Report, add_text, spacing  # noqa: E402
import appendix_code as ac  # noqa: E402

CFG = json.loads((ROOT / "research_config.json").read_text(encoding="utf-8"))
OUT = ROOT / "outputs" / "research" / CFG["run_id"] / "report"
NAME = "ESG-AI平台_程式碼與網站內容對照"
DATE = "中華民國 115 年 11 月 1 日"


def _rule(p, side):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    pPr = p._p.get_or_add_pPr(); b = OxmlElement("w:pBdr"); e = OxmlElement(f"w:{side}")
    e.set(qn("w:val"), "single"); e.set(qn("w:sz"), "12"); e.set(qn("w:space"), "1"); e.set(qn("w:color"), "000000")
    b.append(e); pPr.append(b)


def compose(R: Report, pages: dict):
    D = R.doc

    def C(text, size, bold=False, before=0, after=0):
        p = D.add_paragraph(); spacing(p, before, after, 1.5, align=WD_ALIGN_PARAGRAPH.CENTER); add_text(p, text, bold=bold, size=size)

    C("逢甲大學 財務金融學系", 26); C("115學年度 專題製作", 22, after=10)
    p = D.add_paragraph(); spacing(p, 14, 0, 1.0); _rule(p, "bottom")
    C("ESG-AI 台股選股平台", 26, bold=True, before=8)
    C("程式碼與網站內容對照", 24, bold=True, after=2)
    C("（專題「AI選股結合ESG與現有ETF的比較」附件，供程式檢查使用）", 13, after=8)
    p = D.add_paragraph(); spacing(p, 0, 26, 1.0); _rule(p, "top")
    t = D.add_table(rows=7, cols=2)
    from report_lib import borders
    from docx.shared import Cm
    borders(t, none=True)
    t.alignment = 1
    for i, (a, b) in enumerate([("指導教授：", "王鈺仁 老師"), ("班　　級：", "財金系 三年乙班"), ("組　　長：", "陳東杰 D1280673"),
                                 ("組　　員：", "陳亭翰 D1209072"), ("", "陳治嘉 D1222280"), ("", "黃彥霖 D1240092"), ("", "張建民 D1240121")]):
        for j, v in enumerate((a, b)):
            c = t.cell(i, j); c.width = Cm(4.2 if j == 0 else 7.0)
            spacing(c.paragraphs[0], 0, 0, 1.4); add_text(c.paragraphs[0], v, size=16)
    C(DATE, 15, before=36)
    C("程式碼：GitHub Hendrick0815/ESG_AI_Dashboard　網站：esgaidashboard.streamlit.app", 11, before=6)

    R.new_section(fmt="lowerRoman", start=1)
    R.h(1, "目錄")
    R.toc(pages)
    R.new_section(fmt="decimal", start=1)
    ac.appendix_e_detail(R, OUT / "pages", None, figure_fn=lambda: ac.architecture_figure(OUT / "fig_arch.png"),
                         standalone=True)


def build(pages):
    R = Report(shots={})
    R.toc_items = getattr(build, "items", [])
    compose(R, pages)
    items = [(l, t) for l, t in R.headings if l in (1, 2) and t != "目錄"]
    return R, items


def find_pages(pdf, items):
    n = int(re.search(r"Pages:\s+(\d+)", subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout).group(1))
    T = [re.sub(r"\s+", "", subprocess.run(["pdftotext", "-f", str(k), "-l", str(k), str(pdf), "-"],
                                           capture_output=True, text=True).stdout) for k in range(1, n + 1)]
    start = next(k for k in range(n) if T[k].startswith("說明"))
    res, k = {}, start
    for i, (_, t) in enumerate(items):
        key = re.sub(r"\s+", "", t)
        j = k
        while j < n and key not in T[j]:
            j += 1
        if j == n:
            j = k
        res[i] = j - start + 1
        k = j
    return res


def main():
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    build.items = []
    R, items = build({})
    build.items = items
    docx = OUT / f"{NAME}.docx"
    pages = {}
    for _ in range(3):
        R, items = build(pages)
        R.save(docx)
        if not soffice:
            break
        subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", str(OUT), str(docx)], capture_output=True)
        newp = find_pages(OUT / f"{NAME}.pdf", items)
        if newp == pages:
            break
        pages = newp
    print("完成：", docx)


if __name__ == "__main__":
    main()
