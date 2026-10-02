"""自動發佈：資料夾裡的檔案一有變動，就跑測試 → 通過才 commit + push 到 GitHub → Streamlit Cloud 自動重新部署。

用法（在專案根目錄）：
    py scripts/auto_push.py            # 一直監看（視窗開著就會運作；Ctrl+C 結束）
    py scripts/auto_push.py --once     # 只檢查一次（有變動就發佈），適合手動或排程
雙擊 scripts/start_auto_push.bat 也可以；scripts/install_auto_push.bat 讓它開機登入後自動在背景執行。

規則
- 偵測到變動就立刻發佈（每 5 秒檢查一次）。
- 有改到 .py：先跑 tests/test_core.py 和 tests/smoke_ui.py，任何一個失敗就不推，等下次有新變動再試。
- 只改資料（股價 CSV 等）：不跑測試，直接推。
- push 被拒（GitHub 上有比較新的版本）：先 git pull --rebase 再推一次。
紀錄：data/processed/auto_push.log
"""
from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "data" / "processed" / "auto_push.log"
POLL_SECONDS = 5
TESTS = ["tests/test_core.py", "tests/smoke_ui.py"]
# 有 GitHub Actions 每日更新時，資料一律以 GitHub 上的為準：本機抓的股價、回測存檔不推，避免兩邊衝突
CLOUD_DATA = (ROOT / ".github" / "workflows" / "daily_update.yml").exists()
DATA_PATHS = ("data/processed/", "outputs/cache/")
TEST_TIMEOUT = 900


def log(msg: str) -> None:
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    try:
        print(line, flush=True)
    except Exception:
        pass
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def git(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 失敗：{(r.stderr or r.stdout).strip()}")
    return r


def pending_changes() -> list[str]:
    """git 看得到、還沒 commit 的檔案（已被 .gitignore 排除的不算）。"""
    out = git("-c", "core.quotePath=false", "status", "--porcelain", "-uall").stdout
    files = []
    for line in out.splitlines():
        path = line[3:].strip().strip('"')
        if " -> " in path:                         # 改名
            path = path.split(" -> ", 1)[1]
        if CLOUD_DATA and path.startswith(DATA_PATHS):
            continue
        files.append(path)
    return files


def signature(files: list[str]) -> tuple:
    sig = []
    for f in files:
        p = ROOT / f
        try:
            st = p.stat()
            sig.append((f, st.st_mtime_ns, st.st_size))
        except FileNotFoundError:
            sig.append((f, None, None))           # 刪除
    return tuple(sorted(sig))


def run_tests() -> bool:
    env = {**os.environ, "ESG_CACHE_DIR": tempfile.mkdtemp(prefix="esg_test_cache_"),  # 測試的存檔不要混進專案
           "PYTHONIOENCODING": "utf-8"}
    for t in TESTS:
        log(f"  測試 {t} …")
        try:
            r = subprocess.run([sys.executable, t], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", env=env, timeout=TEST_TIMEOUT)
        except subprocess.TimeoutExpired:
            log(f"  ✗ {t} 超過 {TEST_TIMEOUT // 60} 分鐘沒跑完")
            return False
        if r.returncode != 0:
            tail = "\n".join((r.stdout + r.stderr).strip().splitlines()[-15:])
            log(f"  ✗ {t} 沒通過，這次不發佈：\n{tail}")
            return False
    log("  ✓ 測試全部通過")
    return True


def publish(files: list[str]) -> bool:
    code = [f for f in files if f.endswith(".py")]
    if code and not run_tests():
        return False
    if CLOUD_DATA:
        # 本機資料丟掉、改用 GitHub 上每天自動更新的版本（兩邊內容一樣，只是避免合併衝突）
        for d in DATA_PATHS:                      # 分開做：某個資料夾還沒被 git 追蹤時不會讓另一個失敗
            if (ROOT / d).exists():
                git("checkout", "--", d)
                # 本機才有、GitHub 上後來新增的資料檔（例如 institutional.csv）會擋住 pull，
                # 一併刪掉改用 GitHub 的版本（.gitignore 裡的檔案，例如 auto_push.log，不受影響）
                git("clean", "-fq", "--", d)
        if (ROOT / "outputs" / "cache").exists():
            git("clean", "-fq", "--", "outputs/cache/")
    pull = git("pull", "--rebase", "--autostash")
    if pull.returncode != 0:
        git("rebase", "--abort")
        log(f"  ✗ 無法和 GitHub 上的版本合併，請用 GitHub Desktop 處理：{(pull.stderr or pull.stdout).strip()[-600:]}")
        return False
    if CLOUD_DATA:
        git("add", "-A", "--", ".", *[f":(exclude){p}" for p in DATA_PATHS], check=True)
    else:
        git("add", "-A", check=True)
    if not git("diff", "--cached", "--name-only").stdout.strip():
        return True
    names = [Path(f).name for f in files]
    summary = "、".join(names[:5]) + (f" 等 {len(names)} 個檔案" if len(names) > 5 else "")
    git("commit", "-m", f"auto: 更新 {summary}", check=True)
    r = git("push")
    if r.returncode != 0:
        log("  push 被拒，先同步 GitHub 上的新版本再推一次 …")
        pull = git("pull", "--rebase", "--autostash")
        if pull.returncode != 0:
            git("rebase", "--abort")
            log(f"  ✗ 無法自動合併，請用 GitHub Desktop 處理：{(pull.stderr or pull.stdout).strip()[-600:]}")
            return False
        r = git("push")
    if r.returncode != 0:
        log(f"  ✗ push 失敗：{(r.stderr or r.stdout).strip()[:300]}")
        return False
    log(f"  ✓ 已推到 GitHub（{summary}），網站約 1～3 分鐘後自動更新")
    return True


def main() -> None:
    ap = argparse.ArgumentParser(description="檔案有變動就測試並推到 GitHub")
    ap.add_argument("--once", action="store_true", help="只檢查一次")
    args = ap.parse_args()

    if git("rev-parse", "--is-inside-work-tree").returncode != 0:
        log("✗ 這個資料夾還不是 git repository，請先照 DEPLOY.md 用 GitHub Desktop 建立並 publish。")
        sys.exit(1)
    if not git("remote").stdout.strip():
        log("✗ 還沒有設定 GitHub remote，請先照 DEPLOY.md 按 Publish repository。")
        sys.exit(1)

    if args.once:
        files = pending_changes()
        if files:
            log(f"發現 {len(files)} 個變動檔案")
            publish(files)
        else:
            log("沒有變動")
        return

    try:   # 避免同時開兩個監看程式（例如開機自動啟動後又手動雙擊）
        guard = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        guard.bind(("127.0.0.1", 47631))
    except OSError:
        log("已經有一個自動發佈程式在執行，這個視窗不需要再開。")
        return
    log(f"開始監看 {ROOT}（偵測到變動就發佈；Ctrl+C 結束）")
    failed_sig = None
    while True:
        try:
            files = pending_changes()
            sig = signature(files) if files else None
            if sig is not None and sig != failed_sig:
                log(f"偵測到 {len(files)} 個變動檔案，開始發佈")
                if publish(files):
                    failed_sig = None
                else:
                    failed_sig = sig          # 測試失敗：同樣的內容不重試，等下一次變動
        except KeyboardInterrupt:
            raise
        except Exception as e:  # noqa: BLE001  監看程式本身不要因為一次錯誤就停掉
            log(f"✗ 發生錯誤（稍後重試）：{e}")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    try:
        main()
    except KeyboardInterrupt:
        log("停止監看")
