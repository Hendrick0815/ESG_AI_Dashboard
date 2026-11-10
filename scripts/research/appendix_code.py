"""論文附錄 E：系統實作與程式對照。
每個網站頁面放整頁截圖、畫面區塊 ↔ 程式位置對照表與關鍵程式片段；另列核心引擎、資料更新、論文研究程式與測試。
程式片段一律在產生論文時直接從程式檔讀取（以函式名稱或關鍵字定位），行號與現行程式一致，不手動貼上。
截圖由 scripts/research/capture_pages.py 產生（outputs/research/<run_id>/report/pages/*.png）。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHOW_CODE = False          # True：另外列出關鍵程式碼片段（篇幅約多 35 頁）


# ------------------------------------------------------------------ 程式定位
_cache: dict = {}


def lines_of(path):
    if path not in _cache:
        _cache[path] = (ROOT / path).read_text(encoding="utf-8").splitlines()
    return _cache[path]


def fn(path, name):
    """函式（或類別、Class.method）的起訖行（含 decorator），1 起算。"""
    tree = ast.parse("\n".join(lines_of(path)))
    parts = name.split(".")
    nodes = tree.body
    node = None
    for part in parts:
        node = next(n for n in nodes if isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)) and n.name == part)
        nodes = node.body
    start = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
    return start, node.end_lineno


def find(path, pat, after=1):
    """第一個包含 pat 的行號（從第 after 行起找）。"""
    L = lines_of(path)
    for i in range(after - 1, len(L)):
        if pat in L[i]:
            return i + 1
    raise ValueError(f"{path} 找不到「{pat}」")


def rng(path, start, end=None, n=None):
    """start：關鍵字或行號；end：關鍵字（含該行）；n：行數。"""
    s = start if isinstance(start, int) else find(path, start)
    if end is None:
        e = s + (n or 1) - 1
    elif isinstance(end, int):
        e = end
    else:
        e = find(path, end, s)
    return s, e


def loc(path, *ranges):
    ranges = sorted(ranges)
    return f"{path} 第 " + "、".join(f"{a}–{b}" if a != b else f"{a}" for a, b in ranges) + " 行"


def n_lines(path):
    return len(lines_of(path))


# ------------------------------------------------------------------ 截圖切頁
def split_shot(path, max_ratio=1.22, out_dir=None):
    """長截圖切成數張（在整列都是背景色的地方切），每張高 ≤ 寬 × max_ratio。回傳切好的檔案清單。"""
    from PIL import Image
    import numpy as np
    im = Image.open(path).convert("RGB")
    w, h = im.size
    limit = int(w * max_ratio)
    if h <= limit * 1.08:
        return [path]
    a = np.asarray(im).astype(int)
    blank = (np.abs(a - a[:, :1, :]).max(axis=(1, 2)) < 6)      # 整列顏色一致
    out_dir = Path(out_dir or Path(path).parent / "split")
    out_dir.mkdir(exist_ok=True)
    files, top, k = [], 0, 1
    while top < h:
        if h - top <= limit * 1.08:
            cut = h
        else:
            cut = top + limit
            lo = top + int(limit * 0.55)
            cand = np.flatnonzero(blank[lo:cut])
            if len(cand):
                cut = lo + int(cand[-1])
        f = out_dir / f"{Path(path).stem}_{k}.png"
        im.crop((0, top, w, cut)).save(f)
        files.append(f)
        top, k = cut, k + 1
        while top < h and blank[top] and top - cut < 40:
            top += 1
    return files


# ------------------------------------------------------------------ 附錄 E
class _Ctx:
    def __init__(self, R, shots_dir, prefix="E"):
        self.R, self.dir, self.pre = R, Path(shots_dir), prefix
        self.fig = 0
        self.show_code = False
        self.tab = 0
        self.prog = 0

    def lab(self, kind, n):
        """「表 E-3」；prefix 為空字串時為「表 3」（獨立文件用）。"""
        return f"{kind} {self.pre}-{n}" if self.pre else f"{kind} {n}"

    def figure(self, name, title, width=15.9, desc=None):
        f = self.dir / f"{name}.png"
        if not f.exists():
            self.R.note(f"（尚未產生截圖 {name}.png：請執行 python scripts/research/capture_pages.py）")
            return
        parts = split_shot(f)
        self.fig += 1
        for i, part in enumerate(parts, 1):
            self.R.image(part, width)
            suffix = f"（{i}/{len(parts)}）" if len(parts) > 1 else ""
            self.R.caption(f"{self.lab('圖', self.fig)}　{title}{suffix}")
        if desc:
            self.R.p(f"{self.lab('圖', self.fig)} {desc}")

    def table(self, title, header, rows, widths, align=None, size=9, desc=None):
        self.tab += 1
        if not (SHOW_CODE or self.show_code):      # 不列程式碼時，拿掉表中「（程式 E-n）」的引用
            rows = [[re.sub(r"（[、]*）", "", str(c)) for c in r] for r in rows]
        self.R.caption(f"{self.lab('表', self.tab)}　{title}")
        self.R.table(header, rows, widths, align, size=size)
        if desc:
            self.R.p(f"{self.lab('表', self.tab)} {desc}")

    def explain(self, kind, desc):
        """為最近一張表或圖加上「說明」段落（這張圖表代表什麼、能看出什麼）。"""
        n = self.tab if kind == "表" else self.fig
        self.R.p(f"{self.lab(kind, n)} {desc}")

    def code(self, path, ranges, what, skip_notes=None):
        """ranges：[(a, b), ...]；兩段之間自動加「略」。回傳程式編號（供對照表引用）。
        SHOW_CODE = False 時不列出程式碼（只在對照表寫檔案與行號），回傳空字串。"""
        if not (SHOW_CODE or self.show_code):
            return ""
        self.prog += 1
        blocks = []
        for i, (a, b) in enumerate(ranges):
            if i > 0:
                prev_b = ranges[i - 1][1]
                if a > prev_b + 1:
                    blocks.append((None, f"第 {prev_b + 1}–{a - 1} 行略" if not skip_notes else skip_notes[i - 1]))
            blocks.append((a, lines_of(path)[a - 1:b]))
        span = "、".join(f"{a}–{b}" for a, b in ranges)
        self.R.code(f"{self.lab('程式', self.prog)}　{path}：{what}（第 {span} 行）", blocks)
        return self.lab("程式", self.prog)


def appendix_e_detail(R, shots_dir, note_fn, figure_fn=None, standalone=False):
    """R：report_lib.Report；shots_dir：網站截圖資料夾；figure_fn()：產生系統架構圖並回傳路徑。"""
    """standalone=True：獨立的「程式碼與網站內容對照」文件——各節為一級標題、列出程式碼、圖表編號不加 E-。"""
    X = _Ctx(R, shots_dir, prefix="" if standalone else "E")
    X.show_code = standalone
    P, B, Nn = R.p, R.bullets, R.note
    D = (lambda lvl, t: R.h(max(1, lvl - 1), t)) if standalone else R.h
    W = "本文件" if standalone else "本附錄"
    L = X.lab

    if standalone:
        R.h(1, "說明")
    else:
        D(1, "附錄 E　系統實作與程式對照")
    files = PROGRAM_FILES
    n_files = sum(len(g[1]) for g in files)
    total = sum(n_lines(f) for _, fs in files for f, _, _ in fs if (ROOT / f).exists())
    P(f"{W}說明「ESG-AI 台股選股平台」的程式架構，並將網站每一個頁面對應到產生該畫面的程式段落，"
      f"使讀者能由畫面追溯計算過程，也能由程式確認網站與論文所呈現的內容。平台以 Python 撰寫，網站以 Streamlit 建置並部署於 "
      f"Streamlit Community Cloud，程式碼存放於 GitHub（Hendrick0815/ESG_AI_Dashboard）。{W}涵蓋的程式檔共 {n_files} 個、約 {total:,} 行。")
    P("各節以對照表列出每項功能所在的程式檔與行數範圍，並簡要說明其作用；行號於產生文件時由程式檔自動定位，與現行程式一致，"
      "完整程式碼請見 GitHub 上的對應檔案。截圖取自本機啟動的網站（與雲端網站為同一份程式），截圖時的資料日期以畫面上顯示者為準。")
    if standalone:
        P("本文件依 2026 年 11 月 1 日的程式產生。專題論文的正式結果使用 2026-10-20 的資料截點，研究設定與網站現行程式一致（每 2 週調倉）；"
          "資料截點之後的程式更新（持有期間預估改依大盤狀態、新增短期轉弱減碼選項、大盤狀態特徵開關）於相關章節另外標示，論文結果並未使用這些功能。")
        P("對照表之後列出該功能的關鍵程式碼：程式碼由程式檔直接讀取，左側數字為該檔案的實際行號；較長的函式只節錄與計算邏輯相關的部分，"
          "省略處以「第 a–b 行略」標示。對照表中的「程式 n」即指本文件中編號相同的程式碼清單。")
    P("閱讀時請注意兩項名稱與設定上的差異：")
    B(["**策略名稱：**網站程式與畫面中的「單純 ESG」，即論文所稱的「規則式 ESG 篩選投組」；「單純 AI」與「AI+ESG」名稱相同。",
       "**股票池：**網站「首頁」、「策略回測」、「模型解釋」等頁面以「目前」成交金額前 300 大的股票回測，供日常查詢使用，"
       "含有存活者偏誤，報酬會偏高；論文的正式結果以逐期股票池（含之後下市的股票）重新計算，呈現在「論文正式版本」頁與第四章。"
       "兩者共用同一套選股與回測程式（第十節），差別只在輸入的股票池與調倉日規則。"])

    # ---------------- 一、架構
    D(2, "一、系統架構與程式總覽")
    P("平台分為五個部分：①資料層負責從 Yahoo Finance、證交所、櫃買中心與 TEJ 取得資料並增量更新；②運算層把資料轉為特徵、"
      "以 AI 模型滾動訓練、依三種策略選股並回測；③介面層為網站各頁面與共用的圖表元件；④研究層產生論文的正式結果與論文文件；"
      f"⑤自動化流程每天更新資料，並在程式修改後自動測試與部署。{L('圖', 1)}為各部分之間的資料流向。")
    if figure_fn:
        X.fig += 1
        R.image(figure_fn(), 15.9)
        R.caption(f"{L('圖', X.fig)}　系統架構與資料流向")
        X.explain("圖", "呈現平台之系統架構與資料流向。外部資料來源經資料層下載與整理後，交由運算層進行特徵計算、模型訓練與回測，再由介面層呈現於網站；研究層沿用相同之運算程式產生論文之正式結果；自動化流程則負責每日資料更新，以及程式修改後之測試與部署。")
    rows = []
    for group, fs in files:
        for f, desc, where in fs:
            rows.append([f, f"{n_lines(f):,}" if (ROOT / f).exists() else "—", group, desc, where])
    X.table("程式檔案清單", ["程式檔", "行數", "分類", "主要功能", "對應的網站內容／論文位置"], rows,
            [3.8, 0.8, 1.8, 4.1, 3.3], "lrlll", size=8.5)
    Nn("註：行數為程式檔目前的總行數（含註解與空白行）。")
    X.explain("表", "列示本文件涵蓋之全部程式檔及其行數與功能，並依網站頁面、介面元件、核心運算、資料層、論文研究、資料與自動化腳本及測試分類；最右欄為各程式對應之網站內容或論文章節。")

    X.table("網站頁面與程式對照", ["網站頁面", "頁面程式", "主要呼叫的模組與函式", "畫面內容"], PAGE_MAP,
            [1.8, 2.6, 4.6, 4.8], "llll", size=8.5)
    X.explain("表", "彙整網站七個頁面之對應程式檔、主要呼叫之核心函式及畫面內容，各頁之詳細對照另見第三至九節。")

    # ---------------- 二、共用元件
    D(2, "二、各頁共用的設定與運算流程")
    P("每個頁面開頭都依相同順序執行：先呼叫 ensure_fresh() 確保雲端更新程式後讀到新版模組，再以 setup_page() 設定版面，"
      "接著由側邊欄 sidebar_data() 選擇資料來源、sidebar_strategy() 設定策略參數，最後以 get_result() 取得回測結果。"
      "get_result() 依序查詢記憶體、回測存檔（outputs/cache）與實際計算，同一組資料與參數只會計算一次；"
      "存檔的鍵值包含資料檔內容的雜湊值與參數，資料每日更新後會自動重新計算。")
    X.figure("home_sidebar", "側邊欄設定（資料來源與選股策略參數）", 15.9)
    X.explain("圖", "呈現各頁共用之側邊欄設定區，上方為資料來源選擇，下方為 AI 模型、持股檔數、權重方式、ESG 比重，以及風險控制與短期轉弱減碼等選用功能之設定。各頁面共用同一組設定，任一設定變更均會重新執行回測。")
    s1 = fn("src/ui/common.py", "sidebar_strategy")
    s2 = fn("src/ui/common.py", "get_result")
    p1 = X.code("src/ui/common.py", [s1], "側邊欄策略參數 sidebar_strategy()")
    p2 = X.code("src/ui/common.py", [s2], "取得回測結果 get_result()")
    k1 = fn("src/cache.py", "result_key")
    k2 = fn("src/cache.py", "data_stamp")
    p3 = X.code("src/cache.py", [k2, k1], "回測存檔的鍵值 data_stamp()、result_key()")
    f1 = fn("src/_fresh.py", "ensure_fresh")
    p4 = X.code("src/_fresh.py", [f1], "雲端更新後重新載入模組 ensure_fresh()")
    X.table("側邊欄與共用流程對照", ["畫面／功能", "程式位置", "說明"], [
        ["資料來源（真實資料／合成示範資料）", loc("src/ui/common.py", fn("src/ui/common.py", "sidebar_data")), "選擇資料來源並載入 Dataset；真實資料模式會先檢查是否需要補抓股價"],
        ["AI 模型、Top N、權重方式、ESG 比重、風險控制、進階設定", f"{loc('src/ui/common.py', s1)}（{p1}）", "回傳 Params；所有頁面共用同一組設定"],
        ["短期轉弱減碼（2026 年 11 月新增，預設關閉）", loc("src/ui/common.py", rng("src/ui/common.py", 'pull_on = _keep("pull_on"', "反應比「跌破年線」快")) + "；" + loc("src/backtest.py", fn("src/backtest.py", "pullback_exposure")), "加權指數距 20 日高點跌逾 5% 時持股減半；可與風險控制同時使用，取較低的持股比例"],
        ["回測結果與進度條", f"{loc('src/ui/common.py', s2)}（{p2}）", "記憶體 → 存檔 → 計算；第一次計算時顯示訓練進度"],
        ["回測存檔", f"{loc('src/cache.py', k2, k1)}（{p3}）", "資料內容雜湊＋參數＋程式版本 → 存檔檔名"],
        ["雲端更新後的模組重新載入", f"{loc('src/_fresh.py', f1)}（{p4}）", "src 內任一程式檔更新即清除已載入模組"],
    ], [4.2, 4.6, 5.0], "lll")
    X.explain("表", "對照側邊欄各項設定與各頁共用運算流程所在之程式位置；表中行數可直接對應程式檔，「程式 n」為本節所列之程式碼清單。")

    # ---------------- 三、首頁
    D(2, "三、首頁（app.py）")
    P("首頁顯示資料狀態、最新一次選股名單、三種策略與比較基準的績效指標卡，以及樣本外期間的累積淨值圖。"
      "最新選股以資料最後一天的收盤價計算，並標示最近一次與下一次的調倉日。")
    X.figure("home", "首頁")
    X.explain("圖", "呈現網站首頁，由上而下依序為資料狀態、最新一次選股名單與調倉日、三個策略與加權指數之年化報酬指標，以及樣本外期間之累積淨值圖，可據以掌握各策略之最新持股與累積績效。")
    a = rng("app.py", "params = sidebar_strategy(ds)", "st.caption(HOLDINGS_NOTE)")
    b = rng("app.py", "st.plotly_chart(charts.nav_chart(res.returns", n=1)
    c = rng("app.py", 'with st.expander("📦 資料狀態與更新"', "st.caption(\"價格來源")
    pa = X.code("app.py", [a, b], "績效指標卡、最新選股與累積淨值")
    nv = fn("src/ui/charts.py", "nav_chart")
    pb = X.code("src/ui/charts.py", [nv], "累積淨值圖 nav_chart()")
    hb = fn("src/ui/common.py", "holdings_block")
    X.table("首頁畫面與程式對照", ["畫面區塊", "程式位置", "說明"], [
        ["資料狀態與更新（股票數、資料日期、ESG 期數、比較基準）", loc("app.py", c), "讀取 Dataset 並以 metric_cards() 顯示；可手動更新資料"],
        ["最新選股（調倉日、下次調倉日）", f"{loc('app.py', a)}（{pa}）", "bt.next_rebalance() 推算下一次調倉日"],
        ["各策略年化報酬指標卡", f"{loc('app.py', a)}（{pa}）", "取自 Result.perf（metrics.performance_table）"],
        ["三種策略的持股名單", loc("src/ui/common.py", hb), "holdings_block() 顯示代號、名稱、權重與分數"],
        ["累積淨值圖", f"{loc('app.py', b)}；{loc('src/ui/charts.py', nv)}（{pb}）", "實線為策略、虛線為比較基準；扣除交易成本"],
    ], [4.4, 5.0, 4.4], "lll")
    X.explain("表", "對照首頁各畫面區塊與其對應之程式檔、行數及功能。")

    # ---------------- 四、大盤趨勢
    D(2, "四、大盤趨勢頁（pages/0_大盤趨勢預測.py）")
    P("本頁以 7 項常用指標描述加權指數目前的多空狀態，並以底色標示歷史上每一天依同一套規則的判斷結果。"
      "判斷只使用當天收盤為止的資料，美股與 VIX 使用前一晚已收盤的數值；本頁為描述性資訊，未用於選股與回測。"
      "頁面下方另提供未來一個月的波動與漲跌機率模型作為參考，其樣本外檢驗顯示漲跌方向的預測力接近隨機，因此判斷以指標表為主。")
    X.figure("trend", "大盤趨勢頁")
    X.explain("圖", "呈現大盤趨勢頁。上方表格以 7 項指標判斷加權指數當前之多空狀態，各指標分別判定為多、中性或空；下方圖以底色標示歷史上各交易日依相同規則之判斷結果，可據以觀察市場狀態之轉換。本頁僅描述當前狀態，未用於選股。")
    ts = fn("src/market_trend.py", "trend_series")
    ct = fn("src/market_trend.py", "current_trend")
    pg = "pages/0_大盤趨勢預測.py"
    t1 = rng(pg, "st.caption(f\"資料到", "不是預測未來")
    t2 = rng(pg, "seg = (ts[\"verdict\"]", 'layer="below")')
    q1 = X.code("src/market_trend.py", [ts], "7 項指標的每日多空判斷 trend_series()")
    q2 = X.code(pg, [t1, t2], "趨勢判斷表與歷史底色")
    X.table("大盤趨勢頁畫面與程式對照", ["畫面區塊", "程式位置", "說明"], [
        ["目前趨勢、指標統計", f"{loc(pg, t1)}（{q2}）", "current_trend() 的結論、持續天數與多空指標數"],
        ["7 項指標判斷表", f"{loc('src/market_trend.py', ct)}", "年線位置、年線方向、均線排列、距一年高點、近 60 日漲跌、美股趨勢、VIX"],
        ["判斷規則（加總分數分級）", f"{loc('src/market_trend.py', ts)}（{q1}）", "各指標 +1／0／−1 加總：≥ 4 牛市、2～3 偏多、−1～1 盤整、≤ −2 偏空；距一年高點跌逾 20% 為熊市"],
        ["加權指數與歷來趨勢判斷圖", f"{loc(pg, t2)}（{q2}）", "對數刻度；底色為當天的判斷"],
        ["未來 1 個月展望（參考）", loc("src/market_trend.py", fn("src/market_trend.py", "run")), "羅吉斯迴歸滾動訓練，2008 年起樣本外 AUC 與 Brier 分數"],
    ], [3.8, 4.6, 5.4], "lll")
    X.explain("表", "對照大盤趨勢頁之判斷表、歷史趨勢圖與展望模型所在之程式位置，並說明 7 項指標之判斷規則。")

    # ---------------- 五、策略回測
    D(2, "五、策略回測頁（pages/1_策略回測.py）")
    pg = "pages/1_策略回測.py"
    P("本頁有四個分頁：「績效比較」可選擇期間比較累積淨值、績效指標、風險報酬散佈與回撤；「歷次持股」列出每個調倉日三種策略的持股，"
      "並以調倉日當天的模型預估對照持有期間的實際走勢（2026 年 11 月起，預估的大盤部分改依調倉日的大盤狀態估計，並顯示期末虧損機率）；「換股與成本」列出每次調倉的週轉率與交易成本；「方法說明」以文字說明預測目標、"
      "特徵、訓練方式與回測規則。")
    X.figure("backtest_perf", "策略回測頁：績效比較")
    X.explain("圖", "呈現策略回測頁之績效比較分頁，包括各策略與比較基準之累積淨值、績效指標、風險報酬散佈與回撤，並可選擇不同評估期間，據以比較各策略之報酬、波動與最大跌幅。")
    t1 = rng(pg, "with tab1:", "c2.plotly_chart(charts.drawdown_chart")
    r1 = X.code(pg, [t1], "績效比較分頁（期間選擇、淨值圖、績效表）")
    pf, cp, pt = fn("src/metrics.py", "performance"), fn("src/metrics.py", "capm"), fn("src/metrics.py", "performance_table")
    r2 = X.code("src/metrics.py", [pf, cp], "績效指標 performance() 與 CAPM capm()")
    X.figure("backtest_holdings", "策略回測頁：歷次持股與持有期間預估")
    X.explain("圖", "呈現策略回測頁之歷次持股分頁。上方列示調倉日與最新交易日之大盤狀態及歷史上漲機率；中段為三個策略於該調倉日之持股；下方走勢圖比較調倉日之預估（虛線與色帶）與實際走勢（實線），指標卡列示預估期末報酬、期末虧損機率與實際報酬，可據以檢驗模型預估與實際結果之差異。")
    t2 = rng(pg, "# 先算三個策略的預估", "不代表模型能預測方向")
    r3 = X.code(pg, [t2], "歷次持股：三種策略的持有期間預估與大盤狀態")
    hf = fn("src/forecast.py", "holding_forecast")
    r4 = X.code("src/forecast.py", [hf], "持有期間預估路徑、區間與期末虧損機率 holding_forecast()")
    mv, sb = fn("src/forecast.py", "market_view"), fn("src/forecast.py", "strategy_beta")
    r4b = X.code("src/forecast.py", [mv, sb], "依大盤狀態的預期大盤報酬 market_view() 與策略 Beta strategy_beta()")
    X.figure("backtest_trades", "策略回測頁：換股與成本")
    X.explain("圖", "呈現策略回測頁之換股與成本分頁。上表彙整各策略之換股次數、平均週轉率與累計交易成本，下表列示各次調倉之週轉率與成本；由圖可知，AI 策略之換股頻率與交易成本明顯高於規則式 ESG 篩選。")
    t4 = rng(pg, "with tab4:", "st.dataframe(res.trades.sort_values")
    t4 = (t4[0], t4[1] + 2)
    r5 = X.code(pg, [t4], "換股與成本分頁")
    tc = fn("src/backtest.py", "trading_cost")
    r6 = X.code("src/backtest.py", [tc], "交易成本 trading_cost()")
    X.figure("backtest_method", "策略回測頁：方法說明")
    X.explain("圖", "呈現策略回測頁之方法說明分頁，以文字說明預測目標、特徵、訓練方式、三種策略、回測規則與研究限制，其參數依側邊欄當前設定自動帶入。")
    t5 = rng(pg, "with tab5:", '""")')
    X.table("策略回測頁畫面與程式對照", ["畫面區塊", "程式位置", "說明"], [
        ["期間選擇、累積淨值（可切換對數刻度）", f"{loc(pg, t1)}（{r1}）", "全部樣本外期間或近 1／3／5 年、自訂區間"],
        ["績效表（年化報酬、波動、Sharpe、最大回撤、Beta、詹森 Alpha）", f"{loc('src/metrics.py', pt, pf, cp)}（{r2}）", "幾何年化；CAPM 以加權指數為市場"],
        ["風險報酬散佈、回撤圖", loc("src/ui/charts.py", fn("src/ui/charts.py", "risk_return_scatter"), fn("src/ui/charts.py", "drawdown_chart")), "Plotly 圖，顏色固定對應策略"],
        ["歷次持股（調倉日選單、三策略持股）", loc(pg, rng(pg, "with tab2:", "info = stock_info(res, ds, d)")), "調倉日每 2 週一次，遇假日順延"],
        ["持有期間走勢圖與預估指標卡", f"{loc(pg, (t2[0], find(pg, 'st.plotly_chart(charts.forecast_compare')))}（{r3}）；{loc('src/forecast.py', hf)}（{r4}）", "預估 = 策略 Beta × 依大盤狀態的預期大盤報酬＋持股 AI 預測超額；區間依過去 60 日波動；另顯示期末虧損機率"],
        ["大盤狀態與歷史上漲機率（預估上方的說明）", f"{loc('src/forecast.py', mv, sb)}（{r4b}）", "7 項趨勢指標判斷狀態（牛市回檔另外標示）；取過去同狀態之後 10 個交易日的平均報酬並向全期平均收縮；只用調倉日以前已實現的資料"],
        ["期末報酬預估比較", loc("src/ui/charts.py", fn("src/ui/charts.py", "forecast_compare")), "圓圈＝預估、粗線＝68% 區間、菱形＝實際"],
        ["換股次數、週轉率、累計成本", f"{loc(pg, t4)}（{r5}）；{loc('src/backtest.py', tc)}（{r6}）", "買進手續費 0.1425%；賣出手續費＋證交稅 0.3%"],
        ["方法說明（文字）", loc(pg, t5), "依目前設定動態帶入參數"],
    ], [4.2, 5.4, 4.2], "lll")
    X.explain("表", "對照策略回測頁四個分頁之畫面區塊與程式位置；其中持有期間預估與大盤狀態二列為 2026 年 11 月更新後之做法。")

    # ---------------- 六、個股分析
    D(2, "六、個股分析頁（pages/2_個股分析.py）")
    pg = "pages/2_個股分析.py"
    P("本頁可輸入任一股票代號；不在資料中的股票會即時向 Yahoo Finance 下載。頁面上方為累積報酬、年化波動、Sharpe、最大回撤與 ESG 評等，"
      "下方分為走勢、風險與技術指標、ESG、同業比較四個分頁。ESG 評等取「期間結束時已公告」的最新一期，不使用之後才公告的資料。")
    X.figure("stock_price", "個股分析頁：走勢（以 2330 台積電為例）")
    X.explain("圖", "呈現個股分析頁之走勢分頁。上方指標列示個股於選定期間之累積報酬、年化波動、夏普值、最大回撤與 ESG 評等，下方為股價與均線走勢，以及依固定門檻自動產生之走勢摘要。")
    X.figure("stock_risk", "個股分析頁：風險與技術指標")
    X.explain("圖", "呈現個股分析頁之風險與技術指標分頁。左圖為 20 日年化波動率之變化，右圖為日報酬分布，下表說明各風險指標之意義，可據以判斷個股之波動程度與極端報酬之頻率。")
    X.figure("stock_esg", "個股分析頁：ESG")
    X.explain("圖", "呈現個股分析頁之 ESG 分頁。左側雷達圖呈現 E、S、G 三構面分數，右表列示 TESG 總分、等級、爭議相關分數與公告日，下方為歷次評等之變化；所呈現者僅限期間結束時已公告之評等。")
    X.figure("stock_peer", "個股分析頁：同業比較")
    X.explain("圖", "呈現個股分析頁之同業比較分頁。上表比較同產業股票之 ESG 總分、報酬、波動、夏普值與最大回撤，下方散佈圖呈現 ESG 總分與累積報酬之關係，可據以觀察該股於同業中之相對位置。")
    a = rng(pg, 'd = px_df.copy()', "esg_row = (e_known")
    b = rng(pg, "for t in dict.fromkeys([ticker, *peers]):", '"Sharpe": pm["sharpe"], "最大回撤": pm["max_drawdown"]})')
    s1 = X.code(pg, [a], "技術指標與已公告的 ESG 評等")
    s2 = X.code(pg, [b], "同業比較")
    X.table("個股分析頁畫面與程式對照", ["畫面區塊", "程式位置", "說明"], [
        ["代號輸入與即時下載", loc(pg, fn(pg, "fetch_one"), rng(pg, "tickers = sorted(ds.prices", "candle = st.toggle")), "資料中沒有的股票以 yahoo.fetch_prices() 下載，快取 1 小時"],
        ["指標卡（累積報酬、波動、Sharpe、最大回撤、ESG）", f"{loc(pg, a)}（{s1}）", "metrics.price_metrics()；ESG 取期末已公告的一期"],
        ["走勢（價格、均線、規則式摘要）", loc(pg, rng(pg, "with tab1:", "目前股價{pos}。\")")), "摘要依固定門檻自動產生"],
        ["風險與技術指標", loc(pg, rng(pg, "with tab2:", "}), hide_index=True")), "20 日年化波動、日報酬分布與指標說明"],
        ["ESG（雷達圖、評等明細、歷史）", loc(pg, rng(pg, "with tab3:", "目前只有一期 ESG 評等")), "TEJ TESG 總分與 E／S／G、爭議分數、公告日"],
        ["同業比較", f"{loc(pg, b)}（{s2}）", "同產業至少 3 檔時比較同產業，否則比較全部股票"],
    ], [4.2, 5.2, 4.4], "lll")
    X.explain("表", "對照個股分析頁之代號輸入、指標與四個分頁所在之程式位置。")

    # ---------------- 七、模型解釋
    D(2, "七、模型解釋頁（pages/3_模型解釋.py）")
    pg = "pages/3_模型解釋.py"
    P("本頁說明 AI 模型的表現與使用的特徵：上方為平均 Rank IC、IC 為正的比例與 Top N 每期平均超額報酬；"
      "左圖為最後一次訓練的特徵重要性，右圖為每次調倉的 Rank IC；下方可展開 SHAP 分析、特徵清單與每次訓練的紀錄。")
    X.figure("model", "模型解釋頁")
    X.explain("圖", "呈現模型解釋頁。上方指標列示平均 Rank IC、IC 為正之比例與前 N 檔平均超額報酬；左圖為最近一次訓練之特徵重要性，右圖為各調倉日之 Rank IC，可據以觀察模型所依賴之特徵及其排序能力之穩定性。")
    a = rng(pg, "ic = rank_ic(res.evaluation)", "metric_cards(cards, min_width=190)")
    m1 = X.code(pg, [a], "Rank IC 與 Top N 超額報酬")
    ri = fn("src/pipeline.py", "rank_ic")
    m2 = X.code("src/pipeline.py", [ri], "每次調倉的 Rank IC rank_ic()")
    X.table("模型解釋頁畫面與程式對照", ["畫面區塊", "程式位置", "說明"], [
        ["平均 Rank IC、IC > 0 比例、Top N 平均超額", f"{loc(pg, a)}（{m1}）；{loc('src/pipeline.py', ri)}（{m2}）", "Spearman 等級相關；超額 = 前 N 檔平均 − 全部平均（未扣成本）"],
        ["特徵重要性圖", loc(pg, rng(pg, "with a:", "特徵重要性（最後一次訓練）")), "Random Forest 內建重要性"],
        ["Rank IC 時間序列", loc("src/ui/charts.py", fn("src/ui/charts.py", "rank_ic_chart")), "每次調倉一點"],
        ["SHAP 分析", loc(pg, rng(pg, 'with st.expander("SHAP', 'st.caption("尚未安裝 shap')), "需另行安裝 shap；按鈕觸發計算"],
        ["使用的特徵", loc(pg, rng(pg, 'with st.expander("使用的特徵")', "ESG 資料涵蓋率")), "技術面、見頂訊號、估值；ESG 不進入模型，於選股時融合"],
        ["訓練紀錄", loc(pg, rng(pg, 'with st.expander("訓練紀錄")', 'st.caption("最新的模型排在最上面。")')), "每次訓練的資料期間、樣本數與負責期間的表現"],
    ], [4.2, 5.4, 4.2], "lll")
    X.explain("表", "對照模型解釋頁之 Rank IC、特徵重要性、SHAP 分析與訓練紀錄所在之程式位置。")

    # ---------------- 八、產業與籌碼
    D(2, "八、產業與籌碼頁（pages/4_產業與籌碼.py）")
    pg = "pages/4_產業與籌碼.py"
    P("本頁提供產業趨勢與三大法人買賣超資訊，僅供參考，不影響選股與回測。產業指數為股票池內同產業股票的等權平均；"
      "法人資料取自證交所 T86 報表（僅涵蓋上市股票）。")
    X.figure("industry", "產業與籌碼頁：產業趨勢")
    X.explain("圖", "呈現產業與籌碼頁之產業趨勢分頁。上方指標列示趨勢向上之產業數及近 1 個月表現最強與最弱之產業，長條圖與下表列示各產業之近期報酬與季線乖離；本頁僅供參考，未用於選股。")
    X.figure("flows", "產業與籌碼頁：主力動向（三大法人）")
    X.explain("圖", "呈現產業與籌碼頁之主力動向分頁。上圖依產業彙整三大法人之買賣超金額，下方表格列示買超與賣超金額前 15 名及投信買超前 10 名，可據以觀察近期法人資金之流向。")
    it, fl, fb = fn("src/analysis.py", "industry_trend"), fn("src/analysis.py", "flow_leaders"), fn("src/analysis.py", "flow_by_industry")
    n1 = X.code("src/analysis.py", [it], "產業趨勢 industry_trend()")
    n2 = X.code("src/analysis.py", [fl], "三大法人買賣超彙整 flow_leaders()")
    X.table("產業與籌碼頁畫面與程式對照", ["畫面區塊", "程式位置", "說明"], [
        ["趨勢向上的產業數、近 1 月最強／最弱", f"{loc(pg, rng(pg, 'with tab1:', 'fmt_pct(it.iloc[-1]'))}；{loc('src/analysis.py', it)}（{n1}）", "趨勢向上 = 產業指數在季線之上且近 20 日上漲"],
        ["各產業近 1 個月報酬圖與明細表", loc(pg, rng(pg, 'st.plotly_chart(charts.industry_bar(it', 'column_config={"趨勢向上"')), "等權產業指數"],
        ["法人買賣超金額（依產業）", f"{loc('src/analysis.py', fb)}", "估計金額 = 買超股數 × 最新收盤價"],
        ["買超、賣超前 15 名與投信買超前 10 名", loc(pg, rng(pg, "with tab2:", "st.caption(\"資料來源：證交所 T86")) + f"；{loc('src/analysis.py', fl)}（{n2}）", "可選近 1／5／20 個交易日"],
    ], [4.2, 5.4, 4.2], "lll")
    X.explain("表", "對照產業趨勢與三大法人買賣超各畫面區塊所在之程式位置及計算方式。")

    # ---------------- 九、論文正式版本
    D(2, "九、論文正式版本頁（pages/5_論文正式版本.py）")
    pg = "pages/5_論文正式版本.py"
    P("本頁呈現論文第三章與第四章的正式表格與圖。表格內容由 build_report.py 產生論文時一併寫入 web_tables.json，"
      "頁面讀取後以與論文相同的格式（深藍表頭、隔列淺底）顯示；論文中的表 3-3、3-4、3-8 與表 4-1 至 4-14（表 4-10 除外）"
      "即為本頁的截圖（由 capture_web.py 擷取）。因此網站與論文的數字出自同一份輸出檔，不會不一致。")
    X.figure("thesis", "論文正式版本頁（樣本與期間分頁）")
    X.explain("圖", "呈現論文正式版本頁，內容為論文第三、四章之正式表格與圖，上方指標列示各投組與 ETF 之年化報酬、夏普值與最大回撤；論文中之表格即為本頁之截圖，故網站與論文之數據一致。")
    th, sh = fn(pg, "table_html"), fn(pg, "show_table")
    tb = rng(pg, "NAMES = [", "with st.expander(\"下載與重現方式\")")
    tb = (tb[0], tb[1] - 2)
    w1 = X.code(pg, [th, sh, tb], "表格產生與分頁配置")
    X.table("論文正式版本頁畫面與程式對照", ["畫面區塊", "程式位置", "說明"], [
        ["版本與期間說明、績效指標卡", loc(pg, rng(pg, "st.caption(f\"研究版本", "metric_cards(cards, min_width=180)")), "讀取 research_config.json 與 table_4_1_performance.csv"],
        ["五個分頁的表格", f"{loc(pg, th, sh, tb)}（{w1}）", "樣本與期間、投組績效、風險比較、統計檢定、穩健性測試"],
        ["圖 4-1 累積淨值、圖 4-2 ESG 分數", loc(pg, fn(pg, "nav_figure"), fn(pg, "esg_figure")), "讀取 strategy_returns.csv 與 esg_quality_by_rebalance.csv"],
        ["下載與重現方式", loc(pg, rng(pg, 'with st.expander("下載與重現方式")', 'key=f"dl-{name}")')), "提供逐期股票池、持股、報酬與 manifest 下載"],
        ["論文表格截圖", loc("scripts/research/capture_web.py", fn("scripts/research/capture_web.py", "main")), "以 ?all=1 依序展開全部表格後逐一截圖"],
    ], [4.2, 5.4, 4.2], "lll")
    X.explain("表", "對照論文正式版本頁各畫面區塊所在之程式位置，以及論文表格截圖之產生方式。")

    # ---------------- 十、核心引擎
    D(2, "十、選股與回測核心程式（網站與論文共用）")
    P("pipeline.run() 串接整個流程：建立特徵面板 → 依逐期股票池篩選（論文版本） → 產生調倉日 → 滾動訓練模型並預測 → "
      "計算三種策略的分數與權重 → 模擬每日淨值並扣除交易成本 → 彙整績效。網站各頁與論文研究程式都呼叫這個函式，"
      f"差別只在輸入的資料（Dataset）與設定。{L('表', X.tab + 1)}依執行順序列出各步驟所在的程式位置。")
    pr = fn("src/pipeline.py", "run")
    a = rng("src/pipeline.py", "panel, info = build_panel(prices", "panel = panel.merge(key")
    b = rng("src/pipeline.py", "trading_days = pd.DatetimeIndex(sorted(full_panel", "progress=progress)")
    c = rng("src/pipeline.py", "targets: Dict[str, Dict", "\"weight\": w.values")
    c = (c[0], c[1])
    d = rng("src/pipeline.py", "ret_wide = full_panel.pivot_table", "risk_rows.append(sim[")
    e1 = X.code("src/pipeline.py", [a, b, c, d], "整體流程 run()（節錄）")
    at = fn("src/features.py", "add_technical")
    e2 = X.code("src/features.py", [at], "技術面與見頂訊號特徵、預測目標 add_technical()")
    am = fn("src/features.py", "asof_merge")
    e3 = X.code("src/features.py", [am], "依公告日對齊 ESG 與財務資料 asof_merge()")
    rs_ = fn("src/backtest.py", "rebalance_schedule")
    e4 = X.code("src/backtest.py", [rs_], "調倉日 rebalance_schedule()")
    wf = fn("src/models.py", "walk_forward")
    e5 = X.code("src/models.py", [wf], "滾動式訓練與預測 walk_forward()")
    er, ss = fn("src/backtest.py", "apply_esg_rules"), fn("src/backtest.py", "score_strategies")
    e6 = X.code("src/backtest.py", [er, ss], "三種策略的選股分數 apply_esg_rules()、score_strategies()")
    pk, mw = fn("src/backtest.py", "pick_top"), fn("src/backtest.py", "make_weights")
    sm_ = fn("src/backtest.py", "simulate")
    e7 = X.code("src/backtest.py", [sm_], "每日淨值模擬 simulate()")
    pe, ce = fn("src/backtest.py", "pullback_exposure"), fn("src/backtest.py", "combine_exposure")
    e8 = X.code("src/backtest.py", [pe, ce], "短期轉弱減碼 pullback_exposure()、combine_exposure()（2026 年 11 月新增）")
    X.table("核心程式與論文研究方法對照", ["步驟", "程式位置", "論文對應"], [
        ["整體流程", f"{loc('src/pipeline.py', pr)}（{e1}）", "圖 1-1 研究流程"],
        ["技術面特徵、見頂訊號、預測目標（未來 10 日報酬）", f"{loc('src/features.py', at)}（{e2}）", "第三章第二節、表 3-5"],
        ["ESG 與估值依公告日對齊", f"{loc('src/features.py', am)}（{e3}）", "表 3-2 可得日規則"],
        ["調倉日（論文與網站皆為每 2 週固定同一星期幾）", f"{loc('src/backtest.py', rs_)}（{e4}）", "第三章第三節、表 3-9"],
        ["Random Forest 滾動訓練（每 3 次調倉重訓、訓練樣本截至調倉日前 10 日）", f"{loc('src/models.py', wf)}（{e5}）", "第三章第四節（一）（二）"],
        ["單純 AI、AI+ESG、規則式 ESG 篩選的分數", f"{loc('src/backtest.py', er, ss)}（{e6}）", "第三章第三、四節、表 3-6"],
        ["前 N 檔與權重", loc("src/backtest.py", pk, mw), "Top 20 等權"],
        ["每日淨值、週轉率與交易成本", f"{loc('src/backtest.py', sm_, tc)}（{e7}、{r6}）", "表 3-9 交易假設、表 4-12"],
        ["績效指標與 CAPM", f"{loc('src/metrics.py', pf, cp)}（{r2}）", "第三章第五節、表 4-1、表 4-4"],
        ["短期轉弱減碼（選用，網站 2026 年 11 月新增）", f"{loc('src/backtest.py', pe, ce)}（{e8}）", "論文未使用（表 3-1：不使用風險控制）"],
        ["大盤狀態特徵（設定開關，預設關閉）", loc("src/features.py", fn("src/features.py", "add_market_features")), "論文未使用；已測試、效果不一致"],
    ], [5.0, 5.2, 3.6], "lll", desc="依執行順序列示選股與回測各步驟所在之程式位置及其對應之論文章節或表格，可據以由論文之方法說明追溯實際執行之程式；最後二列為資料截點後新增之選用功能，論文結果未使用。")

    # ---------------- 十一、資料更新與部署
    D(2, "十一、資料蒐集、自動更新與部署")
    P("網站資料由 GitHub Actions 於每個交易日台灣時間 14:50 自動更新：執行 update_data.py --auto 補抓到最近收盤日的股價、比較基準、"
      "三大法人、大盤長期資料與月底估值，再以 run_backtest.py 預先計算預設設定的回測，最後將資料與回測存檔提交回 GitHub，"
      "Streamlit Cloud 偵測到更新後自動重新部署。程式修改則由本機的 auto_push.py 監看：檔案變動後先執行測試，通過才提交並推送。")
    au = fn("src/store.py", "auto_update")
    au_r = (au[0], find("src/store.py", 'out["benchmarks"] = {"error": str(e)}', au[0]))
    g1 = X.code("src/store.py", [au_r], "每日自動更新 auto_update()（節錄）")
    yf_ = fn("src/crawlers/yahoo.py", "fetch_prices")
    g2 = X.code("src/crawlers/yahoo.py", [(yf_[0], find("src/crawlers/yahoo.py", "time.sleep(1 + random.random())", yf_[0]))], "Yahoo Finance 批次下載 fetch_prices()（節錄）")
    yml = ".github/workflows/daily_update.yml"
    g3 = X.code(yml, [(1, n_lines(yml))], "每日自動更新排程（GitHub Actions）") if (ROOT / yml).exists() else "—"
    pu = fn("scripts/auto_push.py", "publish")
    g4 = X.code("scripts/auto_push.py", [(pu[0], find("scripts/auto_push.py", "return False", pu[0])), (find("scripts/auto_push.py", "pull = git(\"pull\"", pu[0]), pu[1])], "程式修改後自動測試與推送 publish()")
    X.table("資料來源與更新程式對照", ["資料", "來源", "程式位置", "更新方式"], [
        ["個股股價（網站）", "Yahoo Finance", f"{loc('src/crawlers/yahoo.py', yf_)}（{g2}）", "每日增量補抓；失敗的股票批次重試"],
        ["比較基準（加權指數、0050、00850、00878）", "Yahoo Finance", loc("src/store.py", fn("src/store.py", "update_benchmarks")), "每日"],
        ["上市櫃清單與產業", "證交所 ISIN", loc("src/crawlers/twse.py", fn("src/crawlers/twse.py", "fetch_listing")), "手動更新時"],
        ["本益比、淨值比、殖利率", "證交所 BWIBBU", loc("src/crawlers/twse.py", fn("src/crawlers/twse.py", "fetch_valuation_series")), "每月月底一筆"],
        ["三大法人買賣超", "證交所 T86", loc("src/crawlers/twse.py", fn("src/crawlers/twse.py", "fetch_t86_series")), "每日最近 10 個交易日"],
        ["大盤長期資料（加權指數、S&P 500、VIX 等）", "Yahoo Finance", loc("src/store.py", fn("src/store.py", "update_macro")), "每日"],
        ["TEJ TESG 評等", "TEJ 下載檔", loc("src/loaders/tej.py", fn("src/loaders/tej.py", "load_tej")), "新一期公告後放入 data/raw/tej/"],
        ["每日排程", "GitHub Actions", f"{yml}（{g3}）", "週一至週五 14:50"],
        ["自動更新主程式", "—", f"{loc('src/store.py', au)}（{g1}）", "任一步驟失敗不影響其他步驟"],
        ["程式部署", "GitHub → Streamlit Cloud", f"{loc('scripts/auto_push.py', pu)}（{g4}）", "測試通過才推送"],
    ], [3.6, 2.4, 4.8, 3.0], "llll")
    X.explain("表", "列示網站使用之各項資料、資料來源、下載程式位置與更新頻率，據以區分每日自動更新與需手動更新之資料。")

    # ---------------- 十二、論文研究程式
    D(2, "十二、論文研究程式與輸出檔")
    P("論文的正式結果由 run_research.py 依 research_config.json 的固定設定產生：先以逐日行情建立含下市股票的價格面板與逐期股票池，"
      "再呼叫第十節的 pipeline.run() 回測，最後計算各項統計檢定並輸出表格檔與 manifest.json（設定、資料與程式的 SHA-256）。"
      "build_report.py 讀取這些輸出檔產生論文，文中的數字全部由輸出檔讀取。")
    bd = fn("scripts/research/run_research.py", "build_dataset")
    h1 = X.code("scripts/research/run_research.py", [bd], "研究資料集與逐期股票池 build_dataset()")
    el = fn("src/research/exchange.py", "eligibility")
    h2 = X.code("src/research/exchange.py", [el], "逐期股票池（調倉日以前 20 日平均成交金額前 300 大）eligibility()")
    hm, ca, ho, bs = (fn("src/research/stats.py", x) for x in ("hac_mean", "capm", "holm", "bootstrap_ci_ann"))
    dt = fn("src/research/stats.py", "diff_test")
    h3 = X.code("src/research/stats.py", [hm, ca, dt, ho, bs], "統計檢定：HAC 平均數、CAPM、差異檢定、Holm 調整、區塊 bootstrap")
    t41 = rng("scripts/research/run_research.py", "# 表 4-1 績效", 'tdir / "table_4_1_performance.csv"')
    h4 = X.code("scripts/research/run_research.py", [t41], "表 4-1 績效與信賴區間的計算")
    Nn(f"註：run_research.py 輸出檔名與程式註解中的表號沿用初版編號，與論文表號的對應見{L('表', X.tab + 1)}。")
    rr = "scripts/research/run_research.py"
    X.table("論文表格、輸出檔與產生程式對照", ["論文表／圖", "輸出檔（outputs/research/thesis_2026-10-20/）", "產生程式"], [
        ["表 3-3 逐期股票池概況", "universe_summary.csv、universe_history.csv、universe_screening.csv", f"{loc('src/research/exchange.py', el)}（{h2}）；exchange.universe_summary()"],
        ["表 3-4 樣本期間切分", "tables/table_3_7_period_split.csv", f"{rr} main()"],
        ["表 3-8 參數試驗紀錄", "tables/table_3_8_parameter_trials.csv", "parameter_trials.csv（探索階段紀錄）"],
        ["表 4-1 績效比較", "tables/table_4_1_performance.csv", f"{loc(rr, t41)}（{h4}）"],
        ["表 4-2 各年度報酬", "tables/table_4_2_yearly.csv", "src/research/analysis.py yearly()"],
        ["表 4-3 投組 ESG 品質；圖 4-2", "tables/table_4_10_esg_quality.csv、esg_quality_by_rebalance.csv", "src/research/analysis.py esg_quality()"],
        ["表 4-4 風險指標比較", "tables/table_4_1_performance.csv、table_4_4_capture.csv", "build_report.py risk_table()"],
        ["表 4-5 市場情境", "tables/table_4_3_regimes.csv、regimes.csv", "src/research/analysis.py classify_regimes()、regime_table()"],
        ["表 4-6 上漲日／下跌日參與率", "tables/table_4_4_capture.csv", "src/research/analysis.py capture()"],
        ["表 4-7 CAPM 估計", "tables/table_4_5_capm_hac.csv", f"src/research/stats.py capm()、holm()（{h3}）"],
        ["表 4-8 日報酬差異檢定", "tables/table_4_6_diff_hac.csv", f"src/research/stats.py diff_test()、holm()（{h3}）"],
        ["表 4-9 模型選股能力", "tables/table_4_7_model_skill.csv、rank_ic.csv", "pipeline.rank_ic()、stats.hac_mean()"],
        ["表 4-10 假說檢驗彙整", "（由表 4-1、4-7、4-8 彙整）", "build_report.py ch4()"],
        ["表 4-11 股票池與調倉日期對照", "tables/table_4_2b_*.csv、table_4_11c_*.csv、strategy_returns_*.csv", f"{rr} main()（--test-yahoo 等對照）"],
        ["表 4-12 換股與交易成本", "tables/table_4_9a_turnover_cost.csv", f"{rr} main()"],
        ["表 4-13 滑價敏感度", "tables/table_4_9b_slippage.csv", f"{rr} resimulate()"],
        ["表 4-14 特徵重要性", "tables/table_4_8a_importance_distribution.csv、table_4_8b_permutation_importance.csv", f"{rr} main()"],
        ["圖 4-1 累積淨值", "strategy_returns.csv", "pipeline.run()；build_report.py figures()"],
        ["附錄 A 版本紀錄", "manifest.json", f"{rr} main()"],
    ], [3.6, 5.6, 4.6], "lll", size=8.5)
    X.explain("表", "將論文之各表與各圖對應至其輸出檔與產生程式；檢查論文數據時，可據此追溯原始輸出檔與計算程式。")

    # ---------------- 十三、測試
    D(2, "十三、程式測試")
    P("程式以 pytest 撰寫自動化測試，auto_push.py 在每次推送前執行；測試重點是確認回測沒有使用未來資訊、交易成本與報酬計算正確，"
      "以及各資料來源的解析格式。另以 smoke_ui.py 模擬 Streamlit 把每一頁從頭執行一次，確認畫面程式不會因資料處理錯誤而中斷。")
    T = [("tests/test_core.py", "test_asof_merge_uses_only_published_data", "ESG／財務資料只使用公告日以前已公告者"),
         ("tests/test_core.py", "test_future_prices_do_not_change_past_decisions", "加入未來股價不會改變過去的選股"),
         ("tests/test_core.py", "test_training_window_ends_before_rebalance", "訓練樣本截止於調倉日前 10 個交易日"),
         ("tests/test_core.py", "test_simulate_returns_start_next_day_and_costs", "報酬自調倉日下一個交易日起算並扣成本"),
         ("tests/test_core.py", "test_trading_cost_sell_side_has_tax", "賣出端含證交稅"),
         ("tests/test_core.py", "test_strategies_share_same_period", "三種策略的比較期間一致"),
         ("tests/test_core.py", "test_metrics_known_values", "績效指標與已知數值相符"),
         ("tests/test_core.py", "test_capm_alpha_beta", "CAPM Beta 與詹森 Alpha"),
         ("tests/test_core.py", "test_holding_forecast", "持有期間預估路徑"),
         ("tests/test_core.py", "test_pullback_exposure_threshold_and_no_lookahead", "短期轉弱減碼的門檻正確、只用當天以前的收盤價"),
         ("tests/test_core.py", "test_market_view_uses_only_past_and_follows_state", "大盤狀態預估只用已實現的資料；策略 Beta 計算正確"),
         ("tests/test_research.py", "test_eligibility_top_n_uses_past_window_only", "逐期股票池只用過去 20 日成交金額"),
         ("tests/test_research.py", "test_daily_returns_twse_and_tpex", "上市櫃日報酬（含權息）計算"),
         ("tests/test_research.py", "test_hac_and_holm", "HAC 標準誤與 Holm 調整"),
         ("tests/test_research.py", "test_regimes_use_previous_day", "市場情境只用前一日資訊")]
    rows = []
    for f, name, what in T:
        try:
            rows.append([name, loc(f, fn(f, name)), what])
        except StopIteration:
            continue
    n_core = sum(1 for l in lines_of("tests/test_core.py") if l.startswith("def test_"))
    n_res = sum(1 for l in lines_of("tests/test_research.py") if l.startswith("def test_"))
    X.table(f"主要測試項目（共 {n_core + n_res} 項，節錄）", ["測試函式", "程式位置", "檢查內容"], rows, [5.4, 4.4, 4.0], "lll", size=8.5)
    X.explain("表", "節錄主要之自動化測試及其檢查內容，重點在於確認回測未使用未來資料，以及交易成本與績效計算之正確性；每次推送程式至 GitHub 前均會自動執行全部測試。")
    ft = fn("tests/test_core.py", "test_future_prices_do_not_change_past_decisions")
    X.code("tests/test_core.py", [ft], "前視偏差測試（範例）")


