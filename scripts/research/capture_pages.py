"""把網站各頁面整頁截圖，給論文附錄 E（系統實作與程式對照）使用。
輸出：outputs/research/<run_id>/report/pages/*.png

用法：
    python scripts/research/capture_pages.py                 # 自動啟動本機網站（port 8599）
    python scripts/research/capture_pages.py --url http://localhost:8501
第一次開「首頁」若該組設定沒有回測存檔，網站會先訓練模型（數分鐘），程式會等它算完。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
CFG = json.loads((ROOT / "research_config.json").read_text(encoding="utf-8"))
OUT = ROOT / "outputs" / "research" / CFG["run_id"] / "report" / "pages"
W = 1180                       # 截圖寬度（CSS px）

HIDE = """
header[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"],
[data-testid="stStatusWidget"], [data-testid="stToast"], [data-testid="stToastContainer"] {display:none !important}
"""
NO_SIDEBAR = 'section[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"] {display:none !important}'

# (檔名, 頁面路徑, 動作)；動作：("tab", 分頁名稱)、("type", 標籤文字, 輸入值)、("radio", 選項文字)
SHOTS = [
    ("home_sidebar", "", [("sidebar",)]),
    ("home", "", []),
    ("trend", "大盤趨勢預測", []),
    ("backtest_perf", "策略回測", [("tab", "績效比較")]),
    ("backtest_holdings", "策略回測", [("tab", "歷次持股")]),
    ("backtest_trades", "策略回測", [("tab", "換股與成本")]),
    ("backtest_method", "策略回測", [("tab", "方法說明")]),
    ("stock_price", "個股分析", [("type", "輸入代號", "2330"), ("tab", "走勢")]),
    ("stock_risk", "個股分析", [("type", "輸入代號", "2330"), ("tab", "風險與技術指標")]),
    ("stock_esg", "個股分析", [("type", "輸入代號", "2330"), ("tab", "ESG")]),
    ("stock_peer", "個股分析", [("type", "輸入代號", "2330"), ("tab", "同業比較")]),
    ("model", "模型解釋", []),
    ("industry", "產業與籌碼", [("tab", "產業趨勢")]),
    ("flows", "產業與籌碼", [("tab", "主力動向（三大法人）")]),
    ("thesis", "論文正式版本", [("tab", "樣本與期間")]),
]


def wait_up(url, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            urllib.request.urlopen(url, timeout=3)
            return True
        except Exception:
            time.sleep(1)
    return False


def settle(pg, timeout=900):
    """等網站跑完（沒有進度條、沒有「Running」）。"""
    t0 = time.time()
    time.sleep(2)
    while time.time() - t0 < timeout:
        busy = pg.locator('[data-testid="stProgress"], [data-testid="stSpinner"]').count()
        running = pg.evaluate("() => !!document.querySelector('[data-testid=\"stStatusWidget\"]')"
                              " && document.querySelector('[data-testid=\"stStatusWidget\"]').innerText.includes('Running')")
        if not busy and not running and pg.locator("h1").count():
            time.sleep(3)
            return
        time.sleep(2)


def shoot(pg, base, name, path, actions):
    pg.set_viewport_size({"width": W, "height": 1000})
    pg.goto(f"{base.rstrip('/')}/{quote(path)}", wait_until="networkidle")
    settle(pg)
    sidebar = any(a[0] == "sidebar" for a in actions)
    pg.add_style_tag(content=HIDE)
    for a in actions:
        if a[0] == "type":
            box = pg.get_by_label(a[1], exact=False).first
            box.fill(a[2])
            box.press("Enter")
            settle(pg)
        elif a[0] == "tab":
            pg.get_by_role("tab", name=a[1]).first.click()
            settle(pg)
        elif a[0] == "radio":
            pg.get_by_text(a[1], exact=True).first.click()
            settle(pg)
    if not sidebar:
        pg.add_style_tag(content=NO_SIDEBAR)      # 操作完側邊欄（例如輸入代號）再隱藏
    if sidebar:
        pg.screenshot(path=str(OUT / f"{name}.png"))
        return
    # Streamlit 的內容在內層容器捲動：把視窗拉高到內容高度再截
    h = pg.evaluate("() => { const m = document.querySelector('[data-testid=\"stMainBlockContainer\"]');"
                    " return Math.ceil(m.getBoundingClientRect().height) + 40; }")
    pg.set_viewport_size({"width": W, "height": max(600, min(h, 14000))})
    time.sleep(3)
    el = pg.locator('[data-testid="stMainBlockContainer"]').first
    el.screenshot(path=str(OUT / f"{name}.png"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url")
    ap.add_argument("--only", nargs="*", help="只截這幾張（檔名）")
    args = ap.parse_args()
    proc, base = None, args.url
    if not base:
        base = "http://localhost:8599"
        proc = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "app.py", "--server.headless", "true",
                                 "--server.port", "8599"], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not wait_up(base):
            sys.exit("網站沒有啟動")
        from playwright.sync_api import sync_playwright
        OUT.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": W, "height": 1000}, device_scale_factor=1.5, color_scheme="light")
            for name, path, actions in SHOTS:
                if args.only and name not in args.only:
                    continue
                t0 = time.time()
                shoot(pg, base, name, path, actions)
                print(f"{name}：{time.time() - t0:.0f} 秒", flush=True)
            b.close()
    finally:
        if proc:
            proc.terminate()


if __name__ == "__main__":
    main()
