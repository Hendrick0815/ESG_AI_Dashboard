"""把網站「論文正式版本」頁面的表格與圖截圖，存到 outputs/research/<run_id>/report/web/，
build_report.py 會用這些截圖取代對應的表格與圖。

用法：
    python scripts/research/build_report.py          # 先產生 web_tables.json
    python scripts/research/capture_web.py           # 自動啟動本機網站並截圖（或 --url 指定已開啟的網站）
    python scripts/research/build_report.py          # 重新產生論文，表格換成截圖
需要 playwright（pip install playwright；python -m playwright install chromium）。
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
from report_lib import SHOT_CSS_W, SHOT_DPR  # noqa: E402

CFG = json.loads((ROOT / "research_config.json").read_text(encoding="utf-8"))
OUT = ROOT / "outputs" / "research" / CFG["run_id"] / "report" / "web"
PAGE = "論文正式版本"
CSS = f"""
section[data-testid="stSidebar"], header[data-testid="stHeader"], [data-testid="stToolbar"] {{display:none !important}}
[data-testid="stMainBlockContainer"] {{max-width:{SHOT_CSS_W + 40}px !important; padding:24px 20px !important}}
"""


def wait_up(url, timeout=90):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            urllib.request.urlopen(url, timeout=3)
            return True
        except Exception:
            time.sleep(1)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="已在執行的網站網址（預設自動啟動 http://localhost:8599）")
    args = ap.parse_args()
    proc = None
    base = args.url
    if not base:
        base = "http://localhost:8599"
        proc = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "app.py", "--server.headless", "true",
                                 "--server.port", "8599"], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not wait_up(base):
            sys.exit("網站沒有啟動")
        from playwright.sync_api import sync_playwright
        keys = [t["key"] for t in json.loads((OUT.parent / "web_tables.json").read_text(encoding="utf-8"))]
        OUT.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1100, "height": 1400}, device_scale_factor=SHOT_DPR, color_scheme="light")
            pg.goto(f"{base.rstrip('/')}/{quote(PAGE)}?all=1", wait_until="networkidle")
            pg.wait_for_selector(".st-key-tbl-4-12", timeout=120_000)
            pg.add_style_tag(content=CSS)
            pg.wait_for_selector(".st-key-fig-4-2 .main-svg", timeout=60_000)
            time.sleep(2)
            n = 0
            for k in keys:
                for prefix, name in (("tbl", k), ("fig", f"fig-{k}")):
                    loc = pg.locator(f".st-key-{prefix}-{k}")
                    if loc.count():
                        loc.first.scroll_into_view_if_needed()
                        loc.first.screenshot(path=str(OUT / f"{name}.png"))
                        n += 1
            b.close()
        print(f"截圖 {n} 張 → {OUT}")
    finally:
        if proc:
            proc.terminate()


if __name__ == "__main__":
    main()