# ------------------------------------------------------------------ 程式檔清單
PROGRAM_FILES = [
    ("網站頁面", [
        ("app.py", "首頁：資料狀態、最新選股、績效指標卡、累積淨值", "首頁"),
        ("pages/0_大盤趨勢預測.py", "多空指標判斷表、歷史趨勢圖、未來 1 個月展望", "大盤趨勢頁"),
        ("pages/1_策略回測.py", "績效比較、歷次持股與預估、換股成本、方法說明", "策略回測頁"),
        ("pages/2_個股分析.py", "個股走勢、風險指標、ESG、同業比較", "個股分析頁"),
        ("pages/3_模型解釋.py", "特徵重要性、Rank IC、SHAP、訓練紀錄", "模型解釋頁"),
        ("pages/4_產業與籌碼.py", "產業趨勢、三大法人買賣超", "產業與籌碼頁"),
        ("pages/5_論文正式版本.py", "論文第三、四章的正式表格與圖", "論文正式版本頁；第四章"),
    ]),
    ("介面元件", [
        ("src/ui/common.py", "側邊欄設定、回測結果快取、持股表與指標卡", "所有頁面"),
        ("src/ui/charts.py", "Plotly 圖表（策略配色固定）", "所有圖表"),
        ("src/_fresh.py", "雲端更新程式後重新載入模組", "所有頁面"),
        ("src/cache.py", "回測結果存檔（資料內容雜湊）", "首頁、策略回測、模型解釋"),
    ]),
    ("核心運算", [
        ("src/config.py", "共用設定：路徑、交易成本、調倉、模型參數", "全部；表 3-1、表 3-9"),
        ("src/pipeline.py", "串接資料→特徵→模型→選股→回測", "圖 1-1；首頁、策略回測"),
        ("src/features.py", "技術面、見頂訊號、產業特徵；依公告日對齊", "第三章第二節；表 3-5"),
        ("src/models.py", "Random Forest／XGBoost 滾動式訓練", "第三章第四節；模型解釋頁"),
        ("src/backtest.py", "調倉日、策略分數、權重、交易成本、回測", "第三章第三、四節"),
        ("src/metrics.py", "年化報酬、波動、Sharpe、回撤、Beta、Alpha", "第三章第五節；績效表"),
        ("src/forecast.py", "持有期間預估路徑與區間", "策略回測「歷次持股」"),
        ("src/market_trend.py", "大盤多空判斷與展望模型", "大盤趨勢頁"),
        ("src/analysis.py", "產業趨勢與法人買賣超彙整", "產業與籌碼頁"),
    ]),
    ("資料層", [
        ("src/store.py", "整合爬蟲與本機檔案、增量更新、股票池、Dataset", "首頁資料狀態；所有頁面"),
        ("src/crawlers/yahoo.py", "Yahoo Finance 股價批次下載", "股價、比較基準"),
        ("src/crawlers/twse.py", "證交所清單、估值、三大法人、成交金額", "估值；產業與籌碼頁"),
        ("src/loaders/tej.py", "讀取 TEJ TESG（公告日為可得日）", "ESG 資料；表 3-2"),
        ("src/loaders/local.py", "讀取自備 CSV（示範資料）", "合成示範資料"),
        ("src/utils.py", "代號格式、檔案讀寫工具", "—"),
    ]),
    ("論文研究", [
        ("src/research/exchange.py", "逐日行情、價格面板、逐期股票池", "第三章第一節；表 3-3"),
        ("src/research/stats.py", "HAC、CAPM、差異檢定、Holm、bootstrap", "第三章第五節；第四章第三節"),
        ("src/research/analysis.py", "市場情境、參與率、年度報酬、ESG 品質", "表 4-2、4-3、4-5、4-6"),
        ("scripts/research/run_research.py", "論文正式結果與 manifest", "第四章全部表格；附錄 A"),
        ("scripts/research/check_twse_coverage.py", "上市股票涵蓋率檢查", "第三章第一節（三）"),
        ("scripts/research/build_report.py", "產生論文 Word／PDF", "論文全文"),
        ("scripts/research/report_lib.py", "論文排版工具", "全文"),
        ("scripts/research/appendix_code.py", "論文附錄 A 與本程式對照文件的內容", "論文附錄 A；本文件"),
        ("scripts/research/build_code_doc.py", "產生本程式對照文件（Word）", "本文件"),
        ("scripts/research/capture_web.py", "論文表格截圖", "表 3-3～4-14"),
        ("scripts/research/capture_pages.py", "網站各頁截圖", "本文件各圖"),
    ]),
    ("資料與自動化腳本", [
        ("scripts/update_data.py", "指令列資料更新（每日排程呼叫）", "網站資料"),
        ("scripts/run_backtest.py", "指令列回測，預先產生網站存檔", "網站回測結果"),
        ("scripts/auto_push.py", "程式變動後自動測試並推送 GitHub", "網站部署"),
        ("scripts/backfill_daily_quotes.py", "證交所／櫃買中心逐日全市場行情", "論文資料"),
        ("scripts/fetch_yahoo_all.py", "研究用上市股票 Yahoo 日資料", "論文資料"),
        ("scripts/fetch_finmind_twse.py", "研究用 FinMind 上市行情（含下市）", "論文資料"),
        (".github/workflows/daily_update.yml", "每日自動更新排程", "網站資料"),
    ]),
    ("測試", [
        ("tests/test_core.py", "核心邏輯測試（前視偏差、成本、指標等）", "第十三節"),
        ("tests/test_research.py", "研究模組測試", "第十三節"),
        ("tests/smoke_ui.py", "各頁面冒煙測試", "第十三節"),
    ]),
]

