"""核心功能測試。執行：pytest tests/  或  python tests/test_core.py（不需安裝 pytest）"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import backtest as bt  # noqa: E402
from src import config, metrics, store  # noqa: E402
from src.crawlers import twse, yahoo  # noqa: E402
from src.features import asof_merge  # noqa: E402
from src.loaders import local as local_loader  # noqa: E402
from src.loaders.tej import load_tej, parse_tej  # noqa: E402
from src.pipeline import Params, run  # noqa: E402
from src.utils import normalize_ticker, read_csv_any  # noqa: E402

FIX = Path(__file__).parent / "fixtures"


# ------------------------------------------------------------------ 小工具
def test_normalize_ticker():
    assert normalize_ticker("2330") == "2330.TW"
    assert normalize_ticker(2330) == "2330.TW"
    assert normalize_ticker("2330.0") == "2330.TW"
    assert normalize_ticker(" 2330.tw ") == "2330.TW"
    assert normalize_ticker("6488", otc_codes={"6488"}) == "6488.TWO"
    assert normalize_ticker("^TWII") == "^TWII"
    assert normalize_ticker("00878") == "00878.TW"
    assert normalize_ticker(None) is None


def test_metrics_known_values():
    r = pd.Series([0.1, -0.1])
    m = metrics.performance(r, rf=0.0)
    assert abs(m["cum_return"] - (1.1 * 0.9 - 1)) < 1e-12
    assert abs(m["max_drawdown"] - (-0.1)) < 1e-12
    assert m["n_days"] == 2
    # 一路下跌時回撤從起始淨值 1 算起
    assert abs(metrics.performance(pd.Series([-0.05, -0.05]))["max_drawdown"] - (0.95 ** 2 - 1)) < 1e-12


# ------------------------------------------------------------------ 爬蟲解析（離線）
def test_parse_isin_table_keeps_only_common_stock():
    html = (FIX / "isin_sample.html").read_text(encoding="utf-8")
    df = twse.parse_isin_table(html, "上市")
    assert set(df["ticker"]) == {"1101.TW", "2330.TW"}          # ETF 0050、權證、特別股都被排除
    assert df.set_index("ticker").loc["2330.TW", "name"] == "台積電"
    assert df.set_index("ticker").loc["2330.TW", "industry"] == "半導體業"


def test_parse_bwibbu():
    payload = {"stat": "OK", "fields": ["證券代號", "證券名稱", "收盤價", "殖利率(%)", "股利年度", "本益比", "股價淨值比", "財報年/季"],
               "data": [["2330", "台積電", "1,000.00", "1.50", "114", "25.10", "6.80", "115/2"],
                        ["1101", "台泥", "30.00", "4.00", "114", "-", "0.90", "115/2"],
                        ["00878", "國泰永續高股息", "20", "6", "114", "-", "-", "-"]]}
    df = twse.parse_bwibbu(payload, pd.Timestamp("2026-08-31"))
    assert list(df["ticker"]) == ["2330.TW", "1101.TW"]
    row = df.set_index("ticker").loc["2330.TW"]
    assert row["pe"] == 25.1 and row["pb"] == 6.8 and abs(row["dividend_yield"] - 0.015) < 1e-12
    assert np.isnan(df.set_index("ticker").loc["1101.TW", "pe"])
    assert twse.parse_bwibbu({"stat": "很抱歉，沒有符合條件的資料!"}, pd.Timestamp("2026-08-30")).empty


def test_parse_yf_frame_both_layouts():
    idx = pd.to_datetime(["2026-01-02", "2026-01-05"])
    fields = ["Open", "High", "Low", "Close", "Volume"]
    for ticker_first in (True, False):
        cols = pd.MultiIndex.from_product([["2330.TW", "2317.TW"], fields] if ticker_first
                                          else [fields, ["2330.TW", "2317.TW"]])
        raw = pd.DataFrame(np.arange(20, dtype=float).reshape(2, 10) + 1, index=idx, columns=cols)
        raw.index.name = "Date"
        df = yahoo.parse_yf_frame(raw, ["2330.TW", "2317.TW"])
        assert len(df) == 4 and set(df["ticker"]) == {"2330.TW", "2317.TW"}
        assert list(df.columns) == yahoo.PRICE_COLS
    single = pd.DataFrame({"Close": [1.0, 2.0], "Open": [1, 2], "High": [1, 2], "Low": [1, 2], "Volume": [5, 6]},
                          index=pd.DatetimeIndex(idx, name="Date"))
    assert yahoo.parse_yf_frame(single, ["2330.TW"])["ticker"].eq("2330.TW").all()


# ------------------------------------------------------------------ 本機資料
TEJ_2026 = config.TEJ_DIR / "tesg_2026Q2.csv"


def test_tej_file_reads_with_announcement_date():
    tej = parse_tej(read_csv_any(TEJ_2026, dtype=str), source=TEJ_2026.name)
    assert len(tej) > 1000
    assert (tej["available_date"] == pd.Timestamp("2026-05-04")).all()
    row = tej.set_index("ticker").loc["1101.TW"]
    assert row["name"] == "台泥" and abs(row["esg_total"] - 61.21) < 1e-9 and abs(row["e_score"] - 85.09) < 1e-9


def test_tej_folder_merges_multiple_periods():
    """資料夾內多個檔案（含重複的期別）合併後，每家公司每期只留一筆。"""
    tej = load_tej(config.TEJ_DIR)
    assert not tej.duplicated(["ticker", "period"]).any()
    if len(list(config.TEJ_DIR.glob("*.csv"))) > 1:
        assert tej["available_date"].nunique() >= 2


def test_tej_duplicate_files_are_deduplicated():
    raw = read_csv_any(TEJ_2026, dtype=str)
    a = parse_tej(raw, source="a.csv")
    both = pd.concat([a, parse_tej(raw, source="b.csv")])
    dedup = both.sort_values(["ticker", "period", "available_date"]).drop_duplicates(["ticker", "period"], keep="last")
    assert len(dedup) == len(a)


def test_local_wide_price_format():
    wide = pd.DataFrame({"date": ["2026-01-02", "2026-01-05"], "2330": [100, 101], "2317.TW": [50, 51]})
    df = local_loader.parse_prices(wide)
    assert set(df["ticker"]) == {"2330.TW", "2317.TW"} and len(df) == 4


def test_merge_prices_web_overrides_local():
    d = pd.Timestamp("2026-01-02")
    local = pd.DataFrame({"date": [d], "ticker": ["2330.TW"], "close": [100.0], "source": ["local"]})
    web = pd.DataFrame({"date": [d], "ticker": ["2330.TW"], "close": [99.0], "source": ["yahoo"]})
    assert store.merge_prices(web, local)["close"].tolist() == [99.0]   # 不論傳入順序，網路優先
    assert store.merge_prices(local, web)["close"].tolist() == [99.0]


def test_weekend_rows_are_dropped():
    d = pd.to_datetime(["2026-09-18", "2026-09-20"])   # 週五、週日
    df = pd.DataFrame({"date": d, "ticker": "2330.TW", "close": [1.0, 1.0], "source": "yahoo"})
    assert store.merge_prices(df)["date"].tolist() == [pd.Timestamp("2026-09-18")]
    assert store.month_end_trading_days(df) == [pd.Timestamp("2026-09-18")]


def test_failed_tickers_retry_in_batches_and_are_skipped_next_time(tmp_path=None):
    """抓不到的股票只批次重試一輪（不再一檔一檔等），且 7 天內不再重抓。"""
    import tempfile
    import types
    tmp = Path(tmp_path or tempfile.mkdtemp())
    calls = []

    def fake_download(batch, **k):
        calls.append(list(batch))
        idx = pd.bdate_range("2026-09-01", "2026-09-18", name="Date")
        cols = pd.MultiIndex.from_product([batch, ["Open", "High", "Low", "Close", "Volume"]])
        df = pd.DataFrame(np.nan, index=idx, columns=cols)
        for t in batch:
            if not t.startswith("9"):     # 9 開頭的假裝 Yahoo 沒資料
                df[t] = 1.0
        return df

    old = (yahoo.yf, yahoo.YF_AVAILABLE, yahoo.time.sleep, config.PRICES_FILE, store.FAILED_FILE)
    try:
        yahoo.yf, yahoo.YF_AVAILABLE = types.SimpleNamespace(download=fake_download), True
        yahoo.time.sleep = lambda s: None
        config.PRICES_FILE, store.FAILED_FILE = tmp / "p.csv", tmp / "f.csv"
        tickers = [f"{1000 + i}.TW" for i in range(120)] + [f"{9000 + i}.TW" for i in range(30)]
        r = store.update_prices(tickers, "2026-09-01", "2026-09-18")
        assert len(r["failed"]) == 30 and len(calls) <= 5          # 3 批 + 2 批重試
        calls.clear()
        r2 = store.update_prices(tickers, "2026-09-01", "2026-09-18")
        assert r2["skipped_recent_failures"] == 30 and calls == []
    finally:
        yahoo.yf, yahoo.YF_AVAILABLE, yahoo.time.sleep, config.PRICES_FILE, store.FAILED_FILE = old


def test_plan_fetch_is_incremental():
    days = pd.bdate_range("2026-01-01", "2026-03-31")
    existing = pd.DataFrame({"date": days, "ticker": "2330.TW", "close": 1.0})
    plan = store.plan_fetch(existing, ["2330.TW", "2317.TW"], "2026-01-01", "2026-04-15")
    flat = {t: k for k, ts in plan.items() for t in ts}
    assert flat["2317.TW"] <= pd.Timestamp("2026-01-01")              # 沒資料 → 從頭抓
    assert pd.Timestamp("2026-03-16") <= flat["2330.TW"] <= pd.Timestamp("2026-03-31")  # 只補最後一段
    assert store.plan_fetch(existing, ["2330.TW"], "2026-01-01", "2026-03-31") == {}   # 已最新


# ------------------------------------------------------------------ 前視偏差
def test_asof_merge_uses_only_published_data():
    panel = pd.DataFrame({"date": pd.to_datetime(["2026-05-01", "2026-05-04", "2026-06-01"]), "ticker": "1101.TW"})
    esg = pd.DataFrame({"ticker": ["1101.TW"], "available_date": [pd.Timestamp("2026-05-04")], "esg_total": [61.2]})
    out = asof_merge(panel, esg, ["esg_total"])
    assert np.isnan(out.loc[0, "esg_total"])        # 公告前拿不到
    assert out.loc[1, "esg_total"] == 61.2 and out.loc[2, "esg_total"] == 61.2
    static = asof_merge(panel, esg, ["esg_total"], static=True)
    assert static["esg_total"].notna().all()         # 對照組：全部回填


def _demo():
    return store.load_dataset("demo", "sample_1y")


def test_future_prices_do_not_change_past_decisions():
    """把某天之後的價格全部改掉，在那之前的選股必須完全不變。"""
    ds = _demo()
    p = Params(top_n=3, n_estimators=30)
    base = run(ds, p)
    cut = base.rebalance_dates[2]
    shocked = ds.prices.copy()
    after = shocked["date"] > cut
    rng = np.random.default_rng(0)
    shocked.loc[after, "close"] *= rng.uniform(0.5, 1.5, after.sum())
    ds2 = store.Dataset(ds.mode, shocked, ds.benchmarks, ds.esg, ds.financials, ds.listing, [])
    alt = run(ds2, p)
    h1 = base.holdings[base.holdings["date"] <= cut].reset_index(drop=True)
    h2 = alt.holdings[alt.holdings["date"] <= cut].reset_index(drop=True)
    pd.testing.assert_frame_equal(h1, h2)


def test_training_window_ends_before_rebalance():
    ds = _demo()
    r = run(ds, Params(top_n=3, n_estimators=20))
    days = pd.DatetimeIndex(sorted(ds.prices["date"].unique()))
    for _, row in r.train_log.iterrows():
        pos = days.get_loc(row["rebalance_date"])
        assert days.get_loc(row["train_end"]) == pos - r.params.hold_days


# ------------------------------------------------------------------ 回測引擎
def test_simulate_returns_start_next_day_and_costs():
    days = pd.bdate_range("2026-01-01", periods=4)
    ret = pd.DataFrame({"A": [0.5, 0.10, 0.0, 0.0], "B": [0.5, 0.0, 0.0, 0.0]}, index=days)
    targets = {days[0]: pd.Series({"A": 0.5, "B": 0.5})}
    sim = bt.simulate(targets, ret)
    # 第一天：當天報酬不算（收盤才買），只扣買進手續費
    assert abs(sim.loc[0, "ret"] - (-config.COMMISSION)) < 1e-12
    # 第二天：A 漲 10%，半倉 → +5%
    assert abs(sim.loc[1, "ret"] - 0.05) < 1e-12


def test_trading_cost_sell_side_has_tax():
    old, new = pd.Series({"A": 1.0}), pd.Series({"B": 1.0})
    c = bt.trading_cost(old, new)
    assert abs(c - (config.COMMISSION + config.COMMISSION + config.SELL_TAX)) < 1e-12


def test_weights_sum_to_one():
    s = pd.Series(np.arange(30, dtype=float), index=[f"T{i}" for i in range(30)])
    for scheme in ("等權", "集中加權"):
        for n in (3, 20, 25):
            w = bt.make_weights(s, n, scheme)
            assert len(w) == n and abs(w.sum() - 1) < 1e-12
    assert bt.make_weights(s, 20, "集中加權").iloc[0] == 0.30


def test_strategies_share_same_period():
    r = run(_demo(), Params(top_n=3, n_estimators=20))
    starts = r.returns.groupby("portfolio")["date"].min()
    assert starts.nunique() == 1


def test_real_mode_with_tej_partial_history(tmp_path=None):
    """真實模式：價格涵蓋 TEJ 公告日前後，公告前 ESG 策略應持有現金、公告後才有持股。"""
    import tempfile
    tmp = Path(tmp_path or tempfile.mkdtemp())
    demo = local_loader.load_folder(config.DEMO_DIR / "sample_1y")
    shift = pd.DateOffset(months=5)
    px_ = demo["prices"].assign(date=lambda d: d["date"] + shift, source="yahoo")
    bm = demo["benchmarks"].assign(date=lambda d: d["date"] + shift, source="yahoo")
    old = (config.PRICES_FILE, config.BENCH_FILE, config.VALUATION_FILE, config.LISTING_FILE, config.LOCAL_DIR,
           config.TEJ_DIR)
    try:
        (tmp / "tej").mkdir(exist_ok=True)
        (tmp / "tej" / TEJ_2026.name).write_bytes(TEJ_2026.read_bytes())   # 只放一期，模擬歷史不足
        config.TEJ_DIR = tmp / "tej"
        config.PRICES_FILE, config.BENCH_FILE = tmp / "prices.csv", tmp / "bench.csv"
        config.VALUATION_FILE, config.LISTING_FILE, config.LOCAL_DIR = tmp / "v.csv", tmp / "l.csv", tmp / "local"
        px_.to_csv(config.PRICES_FILE, index=False)
        bm.to_csv(config.BENCH_FILE, index=False)
        ds = store.load_dataset("real")
        r = run(ds, Params(top_n=3, n_estimators=20))
        esg_h = r.holdings[r.holdings["portfolio"] == bt.STRATEGY_ESG]
        assert esg_h["date"].min() >= pd.Timestamp("2026-05-04")
        assert any("ESG 資料最早從 2026-05-04" in n for n in r.notes)
        assert r.returns.groupby("portfolio")["date"].min().nunique() == 1
        # 對照組：回填後每一期都有 ESG 持股
        r2 = run(ds, Params(top_n=3, n_estimators=20, static_esg=True))
        assert r2.holdings[r2.holdings["portfolio"] == bt.STRATEGY_ESG]["date"].min() < pd.Timestamp("2026-05-04")
    finally:
        (config.PRICES_FILE, config.BENCH_FILE, config.VALUATION_FILE, config.LISTING_FILE, config.LOCAL_DIR,
         config.TEJ_DIR) = old


# ------------------------------------------------------------------ 風險控制、法人、自動更新
def _series_prices(close, ticker="AAA", start="2024-01-01"):
    days = pd.bdate_range(start, periods=len(close))
    return pd.DataFrame({"date": days, "ticker": ticker, "close": close})


def test_stock_trend_and_volatility_filters():
    from src.features import add_technical
    down = add_technical(_series_prices(np.linspace(100, 60, 260)), hold_days=5).iloc[-1]
    up = add_technical(_series_prices(np.linspace(60, 100, 260)), hold_days=5).iloc[-1]
    assert down["above_ma_long"] == 0 and up["above_ma_long"] == 1
    young = add_technical(_series_prices(np.linspace(60, 100, 100)), hold_days=5).iloc[-1]
    assert np.isnan(young["above_ma_long"])                  # 上市不滿 150 天 → 無法判斷，不排除
    snap = pd.DataFrame({"ticker": list("ABCDEFGHIJ"), "above_ma_long": [0.0] + [1.0] * 8 + [np.nan],
                         "vol_60": [0.1, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.9, 0.2]}).set_index("ticker")
    kept = bt.apply_risk_filters(snap)
    assert "A" not in kept.index                              # 跌破年線
    assert "I" not in kept.index                              # 波動最高的 20%
    assert "J" in kept.index                                  # 年線缺資料不排除


def test_market_regime_halves_exposure_without_lookahead():
    days = pd.bdate_range("2026-01-01", periods=6)
    ret = pd.DataFrame({"A": [0.0, 0.01, -0.02, 0.01, 0.0, 0.0]}, index=days)
    regime = pd.Series([1.0, 1.0, 0.5, 0.5, 1.0, 1.0], index=days)   # 第 3 天收盤跌破年線
    sim = bt.simulate({days[0]: pd.Series({"A": 1.0})}, ret, bt.RiskControl(market_exposure=regime))
    assert list(sim["exposure"].round(1)) == [1.0, 1.0, 0.5, 0.5, 1.0, 1.0]   # 中間會隨股價小幅漂移
    # 第 3 天的報酬仍以滿倉計算（收盤後才減碼，不能事先知道），再扣賣出一半的成本
    assert abs(sim.loc[2, "ret"] - ((1 - 0.02) * (1 - 0.5 * (config.COMMISSION + config.SELL_TAX)) - 1)) < 1e-3
    # 年線判斷只用到當天以前的資料
    bench = pd.DataFrame({"date": pd.bdate_range("2025-01-01", periods=260), "ticker": "^TWII",
                          "close": 100 * np.cumprod(1 + np.random.default_rng(1).normal(0, 0.01, 260))})
    r1 = bt.market_regime(bench)
    bench2 = bench.copy()
    bench2.loc[bench2.index[-1], "close"] *= 0.5
    r2 = bt.market_regime(bench2)
    assert r1.iloc[:-1].equals(r2.iloc[:-1])


def test_parse_t86():
    fields = ["證券代號", "證券名稱", "外陸資買賣超股數(不含外資自營商)", "外資自營商買賣超股數",
              "投信買賣超股數", "自營商買賣超股數", "自營商買賣超股數(自行買賣)", "三大法人買賣超股數"]
    payload = {"stat": "OK", "fields": fields,
               "data": [["2330", "台積電", "6,000", "100", "300", "-50", "-20", "6,350"],
                        ["00878", "國泰永續高股息", "1", "0", "0", "0", "0", "1"]]}
    f = twse.parse_t86(payload, "2026-09-18")
    assert list(f["ticker"]) == ["2330.TW"]
    assert f.iloc[0]["foreign_net"] == 6100 and f.iloc[0]["trust_net"] == 300 and f.iloc[0]["dealer_net"] == -50
    assert twse.parse_t86({"stat": "很抱歉，沒有符合條件的資料!"}, "2026-09-19").empty


def test_last_close_date_and_consecutive_day_updates():
    from datetime import datetime, timedelta, timezone
    tz = timezone(timedelta(hours=8))
    assert store.last_close_date(datetime(2026, 9, 28, 10, 0, tzinfo=tz)) == pd.Timestamp("2026-09-25")  # 週一盤中
    assert store.last_close_date(datetime(2026, 9, 28, 15, 0, tzinfo=tz)) == pd.Timestamp("2026-09-28")  # 週一收盤後
    assert store.last_close_date(datetime(2026, 9, 27, 12, 0, tzinfo=tz)) == pd.Timestamp("2026-09-25")  # 週日
    # 舊版的 bug：資料到 9/28、目標 9/29 時會被當成「已是最新」而不抓
    have = pd.DataFrame({"date": pd.bdate_range("2026-06-01", "2026-09-28"), "ticker": "AAA"})
    plan = store.plan_fetch(have, ["AAA"], "2026-06-01", "2026-09-29")
    assert sum(len(v) for v in plan.values()) == 1
    assert store.plan_fetch(have, ["AAA"], "2026-06-01", "2026-09-28") == {}


def test_risk_control_in_pipeline():
    ds = _demo()
    on = run(ds, Params(top_n=3, n_estimators=20, risk_control=True))
    off = run(ds, Params(top_n=3, n_estimators=20, risk_control=False))
    assert bt.STRATEGY_AI in set(on.returns["portfolio"])
    assert not on.risk_log.empty and on.risk_log["exposure"].between(0, 1 + 1e-9).all()
    assert off.risk_log["exposure"].round(6).isin([0.0, 1.0]).all()     # 關閉時永遠滿倉（或空手）


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS", name)
            except Exception as e:  # noqa: BLE001
                failed += 1
                print("FAIL", name, "→", repr(e))
    print("\n全部通過" if not failed else f"\n{failed} 個失敗")
    sys.exit(1 if failed else 0)


def test_capm_alpha_beta():
    idx = pd.bdate_range("2024-01-01", periods=300)
    rng = np.random.default_rng(0)
    m = pd.Series(rng.normal(0.001, 0.01, len(idx)), index=idx)
    port = 2 * m                                    # 純粹放大大盤 2 倍 → beta 2
    out = metrics.capm(port, m, rf=0.0)
    assert abs(out["beta"] - 2) < 1e-9
    same = metrics.capm(m, m, rf=0.01)
    assert abs(same["beta"] - 1) < 1e-9 and abs(same["jensen_alpha"]) < 1e-9
    panel = pd.concat([pd.DataFrame({"date": idx, "portfolio": "^TWII", "ret": m.values}),
                       pd.DataFrame({"date": idx, "portfolio": "X", "ret": (m + 0.0005).values})])
    tbl = metrics.performance_table(panel).set_index("portfolio")
    assert tbl.loc["X", "jensen_alpha"] > 0 and abs(tbl.loc["^TWII", "jensen_alpha"]) < 1e-9


def test_parse_trading_value():
    twse_payload = {"tables": [{"fields": ["證券代號", "證券名稱", "成交股數", "成交金額"],
                                "data": [["2330", "台積電", "1,000", "2,500,000"], ["00400A", "ETF", "1", "9,999,999"]]}]}
    tpex_payload = {"tables": [{"fields": ["代號", "名稱", "收盤", "成交金額(元)"],
                                "data": [["8299", "群聯", "2,000", "1,234"]]}]}
    a = twse.parse_trading_value(twse_payload, pd.Timestamp("2026-09-18"), ".TW")
    b = twse.parse_trading_value(tpex_payload, pd.Timestamp("2026-09-18"), ".TWO")
    assert a["ticker"].tolist() == ["2330.TW"] and a["trade_value"].iloc[0] == 2_500_000
    assert b["ticker"].tolist() == ["8299.TWO"] and b["trade_value"].iloc[0] == 1234


def test_peak_features():
    from src.features import add_technical
    idx = pd.bdate_range("2024-01-01", periods=80)
    close = list(np.linspace(10, 30, 60)) + [29, 28, 27, 26, 27, 28, 27, 26, 25, 24, 23, 22, 21, 20, 19, 18, 17, 16, 15, 14]
    df = add_technical(pd.DataFrame({"date": idx, "ticker": "A", "close": close, "volume": 1000.0}), 5)
    last = df.iloc[-1]
    assert last["days_since_high20"] == 19                 # 近 20 日高點（29 元）在 19 天前
    assert abs(last["dd_high20"] - (14 / 29 - 1)) < 1e-9
    assert last["down_streak"] == 14                        # 最後 14 天連跌
    assert abs(last["vol_ratio"] - 1) < 1e-9                # 量能不變 → 1
    assert df.iloc[59]["dd_high20"] == 0 and df.iloc[59]["days_since_high20"] == 0


def test_industry_cap():
    s = pd.Series({"A": 5.0, "B": 4.0, "C": 3.0, "D": 2.0, "E": 1.0})
    ind = {"A": "半導體", "B": "半導體", "C": "半導體", "D": "金融"}
    top = bt.pick_top(s, 3, ind, max_per_industry=2)
    assert list(top.index) == ["A", "B", "D"]               # C 超過半導體上限被跳過
    assert list(bt.pick_top(s, 3).index) == ["A", "B", "C"]  # 不限制時照分數


def test_holding_forecast():
    from src import forecast
    days = pd.bdate_range("2026-01-01", periods=120)
    d = days[100]
    rets = []
    for name, r in [("單純 AI", 0.002), ("^TWII", 0.001)]:
        rets.append(pd.DataFrame({"date": days, "portfolio": name,
                                  "ret": r + 0.01 * np.sin(np.arange(len(days)))}))
    returns = pd.concat(rets, ignore_index=True)
    hold = pd.DataFrame({"ticker": ["A", "B"], "weight": [0.5, 0.5]})
    ev = pd.DataFrame({"date": d, "ticker": ["A", "B", "C"], "pred": [0.04, 0.02, -0.5]})
    bench = pd.DataFrame({"date": days, "ticker": "^TWII", "close": 100 * (1.001 ** np.arange(len(days)))})
    w = forecast.holding_window([days[90], d, days[110]], days[-1], d, days, 10)
    assert list(w) == list(days[101:111])                       # 到下一個調倉日為止
    fc = forecast.holding_forecast(hold, ev, returns, bench, "單純 AI", d, w, 10)
    p = fc["path"]
    assert abs(fc["excess"] - 0.03) < 1e-12                     # 只用持股 A、B 的預測
    assert abs(p["expected"].iloc[-1] - ((1.001) ** 10 - 1 + 0.03)) < 1e-6
    assert (p["hi95"] >= p["hi68"]).all() and (p["lo95"] <= p["lo68"]).all()
    assert p["actual"].notna().all() and p["actual"].iloc[0] == 0
    # 最後一期沒有未來資料 → 補成平日，實際走勢為空
    w2 = forecast.holding_window([d], days[-1], days[-1], days, 10)
    assert len(w2) == 10 and w2[0] > days[-1]
