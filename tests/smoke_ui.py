"""畫面冒煙測試：用假的 streamlit / plotly 把每一頁從頭跑到尾，確認不會因資料處理出錯而當掉。
（不檢查外觀；真正的畫面請用 streamlit run app.py 看）

    python tests/smoke_ui.py
"""
from __future__ import annotations

import runpy
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class Stop(Exception):
    pass


class Ctx:
    def __init__(self, st):
        self.st = st

    def __enter__(self):
        return self.st

    def __exit__(self, *a):
        return False

    def __getattr__(self, name):
        return getattr(self.st, name)


class FakeStreamlit(types.ModuleType):
    def __init__(self, overrides=None):
        super().__init__("streamlit")
        self.session_state = {}
        self.sidebar = self
        self.overrides = overrides or {}
        self.log = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    # 顯示類：記錄下來即可
    def _show(self, kind, *a, **k):
        self.log.append((kind, a[0] if a else None))
        return Ctx(self)

    def __getattr__(self, name):
        if name in {"title", "caption", "markdown", "header", "subheader", "write", "info", "warning", "error",
                    "success", "metric", "divider", "code", "json", "set_page_config", "image", "empty", "update"}:
            return lambda *a, **k: self._show(name, *a, **k)
        raise AttributeError(name)

    def dataframe(self, data, *a, **k):
        if hasattr(data, "to_html"):
            data.to_html()          # 強制套用 Styler 格式，格式字串寫錯會在這裡爆
        self.log.append(("dataframe", getattr(data, "shape", None)))

    def plotly_chart(self, fig, *a, **k):
        self.log.append(("chart", fig))

    def download_button(self, label, data, *a, **k):
        assert isinstance(data, (bytes, str)) and len(data) > 0, label

    def columns(self, spec, **k):
        n = spec if isinstance(spec, int) else len(spec)
        return [Ctx(self) for _ in range(n)]

    def tabs(self, names):
        return [Ctx(self) for _ in names]

    def expander(self, *a, **k):
        return Ctx(self)

    popover = status = spinner = container = expander

    def progress(self, *a, **k):
        return Ctx(self)

    # 輸入類：回傳預設值（可用 overrides 指定）
    def _pick(self, label, default):
        return self.overrides.get(label, default)

    def radio(self, label, options, index=0, format_func=str, **k):
        [format_func(o) for o in options]
        return self._pick(label, list(options)[index])

    def selectbox(self, label, options, index=0, format_func=str, **k):
        options = list(options)
        [format_func(o) for o in options]
        return self._pick(label, options[index] if options else None)

    def multiselect(self, label, options, default=None, format_func=str, **k):
        [format_func(o) for o in options]
        return self._pick(label, list(default or []))

    def slider(self, label, min_value=None, max_value=None, value=None, step=None, **k):
        return self._pick(label, value)

    def select_slider(self, label, options, value=None, **k):
        return self._pick(label, value)

    def checkbox(self, label, value=False, **k):
        return self._pick(label, value)

    toggle = checkbox

    def text_input(self, label, value="", **k):
        return self._pick(label, value)

    def date_input(self, label, value=None, **k):
        return self._pick(label, value)

    def button(self, label, **k):
        return self._pick(label, False)

    def stop(self):
        raise Stop()

    def rerun(self):
        raise Stop()

    @staticmethod
    def _cache(func=None, **kw):
        def deco(f):
            store = {}

            def wrapper(*a):
                key = repr(a)
                if key not in store:
                    store[key] = f(*a)
                return store[key]
            wrapper.clear = store.clear
            return wrapper
        return deco(func) if callable(func) else deco

    cache_data = cache_resource = _cache

    class column_config:   # noqa: N801
        CheckboxColumn = staticmethod(lambda *a, **k: None)


def fake_plotly():
    plotly = types.ModuleType("plotly")
    go = types.ModuleType("plotly.graph_objects")
    px = types.ModuleType("plotly.express")

    class Fig:
        def __init__(self, *a, **k):
            self.traces = list(a[:1]) if a and not isinstance(a[0], list) else list(a[0]) if a else []

        def add_trace(self, t):
            self.traces.append(t)

        def __getattr__(self, name):
            return lambda *a, **k: self

    go.Figure = Fig
    for n in ["Scatter", "Candlestick", "Bar", "Histogram", "Scatterpolar"]:
        setattr(go, n, lambda *a, _n=n, **k: (_n, k))
    plotly.graph_objects, plotly.express = go, px
    return {"plotly": plotly, "plotly.graph_objects": go, "plotly.express": px}


AUTO_CALLS = []


def _no_network():
    """冒煙測試不連網：自動更新改成假的（仍會走過「需要更新 → 顯示進度 → 清快取」整段流程）。"""
    from src import store
    store.needs_price_update = lambda now=None: True
    store.auto_update = lambda progress=None, **k: (AUTO_CALLS.append(1), progress and progress("假更新"),
                                                    {"last_price_date": "2000-01-01"})[-1]


def run_page(path: str, overrides=None) -> FakeStreamlit:
    _no_network()
    st = FakeStreamlit(overrides)
    for m in [m for m in sys.modules if m.startswith("src.ui")]:
        del sys.modules[m]
    sys.modules.update({"streamlit": st, **fake_plotly()})
    try:
        runpy.run_path(str(ROOT / path), run_name="__main__")
    except Stop:
        pass
    return st


if __name__ == "__main__":
    demo = {"資料來源": "demo", "每次持有檔數（Top N）": 3, "樹的數量": 50}
    cases = [
        ("app.py", demo), ("pages/1_策略回測.py", demo), ("pages/2_個股分析.py", demo),
        ("pages/3_模型解釋.py", demo), ("pages/4_產業與籌碼.py", demo),
        ("pages/1_策略回測.py", {**demo, "風險控制（降低最大回撤，報酬會變低）": True}),
        ("pages/1_策略回測.py", {**demo, "期間": "自訂"}),
        ("pages/1_策略回測.py", {**demo, "權重方式": "集中加權"}),
        ("pages/2_個股分析.py", {**demo, "K 線圖": True, "期間": "3 個月"}),
        ("app.py", {"資料來源": "real"}),            # 沒有真實股價 → 應提示更新；有的話跑完整流程
        ("pages/1_策略回測.py", {"資料來源": "real"}),
        ("pages/4_產業與籌碼.py", {"資料來源": "real"}),
        ("pages/4_產業與籌碼.py", {"資料來源": "real", "統計期間": 20}),
    ]
    failed = 0
    for path, ov in cases:
        try:
            st = run_page(path, ov)
            errs = [x for x in st.log if x[0] == "error"]
            charts = sum(1 for x in st.log if x[0] == "chart")
            tables = sum(1 for x in st.log if x[0] == "dataframe")
            status = "FAIL" if errs else "PASS"
            failed += bool(errs)
            print(f"{status} {path} {ov}  圖 {charts}、表 {tables} {errs[:2] if errs else ''}")
        except Exception as e:
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {path} {ov} → {e!r}")
    if not AUTO_CALLS:
        failed += 1
        print("FAIL 真實資料模式沒有觸發自動更新股價")
    print("\n全部通過" if not failed else f"\n{failed} 個失敗")
    sys.exit(1 if failed else 0)