PAGE_MAP = [
    ["首頁", "app.py", "pipeline.run()、metrics.performance_table()、charts.nav_chart()、bt.next_rebalance()", "資料狀態、最新選股、三策略與基準的年化報酬、累積淨值"],
    ["大盤趨勢", "pages/0_大盤趨勢預測.py", "market_trend.current_trend()、trend_series()、run()", "7 項指標多空判斷表、歷史趨勢底色圖、未來 1 個月展望"],
    ["策略回測", "pages/1_策略回測.py", "pipeline.run()、metrics.performance_table()、forecast.holding_forecast()、backtest.trading_cost()", "績效比較、歷次持股與持有期間預估、換股與成本、方法說明"],
    ["個股分析", "pages/2_個股分析.py", "crawlers.yahoo.fetch_prices()、metrics.price_metrics()、performance()", "個股走勢、風險指標、ESG 評等、同業比較"],
    ["模型解釋", "pages/3_模型解釋.py", "pipeline.rank_ic()、models.walk_forward() 的訓練紀錄", "Rank IC、特徵重要性、SHAP、訓練紀錄"],
    ["產業與籌碼", "pages/4_產業與籌碼.py", "analysis.industry_trend()、flow_leaders()、flow_by_industry()", "產業趨勢、三大法人買賣超排行"],
    ["論文正式版本", "pages/5_論文正式版本.py", "web_tables.json（build_report.py 產生）、charts.nav_chart()", "論文第三、四章的正式表格與圖"],
]


