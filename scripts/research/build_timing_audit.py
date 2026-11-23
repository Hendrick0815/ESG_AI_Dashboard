"""P1-2 繳交用：一頁「資料可得時點與成交時點稽核表」（含對應程式位置與修正後基準表）。

輸出：outputs/research/audit_p1/資料與交易時點稽核表.docx／.pdf，以及同名 .csv（程式位置的行號自動定位）。
用法：python scripts/research/build_timing_audit.py
"""
import re
import shutil
import subprocess
import sys
import json
from pathlib import Path

import pandas as pd
from docx.enum.section import WD_ORIENT
from docx.shared import Cm

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from report_lib import Report  # noqa: E402

CFG = json.loads((ROOT / "research_config.json").read_text(encoding="utf-8"))
RUN = ROOT / "outputs" / "research" / CFG["run_id"]
OUT = ROOT / "outputs" / "research" / "audit_p1"


def span(path, func):
    """回傳「path func()（第 a–b 行）」：a 為 def 行，b 為下一個頂層定義的前一行（去掉尾端空行）。"""
    lines = (ROOT / path).read_text(encoding="utf-8").splitlines()
    a = next(i for i, l in enumerate(lines) if re.match(rf"def {func}\b", l))
    b = next((i for i in range(a + 1, len(lines)) if re.match(r"(def |class |[A-Za-z_][A-Za-z_0-9]* *=)", lines[i])), len(lines))
    while b > a and not lines[b - 1].strip():
        b -= 1
    return f"{path} {func}()（第 {a + 1}–{b} 行）"


def line_of(path, pattern):
    lines = (ROOT / path).read_text(encoding="utf-8").splitlines()
    return next(i + 1 for i, l in enumerate(lines) if re.search(pattern, l))


def main():
    timing = [
        ["股價、成交量（技術面）", "T 日收盤", "T 日收盤後", "只用 T 日（含）以前之收盤價與成交量",
         span("src/features.py", "add_technical")],
        ["估值（本益比、淨值比、殖利率）", "證交所盤後公布", "資料日 ≤ T", "as-of 合併，只取 T 日以前最新一筆",
         span("src/features.py", "asof_merge")],
        ["ESG（TEJ TESG）", "評等公告日", "公告日 ≤ T", "以「TESG評等公告日」為可用日，as-of 合併",
         span("src/features.py", "asof_merge") + "；src/loaders/tej.py"],
        ["模型訓練樣本", "樣本日之 10 日後", "樣本日 ≤ T−10", "訓練樣本之未來 10 日報酬於 T 日收盤前已實現",
         span("src/models.py", "walk_forward") + f"，cutoff 第 {line_of('src/models.py', r'cutoff = ')} 行"],
        ["調倉訊號日（T）", "—", "T 日收盤後", "每 2 週固定星期，遇休市順延；算出分數與目標權重",
         span("src/backtest.py", "rebalance_schedule")],
        ["成交（T+1）", "—", "T+1 日開盤", "以 TEJ 除權息調整後開盤價換股，並於開盤扣手續費、證交稅",
         span("src/backtest.py", "_simulate_next_open")],
        ["報酬起算", "—", "T+1 日開盤", "舊持股：T 收盤→T+1 開盤；新持股：T+1 開盤→收盤；其後收盤對收盤",
         span("src/backtest.py", "overnight_returns")],
        ["股價來源", "TEJ 盤後", "—", "TEJ 除權息調整後開盤價、收盤價取代混合來源",
         span("src/research/exchange.py", "apply_tej_prices")],
        ["比較基準（ETF、指數）", "當日收盤", "—", "收盤對收盤日報酬（還原收盤價）",
         span("src/backtest.py", "benchmark_returns")],
    ]
    head = ["項目", "資料可得時點", "使用時點", "規則", "程式位置"]
    pd.DataFrame(timing, columns=head).to_csv(OUT / "資料與交易時點稽核表.csv", index=False, encoding="utf-8-sig")

    cmp_ = pd.read_csv(OUT / "成交時點修正前後比較.csv")
    t41 = pd.read_csv(RUN / "tables" / "table_4_1_performance.csv").set_index("投組")
    P = lambda x: f"{x * 100:.1f}%"
    bench = []
    for _, r in cmp_.iterrows():
        bench.append([r["投組"], P(r["v1：混合價格、收盤成交"]), P(r["v2 持股、收盤成交（對照）"]),
                      P(r["v2：TEJ 價格、T+1 開盤成交"]), f"{r['v2 Sharpe']:.2f}", P(r["v2 最大回撤"])])
    for b in ["0050", "00850", "00878", "加權指數"]:
        if b in t41.index:
            x = t41.loc[b]
            bench.append([b, P(x["年化報酬"]), P(x["年化報酬"]), P(x["年化報酬"]), f"{x['Sharpe']:.2f}", P(x["最大回撤"])])

    R = Report()
    sec = R.doc.sections[0]
    sec.orientation = WD_ORIENT.LANDSCAPE
    sec.page_width, sec.page_height = Cm(29.7), Cm(21.0)
    sec.left_margin = sec.right_margin = Cm(1.6)
    sec.top_margin = sec.bottom_margin = Cm(0.8)
    sec.footer_distance = Cm(0.4)
    import report_lib
    report_lib.TEXT_W = Cm(26.5)
    R.h(3, "資料可得時點與成交時點稽核表")
    R.p(f"時點規則：調倉日 T 收盤後以當時已可取得之資料形成訊號，T+1 日開盤成交，報酬自 T+1 開盤起算。"
        f"前一版本以 T 日收盤價成交，已修正並以 TEJ 價格重跑（{CFG['run_id']}，資料截點 {CFG['data_cutoff']}）。"
        "表 2 之策略為 Top 20 等權、每 2 週調倉，已扣手續費（買賣各 0.1425%）與證交稅 0.3%、滑價 0；比較基準不受成交時點影響。"
        "資料來源：TEJ、臺灣證券交易所、證券櫃檯買賣中心、Yahoo Finance、FinMind；本研究整理。",
        indent=False, size=10.5, after=2)
    R.caption("表 1　資料與交易時點稽核")
    R.table(head, timing, [3.9, 2.5, 2.2, 8.6, 8.6], "lccll", size=8.5)
    R.caption("表 2　修正後基準表（評估期間 2022-11-01～2026-10-20 年化報酬）")
    R.table(["投組", "修正前：混合價格、收盤成交", "對照：v2 持股、收盤成交", "修正後：TEJ、T+1 開盤成交", "Sharpe（修正後）", "最大回撤（修正後）"],
            bench, [3.0, 4.6, 4.4, 4.6, 2.6, 2.8], "lrrrrr", size=8.5)
    docx = OUT / "資料與交易時點稽核表.docx"
    R.save(docx)
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice:
        subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", str(OUT), str(docx)], capture_output=True)
    print("完成：", docx)


if __name__ == "__main__":
    main()
