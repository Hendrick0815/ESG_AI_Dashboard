"""產生「修訂標示版」論文：與前一次繳交版本比較，新增或修改的文字以紅字標示。

比較方式：
  - 段落（含表格儲存格）：與舊版最相近的段落逐字比對，只把新增／修改的字元標紅；完全新增的段落整段標紅。
  - 以網站截圖呈現的表格：比較 web_tables.json 中同名表格的內容（表頭、資料列、註），有變更時把表名標紅。
  - 目錄頁不標示（頁碼變動無意義）。刪除的文字不顯示。
用法：python scripts/research/mark_changes.py <舊版 docx> <舊版 web_tables.json> [基準說明]
輸出：outputs/research/<run_id>/report/AI選股結合ESG與現有ETF的比較_修訂標示版.docx／.pdf
"""
import copy
import difflib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.shared import Pt, RGBColor

ROOT = Path(__file__).resolve().parents[2]
CFG = json.loads((ROOT / "research_config.json").read_text(encoding="utf-8"))
REP = ROOT / "outputs" / "research" / CFG["run_id"] / "report"
NEW = REP / "AI選股結合ESG與現有ETF的比較_修訂版.docx"
OUT = REP / "AI選股結合ESG與現有ETF的比較_修訂標示版.docx"
RED = "C00000"
norm = lambda s: re.sub(r"\s+", "", s or "")


def all_paragraphs(doc):
    for p in doc.paragraphs:
        yield p
    for t in doc.tables:
        for row in t.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    yield p


def color_run(r_el):
    rpr = r_el.find(qn("w:rPr"))
    if rpr is None:
        rpr = OxmlElement("w:rPr"); r_el.insert(0, rpr)
    c = rpr.find(qn("w:color"))
    if c is None:
        c = OxmlElement("w:color"); rpr.append(c)
    c.set(qn("w:val"), RED)


def mark_paragraph(p, flags):
    """flags：與 p.text 等長的布林序列（True＝變更）。依旗標拆分 run 並把變更字元標紅。"""
    pos = 0
    for run in list(p.runs):
        t = run.text
        n = len(t)
        f = flags[pos:pos + n]
        pos += n
        if not n or not any(f):
            continue
        if all(f):
            color_run(run._r); continue
        # 拆分：連續相同旗標為一段
        segs, start = [], 0
        for i in range(1, n + 1):
            if i == n or f[i] != f[start]:
                segs.append((t[start:i], f[start])); start = i
        base = run._r
        for txt, chg in segs:
            new = copy.deepcopy(base)
            for tt in new.findall(qn("w:t")):
                new.remove(tt)
            te = OxmlElement("w:t"); te.text = txt; te.set(qn("xml:space"), "preserve"); new.append(te)
            if chg:
                color_run(new)
            base.addprevious(new)
        base.getparent().remove(base)


def caption_title(c):
    return re.sub(r"^(表|圖)\s*[0-9A-Z]+-[0-9]+[a-z]?\s*", "", c or "").strip()


def main():
    old_docx, old_wt = Path(sys.argv[1]), Path(sys.argv[2])
    label = sys.argv[3] if len(sys.argv) > 3 else "前一次繳交版本"
    old = Document(old_docx)
    old_paras = [norm(p.text) for p in all_paragraphs(old) if norm(p.text)]
    old_set = set(old_paras)
    # 截圖表格內容比較
    owt = {caption_title(t["caption"]): t for t in json.loads(old_wt.read_text(encoding="utf-8"))}
    nwt = {caption_title(t["caption"]): t for t in json.loads((REP / "web_tables.json").read_text(encoding="utf-8"))}
    key = lambda t: json.dumps([t["header"], t["rows"], t.get("note")], ensure_ascii=False)
    changed_tables = {k for k, t in nwt.items() if k not in owt or key(owt[k]) != key(t)}

    doc = Document(NEW)
    in_toc = False
    n_full = n_part = n_cap = 0
    for p in all_paragraphs(doc):
        txt = p.text
        s = norm(txt)
        if s == "目錄":
            in_toc = True; continue
        if in_toc:
            if s.startswith("第一章"):
                in_toc = False
            else:
                continue
        if not s or len(s) < 2:
            continue
        # 截圖表格之表名
        if re.match(r"^表\s*[0-9A-Z]+-[0-9]+", txt.strip()) and caption_title(txt.strip()) in nwt:
            if caption_title(txt.strip()) in changed_tables:
                mark_paragraph(p, [True] * len(txt)); n_cap += 1
            continue
        if s in old_set:
            continue
        cand = difflib.get_close_matches(s, old_paras, n=1, cutoff=0.5)
        if not cand:
            mark_paragraph(p, [True] * len(txt)); n_full += 1
            continue
        # 逐字比對（以去空白字串對齊，再映回原文位置）
        idx = [i for i, ch in enumerate(txt) if not ch.isspace()]
        sm = difflib.SequenceMatcher(None, cand[0], s, autojunk=False)
        fl_s = [True] * len(s)
        for a, b, size in sm.get_matching_blocks():
            for k in range(size):
                if size >= 2:            # 單一字元偶然相同不算未變更
                    fl_s[b + k] = False
        flags = [False] * len(txt)
        for j, i in enumerate(idx):
            flags[i] = fl_s[j]
        if any(flags):
            mark_paragraph(p, flags); n_part += 1

    # 頁首說明
    for sec in doc.sections:
        hp = sec.header.paragraphs[0] if sec.header.paragraphs else sec.header.add_paragraph()
        sec.header.is_linked_to_previous = False
        r = hp.add_run(f"修訂標示版：紅字為相對{label}之新增或修改內容；表格以網站截圖呈現者，內容有變更時表名標紅。")
        r.font.size = Pt(8); r.font.color.rgb = RGBColor(0xC0, 0x00, 0x00)
    doc.save(OUT)
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice:
        subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", str(REP), str(OUT)], capture_output=True)
    print(f"完成：{OUT}｜整段新增 {n_full}、部分修改 {n_part}、表格內容變更 {n_cap}（共 {len(changed_tables)} 個表格有變更）")


if __name__ == "__main__":
    main()