def architecture_figure(out_path):
    """圖 E-1：系統架構與資料流向。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    from matplotlib.patches import FancyBboxPatch
    for f in ["Noto Sans CJK TC", "Microsoft JhengHei", "DFKai-SB"]:
        if any(f in x.name for x in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = f
            break
    fig, ax = plt.subplots(figsize=(8.6, 5.6), dpi=220)
    ax.set_xlim(0, 10); ax.set_ylim(0, 6.6); ax.axis("off")
    NAVY, LIGHT = "#1F3864", "#EEF1F6"

    def box(x, y, w, h, title, body, dark=False):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.08",
                                    fc=NAVY if dark else LIGHT, ec=NAVY, lw=1.2))
        c = "white" if dark else NAVY
        ax.text(x + w / 2, y + h - 0.22, title, ha="center", va="top", fontsize=9.5, weight="bold", color=c)
        ax.text(x + w / 2, y + h - 0.55, body, ha="center", va="top", fontsize=7.0, color=c, linespacing=1.35)

    def arrow(a, b, text=""):
        ax.annotate("", xy=b, xytext=a, arrowprops=dict(arrowstyle="-|>", color=NAVY, lw=1.3))
        if text:
            ax.text((a[0] + b[0]) / 2 + 0.08, (a[1] + b[1]) / 2, text, fontsize=6.6, color=NAVY, va="center")

    box(0.1, 5.0, 9.8, 1.45, "外部資料來源", "Yahoo Finance（股價、比較基準、美股與 VIX）　證交所／櫃買中心（清單、逐日行情、估值、三大法人）\n"
        "TEJ（TESG 永續評等）　FinMind（已下市上市股票行情）", dark=True)
    box(0.1, 3.0, 3.0, 1.6, "① 資料層", "src/store.py　src/crawlers/\nsrc/loaders/\n→ data/processed、data/raw")
    box(3.5, 3.0, 3.0, 1.6, "② 運算層", "features → models\n→ backtest → metrics\n（pipeline.run）")
    box(6.9, 3.0, 3.0, 1.6, "③ 介面層（網站）", "app.py、pages/*.py\nsrc/ui/common.py、charts.py\n→ Streamlit Cloud")
    box(3.5, 0.75, 3.0, 1.75, "④ 研究層（論文）", "run_research.py\nsrc/research/\n→ outputs/research\n→ build_report.py → 本論文")
    box(0.1, 0.75, 3.0, 1.75, "⑤ 自動化", "GitHub Actions 每日更新\n（update_data.py、run_backtest.py）\nauto_push.py：測試後推送")
    box(6.9, 0.75, 3.0, 1.75, "論文正式版本頁", "pages/5_論文正式版本.py\n讀取 web_tables.json\ncapture_web.py 截圖回論文")
    arrow((1.6, 5.0), (1.6, 4.6), "下載")
    arrow((3.1, 3.8), (3.5, 3.8))
    arrow((6.5, 3.8), (6.9, 3.8))
    arrow((5.0, 3.0), (5.0, 2.5), "同一套程式")
    arrow((6.5, 1.6), (6.9, 1.6))
    arrow((1.6, 2.5), (1.6, 3.0), "觸發")
    arrow((8.4, 2.5), (8.4, 3.0))
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


# ------------------------------------------------------------------ 附錄 E（精簡版，論文使用）
LETTER = "A"      # 審核版只有這一份附錄


def appendix_e(R, shots_dir=None, note_fn=None, figure_fn=None):
    """精簡版附錄 E：網站頁面與核心程式對照、核心程式說明、資料更新與重現。不放截圖與程式碼。
    詳細版（各頁截圖與逐區塊對照）見 appendix_e_detail()。"""
    X = _Ctx(R, shots_dir or ".", prefix=LETTER)
    P, B, D, Nn = R.p, R.bullets, R.h, R.note
    D(1, f"附錄 {LETTER}　系統實作與核心程式")
    P("本研究的「ESG-AI 台股選股平台」以 Python 撰寫，網站以 Streamlit 建置並部署於 Streamlit Community Cloud，"
      "程式碼存放於 GitHub（Hendrick0815/ESG_AI_Dashboard）。本附錄說明網站各頁面由哪些程式產生，並簡介選股、回測與論文統計的核心程式；"
      "表中的行號於產生論文時由程式檔自動定位，與現行程式一致。", align=0)   # 靠左：英文名稱較長，左右對齊會拉開字距
    P("網站與論文共用同一套選股與回測程式，差別在於輸入：網站其他頁面以「目前」成交金額前 300 大回測，供日常查詢，含存活者偏誤；"
      "論文以逐期股票池（含之後下市的股票）重新計算，結果呈現在「論文正式版本」頁與第四章。網站中的「單純 ESG」即論文的「規則式 ESG 篩選投組」。")

    D(2, "一、網站頁面與程式對照")
    pg = lambda f: f"{f}（{n_lines(f)} 行）"
    X.table("網站頁面與程式對照", ["網站頁面", "頁面程式", "主要呼叫的核心程式", "畫面內容"], [
        ["首頁", pg("app.py"), "pipeline.run()、metrics.performance_table()", "資料狀態、最新選股名單、三種策略與比較基準的年化報酬、累積淨值"],
        ["大盤趨勢", pg("pages/0_大盤趨勢預測.py"), "market_trend.current_trend()", "7 項指標的多空判斷表與歷史趨勢圖（描述性，不用於選股）"],
        ["策略回測", pg("pages/1_策略回測.py"), "pipeline.run()、forecast.holding_forecast()", "績效比較、歷次持股與持有期間預估、換股成本、方法說明"],
        ["個股分析", pg("pages/2_個股分析.py"), "metrics.price_metrics()", "個股走勢、風險指標、ESG 評等、同業比較"],
        ["模型解釋", pg("pages/3_模型解釋.py"), "pipeline.rank_ic()", "Rank IC、特徵重要性、訓練紀錄"],
        ["產業與籌碼", pg("pages/4_產業與籌碼.py"), "analysis.industry_trend()、flow_leaders()", "產業趨勢、三大法人買賣超（僅供參考）"],
        ["論文正式版本", pg("pages/5_論文正式版本.py"), "讀取 build_report.py 產生的 web_tables.json", "論文第三、四章的正式表格與圖"],
    ], [1.8, 3.4, 4.0, 4.6], "llll")
    Nn("註：所有頁面共用側邊欄設定（src/ui/common.py sidebar_strategy()）與回測存檔（src/cache.py），同一組資料與參數只計算一次。")
    P(f"表 {LETTER}-1 對照網站七個頁面與其對應之程式檔及主要呼叫之核心函式。由表可知，各頁面僅負責呈現，選股、回測與績效計算皆集中於 src/ 目錄下之共用程式；論文正式版本頁則直接讀取論文產生程式所輸出之表格檔，故網站與論文之數據來源一致。")

    D(2, "二、核心程式")
    P("選股與回測由 pipeline.run() 串接，依序為：建立特徵 → 滾動訓練模型並預測 → 計算三種策略的分數 → 模擬每日淨值並扣除交易成本 → 計算績效。"
      f"表 {LETTER}-2 列出各步驟所在的程式位置與作用。")
    F = lambda f, n: loc(f, fn(f, n))
    X.table("核心程式說明", ["步驟", "程式位置", "說明"], [
        ["整體流程", F("src/pipeline.py", "run"), "串接資料、特徵、模型、選股與回測；網站與論文共用"],
        ["特徵與預測目標", F("src/features.py", "add_technical"), "動能、波動、均線乖離與見頂訊號等技術特徵；預測目標為未來 10 個交易日報酬"],
        ["ESG 與估值對齊", F("src/features.py", "asof_merge"), "每天只使用公告日以前已公告的 TESG 與估值，避免前視偏差"],
        ["調倉日", F("src/backtest.py", "rebalance_schedule"), "論文與網站皆每 2 週於同一星期幾調倉，遇休市順延"],
        ["AI 模型訓練與預測", F("src/models.py", "walk_forward"), "Random Forest 滾動式訓練，每 3 次調倉重訓；訓練樣本只到調倉日前 10 個交易日，預測相對報酬"],
        ["三種策略的選股分數", loc("src/backtest.py", fn("src/backtest.py", "apply_esg_rules"), fn("src/backtest.py", "score_strategies")),
         "單純 AI：模型分數；AI+ESG：排除爭議與 EPS 為負後，70% AI 排名＋30% ESG 排名；規則式 ESG：TESG 總分"],
        ["持股與權重", F("src/backtest.py", "make_weights"), "取分數最高 20 檔、等權"],
        ["每日淨值與交易成本", loc("src/backtest.py", fn("src/backtest.py", "trading_cost"), fn("src/backtest.py", "simulate")),
         "調倉日收盤換股，報酬自下一交易日起算；買賣手續費 0.1425%、賣出證交稅 0.3%"],
        ["績效指標", loc("src/metrics.py", fn("src/metrics.py", "performance"), fn("src/metrics.py", "capm")), "年化報酬、波動、Sharpe、最大回撤、Beta、詹森 Alpha"],
        ["逐期股票池（論文）", F("src/research/exchange.py", "eligibility"), "每個交易日以過去 20 日平均成交金額取前 300 大，含之後下市的股票"],
        ["統計檢定（論文）", loc("src/research/stats.py", fn("src/research/stats.py", "hac_mean"), fn("src/research/stats.py", "bootstrap_ci_ann")),
         "Newey-West 標準誤、CAPM、差異檢定、Holm 調整、區塊 bootstrap 信賴區間"],
        ["論文正式結果", F("scripts/research/run_research.py", "main"), "依 research_config.json 重跑回測，輸出第四章各表與 manifest.json"],
    ], [3.0, 5.0, 5.8], "lll")
    P(f"表 {LETTER}-2 依執行順序列示選股與回測各步驟所在之程式檔、行數及其功能。前九列為網站與論文共用之流程，後三列為論文專用之逐期股票池、統計檢定與正式結果產生程式；如需檢查特定步驟之計算，可依表列行數查閱對應程式。")

    D(2, "三、資料更新、部署與測試")
    B([f"**每日資料更新：**GitHub Actions（.github/workflows/daily_update.yml）於交易日 14:50 執行 scripts/update_data.py --auto，"
       f"由 {F('src/store.py', 'auto_update')} 補抓股價、比較基準、三大法人與估值，再預先計算回測並提交回 GitHub，網站隨之自動更新。",
       f"**程式部署：**本機 scripts/auto_push.py（{F('scripts/auto_push.py', 'publish')}）在程式修改後先執行測試，通過才推送到 GitHub。",
       f"**測試：**tests/ 內共 {sum(1 for l in lines_of('tests/test_core.py') + lines_of('tests/test_research.py') if l.startswith('def test_'))} 項自動化測試，"
       "重點檢查不使用未來資料（例如加入未來股價不會改變過去的選股）、交易成本與績效計算正確。",
       "**論文產生：**scripts/research/build_report.py 讀取 run_research.py 的輸出檔產生本論文，文中數字皆由輸出檔讀取，不手動輸入。",
       f"**資料截點後的網站更新（2026 年 11 月）：**網站「策略回測」頁的持有期間預估改為依調倉日的大盤狀態估計大盤報酬，並顯示期末虧損機率"
       f"（{F('src/forecast.py', 'market_view')}）；側邊欄新增選用的「短期轉弱減碼」（{F('src/backtest.py', 'pullback_exposure')}，預設關閉）；"
       "另提供把大盤狀態加入模型特徵的設定開關（src/config.py USE_MARKET_FEATURES，預設關閉）。本論文的結果以 2026-10-20 資料截點與表 3-1 之設定為準，未使用這些選用功能。"])
