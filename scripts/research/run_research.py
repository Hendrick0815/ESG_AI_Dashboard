"""論文正式結果產生器：依 research_config.json 重跑回測並輸出表 3-x、表 4-1～4-10 與所有中間檔。

執行（在專案根目錄）：
    python scripts/research/run_research.py                 # 正式版本（設定檔中的 run_id）
    python scripts/research/run_research.py --skip-long     # 略過 2019 年起的長期間對照（較快）
輸出：outputs/research/<run_id>/
    manifest.json            版本紀錄（設定、資料檔 SHA-256、程式檔 SHA-256、Python 與套件版本、執行時間）
    strategy_returns.csv     每日策略與比較基準報酬
    holdings.csv             每次調倉持股（含分數）       latest_picks.csv   資料截點最後一天的選股
    trades.csv               換股與成本                   evaluation.csv     每期預測 vs 實際報酬
    train_log.csv            每次訓練的樣本數、截止日      importance_by_training.csv 每次訓練的特徵重要性
    universe_history.csv     逐期股票池（調倉日、股票、排名、20 日均成交金額）
    universe_summary.csv     各調倉日掛牌數、入選數、之後下市檔數
    availability_checks.csv  資料可得日檢查表               manual_checks.csv  人工核對範例
    price_validation.csv     交易所報酬 vs Yahoo 還原報酬比對
    tables/*.csv             論文各表
"""
from __future__ import annotations

import argparse, hashlib, json, platform, subprocess, sys, time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src import backtest as bt, config, pipeline                     # noqa: E402
from src.metrics import performance_table                           # noqa: E402
from src.research import analysis as an, exchange as ex, stats as rs  # noqa: E402
from src.store import Dataset, load_dataset                          # noqa: E402

LABEL = {"單純 AI": "單純 AI", "AI+ESG": "AI+ESG", "單純 ESG": "規則式 ESG 篩選", "^TWII": "加權指數",
         "0050.TW": "0050", "00850.TW": "00850", "00878.TW": "00878"}
ORDER = ["單純 AI", "AI+ESG", "規則式 ESG 篩選", "0050", "00850", "00878", "加權指數"]
STRATS = ["單純 AI", "AI+ESG", "規則式 ESG 篩選"]


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def apply_config(cfg: dict) -> None:
    config.HOLD_DAYS = cfg["hold_days"]
    config.REBALANCE_MODE = cfg.get("rebalance_mode", "trading_days")   # 論文鎖定：每 hold_days 個交易日調倉
    config.RETRAIN_EVERY = cfg["retrain_every_rebalances"]
    config.USE_PEAK_FEATURES = cfg["use_peak_features"]
    config.USE_INDUSTRY_FEATURES = cfg["use_industry_features"]
    config.MAX_PER_INDUSTRY = cfg["max_per_industry"]
    config.INDUSTRY_TREND_WEIGHT = cfg["industry_trend_weight"]
    config.COMMISSION = cfg["costs"]["commission"]
    config.SELL_TAX = cfg["costs"]["sell_tax"]
    config.SLIPPAGE = cfg["costs"]["slippage_per_side"]
    config.RISK_FREE_RATE = cfg["risk_free_annual"]
    config.BACKTEST_START = cfg["backtest_start"]
    config.BENCHMARKS = cfg["benchmarks"]
    np.random.seed(cfg["random_seed"])


def yahoo_as_quotes(base, cut):
    """對照組：用平台的 Yahoo 股價（只有「目前」成交金額前 300 大）當股票池，用來衡量股票池後見之明偏誤的影響。"""
    y = base.prices[base.prices["date"] <= cut].sort_values(["ticker", "date"]).copy()
    y["ret"] = y.groupby("ticker")["close"].pct_change()
    y["value"] = y["close"] * y["volume"]
    y["raw_close"] = y["close"]; y["market"] = np.where(y["ticker"].str.endswith(".TWO"), "TPEx", "TWSE"); y["name"] = y["ticker"]
    q = y.assign(code=y["ticker"].str[:4])
    return q, y[["date", "ticker", "raw_close", "volume", "value", "market", "name", "ret", "close"]]


def build_dataset(cfg: dict, out: Path, test_yahoo: bool = False):
    cut = pd.Timestamp(cfg["data_cutoff"])
    t0 = time.time()
    if test_yahoo:
        q, px = yahoo_as_quotes(load_dataset("real"), cut)
    else:
        q = ex.load_quotes(end=cut)
        days_tp = q.loc[q["market"] == "TPEx", "date"].nunique()
        days_tw = q.loc[q["market"] == "TWSE", "date"].nunique()
        fm = ex.load_finmind_twse(end=cut)
        if days_tw >= 0.98 * days_tp:          # 證交所逐日全市場行情齊全
            px = ex.build_prices(q)
            source = "證交所 MI_INDEX＋櫃買中心 dailyQuotes（逐日全市場）"
        else:                                   # 上市：Yahoo（現存）＋ FinMind（已下市）；上櫃：櫃買中心逐日行情
            ya = ex.load_yahoo_all(end=cut)
            px = ex.build_prices_hybrid(q, fm, ya)
            n_fm = len(set(fm["ticker"]) - set(ya["ticker"])) if len(fm) else 0
            source = (f"上市：Yahoo Finance 逐檔日資料（{ya['ticker'].nunique()} 檔現存股票）＋ FinMind 逐檔行情（{n_fm} 檔 Yahoo 未收錄、多為已下市）；"
                      f"上櫃：櫃買中心 dailyQuotes 逐日全市場行情")
        base0 = load_dataset("real")
        px = ex.apply_yahoo_returns(px, base0.prices[base0.prices["date"] <= cut])
        share = (px["ret_source"] == "Yahoo").mean()
        source += f"；現存 300 檔的日報酬改用 Yahoo 還原收盤價（占全部股票日資料 {share:.0%}），其餘股票（含已下市）用漲跌價差法"
        print("價格來源：", source, flush=True)
        (out / "price_source.txt").write_text(source, encoding="utf-8")
    u = cfg["universe"]
    elig = ex.eligibility(px, u["size"], u["window_days"], u["min_trading_days"])
    print(f"行情 {px['date'].nunique()} 天、{px['ticker'].nunique()} 檔；股票池建立 {time.time()-t0:.0f}s", flush=True)
    ever = set(elig["ticker"])
    base = load_dataset("real")
    names = q.drop_duplicates("ticker", keep="last").set_index("ticker")["name"]
    listing = base.listing.copy()
    extra = pd.DataFrame({"ticker": sorted(ever - set(listing["ticker"]))})
    if len(extra):
        extra["code"] = extra["ticker"].str[:4]
        extra["name"] = extra["ticker"].map(names)
        extra["market"] = np.where(extra["ticker"].str.endswith(".TWO"), "上櫃", "上市")
        extra["industry"] = None
        listing = pd.concat([listing, extra], ignore_index=True)
    bench = base.benchmarks[base.benchmarks["date"] <= cut]
    esg = base.esg[base.esg["available_date"] <= cut]
    fin = base.financials[base.financials["available_date"] <= cut]
    prices = px[px["ticker"].isin(ever)][["date", "ticker", "close", "volume"]].copy()
    ds = Dataset(mode="research", prices=prices, benchmarks=bench, esg=esg, financials=fin,
                 listing=listing, notes=[], eligible=elig[["date", "ticker"]])
    return ds, px, elig, base


def validate_prices(px: pd.DataFrame, base) -> pd.DataFrame:
    """交易所含權息報酬 vs Yahoo 還原收盤價報酬（重疊的股票與日期）。"""
    y = base.prices[["date", "ticker", "close"]].sort_values(["ticker", "date"]).copy()
    y["ry"] = y.groupby("ticker")["close"].pct_change()
    m = px[["date", "ticker", "ret"]].merge(y[["date", "ticker", "ry"]], on=["date", "ticker"]).dropna()
    rows = []
    for t, g in m.groupby("ticker"):
        if len(g) < 250:
            continue
        rows.append({"ticker": t, "n_days": len(g), "corr": g["ret"].corr(g["ry"]),
                     "mean_abs_diff": (g["ret"] - g["ry"]).abs().mean(),
                     "ann_ret_exchange": (1 + g["ret"]).prod() ** (252 / len(g)) - 1,
                     "ann_ret_yahoo": (1 + g["ry"]).prod() ** (252 / len(g)) - 1})
    return pd.DataFrame(rows)


def ret_wide_of(res, start, end) -> pd.DataFrame:
    r = res.returns.copy()
    r["portfolio"] = r["portfolio"].map(LABEL).fillna(r["portfolio"])
    w = r.pivot_table(index="date", columns="portfolio", values="ret").sort_index()
    w = w[(w.index >= pd.Timestamp(start)) & (w.index <= pd.Timestamp(end))]
    return w[[c for c in ORDER if c in w.columns]]


def resimulate(res, ret_daily: pd.DataFrame, slippage: float) -> pd.DataFrame:
    """用同一組持股（不重新訓練）在不同滑價下重算三個策略的日報酬。"""
    old = config.SLIPPAGE
    config.SLIPPAGE = slippage
    out = {}
    h = res.holdings[res.holdings["date"].isin(res.rebalance_dates)]
    for strat, g in h.groupby("portfolio"):
        targets = {d: x.set_index("ticker")["weight"] for d, x in g.groupby("date")}
        for d in res.rebalance_dates:
            targets.setdefault(d, pd.Series(dtype=float))
        sim = bt.simulate(dict(sorted(targets.items())), ret_daily)
        out[LABEL.get(strat, strat)] = sim.set_index("date")["ret"]
    config.SLIPPAGE = old
    return pd.DataFrame(out)


def main():
    import os
    os.environ["ESG_KEEP_PANEL"] = "1"
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(ROOT / "research_config.json"))
    ap.add_argument("--skip-long", action="store_true")
    ap.add_argument("--test-yahoo", action="store_true",
                    help="對照組：股票池改用平台「目前」成交金額前 300 大的 Yahoo 股價（有後見之明偏誤），輸出到 <run_id>_current_universe")
    a = ap.parse_args()
    cfg = json.loads(Path(a.config).read_text(encoding="utf-8"))
    apply_config(cfg)
    out = ROOT / "outputs" / "research" / (cfg["run_id"] + ("_current_universe" if a.test_yahoo else ""))
    tdir = out / "tables"
    tdir.mkdir(parents=True, exist_ok=True)
    started = datetime.now().isoformat(timespec="seconds")
    cut = pd.Timestamp(cfg["data_cutoff"])

    ds, px, elig, base = build_dataset(cfg, out, a.test_yahoo)
    pxv = px.assign(ret=px["ret_ex"]) if "ret_ex" in px else px
    if (pxv["market"] == "TWSE").any() and "Yahoo Finance 逐檔" in (out / "price_source.txt").read_text(encoding="utf-8") if (out / "price_source.txt").exists() else False:
        pxv = pxv[pxv["market"] == "TPEx"]          # 上市已直接使用 Yahoo，只驗證上櫃的交易所報酬
    pv = validate_prices(pxv, base)
    pv.to_csv(out / "price_validation.csv", index=False)

    p = pipeline.Params(model_name=cfg["model"], top_n=cfg["top_n"], n_estimators=cfg["n_estimators"],
                        esg_weight=cfg["esg_weight"], weighting=cfg["weighting"], risk_control=cfg["risk_control"],
                        start=cfg["history_start"], end=cfg["data_cutoff"])
    t0 = time.time()
    res = pipeline.run(ds, p, progress=lambda k, n, d: print(f"  訓練/預測 {k+1}/{n} {pd.Timestamp(d).date()}", flush=True) if k % 20 == 0 else None)
    print(f"正式回測完成 {time.time()-t0:.0f}s", flush=True)

    # ---------------- 中間檔
    lab = lambda df: df.assign(portfolio=df["portfolio"].map(LABEL).fillna(df["portfolio"]))
    lab(res.returns).to_csv(out / "strategy_returns.csv", index=False)
    perf = performance_table(res.returns)
    lab(perf).to_csv(out / "performance.csv", index=False)
    lab(res.holdings[res.holdings["date"].isin(res.rebalance_dates)]).to_csv(out / "holdings.csv", index=False)
    lab(res.latest).to_csv(out / "latest_picks.csv", index=False)
    lab(res.trades).to_csv(out / "trades.csv", index=False)
    res.evaluation.to_csv(out / "evaluation.csv", index=False)
    tl = res.train_log.copy()
    imp_rows = [dict(rebalance_date=r["rebalance_date"], feature=f, importance=v)
                for _, r in tl.iterrows() for f, v in (r.get("importances") or {}).items()]
    imp = pd.DataFrame(imp_rows)
    imp.to_csv(out / "importance_by_training.csv", index=False)
    tl.drop(columns=["importances"], errors="ignore").to_csv(out / "train_log.csv", index=False)
    rb = pd.DatetimeIndex(res.rebalance_dates)
    uh = elig[elig["date"].isin(rb)].merge(px[["date", "ticker", "name", "market"]], on=["date", "ticker"], how="left")
    uh.to_csv(out / "universe_history.csv", index=False)
    us = ex.universe_summary(px, elig, rb)
    us.to_csv(out / "universe_summary.csv", index=False)
    us.describe().to_csv(tdir / "table_3_3_universe_summary.csv")
    trials = ROOT / "docs" / "parameter_trials.csv"
    if trials.exists():
        pd.read_csv(trials).to_csv(tdir / "table_3_8_parameter_trials.csv", index=False)

    # ---------------- 資料可得日檢查
    hold = res.holdings[res.holdings["date"].isin(rb)]
    chk = []
    esg = ds.esg
    for d in rb:
        e_used = esg[esg["available_date"] <= d]
        h = hold[hold["date"] == d]
        chk.append({"rebalance_date": d.date(),
                    "price_last_date_used": d.date(),
                    "universe_window": f"{elig[elig['date']==d]['n_days'].max():.0f} 個交易日（含當天）",
                    "esg_latest_announce_used": e_used["available_date"].max().date() if len(e_used) else None,
                    "valuation_latest_used": ds.financials[ds.financials["available_date"] <= d]["available_date"].max().date()
                    if len(ds.financials) else None,
                    "holdings_in_universe": int(h["ticker"].isin(elig[elig["date"] == d]["ticker"]).sum()),
                    "holdings_total": int(len(h))})
    chk = pd.DataFrame(chk)
    # 規則式 ESG 篩選的分數 = 當天以前已公告的最新 TESG；逐筆核對是否用到未來公告的評等
    he = hold[hold["portfolio"] == "單純 ESG"]
    bad = 0
    for d, g in he.groupby("date"):
        e_ok = esg[esg["available_date"] <= d].sort_values("available_date").drop_duplicates("ticker", keep="last").set_index("ticker")["esg_total"]
        bad += int((~np.isclose(g.set_index("ticker")["score"], e_ok.reindex(g["ticker"]).values)).sum())
    chk["esg_score_mismatch_total"] = bad
    chk.to_csv(out / "availability_checks.csv", index=False)
    # 人工核對範例：3 個調倉日的單純 AI 前 5 檔
    ex_dates = [rb[0], rb[len(rb) // 2], rb[-1]]
    mc = []
    for d in ex_dates:
        h = hold[(hold["date"] == d) & (hold["portfolio"] == "單純 AI")].sort_values("score", ascending=False).head(5)
        e_used = esg[esg["available_date"] <= d].sort_values("available_date").drop_duplicates("ticker", keep="last").set_index("ticker")
        for _, r in h.iterrows():
            u = elig[(elig["date"] == d) & (elig["ticker"] == r["ticker"])]
            mc.append({"rebalance_date": d.date(), "ticker": r["ticker"], "name": ds.names.get(r["ticker"]),
                       "ai_score": r["score"], "universe_rank": int(u["rank"].iloc[0]) if len(u) else None,
                       "avg_value_20d_億": float(u["avg_value"].iloc[0]) / 1e8 if len(u) else None,
                       "esg_period": e_used["period"].get(r["ticker"]), "esg_announce": e_used["available_date"].get(r["ticker"]),
                       "esg_total": e_used["esg_total"].get(r["ticker"])})
    pd.DataFrame(mc).to_csv(out / "manual_checks.csv", index=False)

    # ---------------- 表格
    start = res.test_start
    W = ret_wide_of(res, start, cut)
    mkt = W["加權指數"]
    # 表 4-1 績效＋CAPM（HAC）＋報酬 bootstrap CI
    t41 = []
    for c in W.columns:
        r = W[c].dropna()
        from src.metrics import performance
        m = performance(r, config.RISK_FREE_RATE)
        lo, hi = rs.bootstrap_ci_ann(r)
        row = {"投組": c, "累積報酬": m["cum_return"], "年化報酬": m["ann_return"], "年化報酬95%CI下限": lo,
               "年化報酬95%CI上限": hi, "年化波動": m["ann_vol"], "Sharpe": m["sharpe"], "最大回撤": m["max_drawdown"],
               "交易日數": len(r)}
        if c != "加權指數":
            cp = rs.capm(r, mkt, config.RISK_FREE_RATE)
            row.update({"Beta": cp["beta"], "年化Alpha(CAPM)": cp["alpha_ann"], "R2": cp["r2"]})
        t41.append(row)
    pd.DataFrame(t41).to_csv(tdir / "table_4_1_performance.csv", index=False)
    # 表 4-2 年度
    an.yearly(W).to_csv(tdir / "table_4_2_yearly.csv")
    # 表 4-3 市場情境（事前規則）
    twii = base.benchmarks[base.benchmarks["ticker"] == "^TWII"].set_index("date")["close"].sort_index()
    reg = an.classify_regimes(twii[twii.index <= cut])
    reg.to_csv(out / "regimes.csv", index=False)
    an.regime_table(W, reg).to_csv(tdir / "table_4_3_regimes.csv", index=False)
    # 表 4-4 參與率
    an.capture(W, "加權指數").to_csv(tdir / "table_4_4_capture.csv", index=False)
    # 表 4-5 CAPM（日頻，HAC）
    t45 = []
    for c in STRATS + ["0050", "00850", "00878"]:
        cp = rs.capm(W[c], mkt, config.RISK_FREE_RATE)
        t45.append({"投組": c, **cp})
    t45 = pd.DataFrame(t45)
    t45["alpha_p_holm"] = rs.holm(t45["alpha_p"].tolist())
    t45.to_csv(tdir / "table_4_5_capm_hac.csv", index=False)
    # 表 4-6 差異檢定（策略 − 基準，HAC，Holm）
    t46 = []
    pairs = [(s, b) for s in STRATS for b in ["加權指數", "0050", "00850", "00878"]]
    pairs += [("AI+ESG", "規則式 ESG 篩選"), ("單純 AI", "AI+ESG")]
    for s, b in pairs:
        t46.append({"策略": s, "基準": b, **rs.diff_test(W[s], W[b])})
    t46 = pd.DataFrame(t46)
    t46["p_holm"] = rs.holm(t46["p"].tolist())
    t46.to_csv(tdir / "table_4_6_diff_hac.csv", index=False)
    # 表 4-7 模型能力與特徵重要性分布
    ic = pipeline.rank_ic(res.evaluation)
    ic.to_csv(out / "rank_ic.csv", index=False)
    ich = rs.hac_mean(ic["rank_ic"])
    ev = res.evaluation.dropna(subset=["pred", "fwd_ret"])
    top = []
    for d, g in ev.groupby("date"):
        if len(g) > cfg["top_n"]:
            top.append(g.nlargest(cfg["top_n"], "pred")["fwd_ret"].mean() - g["fwd_ret"].mean())
    toph = rs.hac_mean(pd.Series(top))
    pd.DataFrame([{"指標": "平均 Rank IC", **ich, "positive_share": float((ic["rank_ic"] > 0).mean())},
                  {"指標": f"前 {cfg['top_n']} 檔每期超額報酬（未扣成本）", **toph,
                   "positive_share": float((pd.Series(top) > 0).mean())}]).to_csv(tdir / "table_4_7_model_skill.csv", index=False)
    if len(imp):
        g = imp.groupby("feature")["importance"]
        imp["rank"] = imp.groupby("rebalance_date")["importance"].rank(ascending=False)
        t47 = pd.DataFrame({"mean": g.mean(), "sd": g.std(), "min": g.min(), "max": g.max(),
                            "top3_share": imp.assign(t3=imp["rank"] <= 3).groupby("feature")["t3"].mean(),
                            "n_trainings": g.size()}).sort_values("mean", ascending=False)
        t47.to_csv(tdir / "table_4_8a_importance_distribution.csv")
    # permutation importance：另外訓練一個「評估窗之前」的模型，在之後 12 次已知實際報酬的調倉日上評估
    panel = getattr(res, "panel", None)
    if panel is not None:
        from src.models import Model
        days = pd.DatetimeIndex(sorted(panel["date"].unique()))
        known = [d for d in rb if panel.loc[panel["date"] == d, "fwd_ret"].notna().sum() > 50]
        evd = known[-12:]
        pos = days.get_loc(evd[0])
        train_end = days[pos - cfg["hold_days"]]
        feats = list(res.wf_features)
        samp = set(days[::cfg["train_sample_every_days"]])
        tr = panel[(panel["date"] <= train_end) & panel["date"].isin(samp)].dropna(subset=["fwd_ret"])
        med = tr[feats].median()
        mdl = Model(cfg["model"], cfg["n_estimators"]).fit(tr[feats].fillna(med), tr["fwd_ret"] - tr.groupby("date")["fwd_ret"].transform("mean"))
        V = panel[panel["date"].isin(evd)].dropna(subset=["fwd_ret"])
        X = V[feats].fillna(med)
        y = V["fwd_ret"] - V.groupby("date")["fwd_ret"].transform("mean")
        def ic(Xm):
            pr = pd.Series(mdl.predict(Xm), index=Xm.index)
            return np.nanmean([pr[g.index].rank().corr(y[g.index].rank()) for _, g in V.groupby("date")])
        base_ic = ic(X)
        rng = np.random.default_rng(cfg["random_seed"])
        rows = []
        for f in feats:
            drops = []
            for _ in range(10):
                Xp = X.copy()
                Xp[f] = X.groupby(V["date"])[f].transform(lambda s: s.sample(frac=1, random_state=int(rng.integers(1e9))).values)
                drops.append(base_ic - ic(Xp))
            rows.append({"feature": f, "ic_drop_mean": np.mean(drops), "ic_drop_sd": np.std(drops)})
        pi = pd.DataFrame(rows).sort_values("ic_drop_mean", ascending=False)
        pi["base_ic"] = base_ic
        pi["train_end"] = train_end.date()
        pi["eval_dates"] = f"{evd[0].date()}～{evd[-1].date()}（{len(evd)} 期，{len(V)} 筆）"
        pi.to_csv(tdir / "table_4_8b_permutation_importance.csv", index=False)

    # 表 4-8 成本與滑價敏感度
    tr = res.trades.copy()
    tr["portfolio"] = tr["portfolio"].map(LABEL)
    t48a = tr.groupby("portfolio").agg(rebalances=("date", "nunique"), avg_turnover=("turnover", "mean"),
                                       total_cost=("cost", "sum")).reset_index()
    t48a.to_csv(tdir / "table_4_9a_turnover_cost.csv", index=False)
    full_ret = ds.prices.sort_values(["ticker", "date"]).copy()
    full_ret["r"] = full_ret.groupby("ticker")["close"].pct_change()
    ret_daily = full_ret.pivot_table(index="date", columns="ticker", values="r").sort_index()
    sens = []
    for s in cfg["slippage_grid"]:
        R = resimulate(res, ret_daily, s)
        R = R[(R.index >= start) & (R.index <= cut)]
        for c in R.columns:
            from src.metrics import performance
            m = performance(R[c], config.RISK_FREE_RATE)
            d = rs.diff_test(R[c], W["00850"].reindex(R.index))
            sens.append({"slippage_bps": round(s * 1e4), "投組": c, "年化報酬": m["ann_return"], "Sharpe": m["sharpe"],
                         "相對00850年化差": d["ann_diff"], "相對00850_HAC_t": d["t"]})
    pd.DataFrame(sens).to_csv(tdir / "table_4_9b_slippage.csv", index=False)
    # 存活者偏誤檢查：持股中「不在平台目前 300 檔名單」的股票，其持有期報酬與其他持股比較
    cur = set(base.prices["ticker"])
    hp = []
    rbl = list(rb)
    for i, d in enumerate(rbl):
        e = rbl[i + 1] if i + 1 < len(rbl) else ret_daily.index[-1]
        seg = ret_daily[(ret_daily.index > d) & (ret_daily.index <= e)]
        for _, r in hold[hold["date"] == d].iterrows():
            x = seg[r["ticker"]] if r["ticker"] in seg.columns else pd.Series(dtype=float)
            hp.append({"date": d, "portfolio": LABEL.get(r["portfolio"], r["portfolio"]), "ticker": r["ticker"],
                       "period_ret": float((1 + x.fillna(0)).prod() - 1), "in_current_top300": r["ticker"] in cur})
    hp = pd.DataFrame(hp)
    hp.to_csv(out / "holding_period_returns.csv", index=False)
    hp.groupby(["portfolio", "in_current_top300"])["period_ret"].agg(["count", "mean", "median"]).to_csv(tdir / "table_4_2b_survivorship_split.csv")
    # 表 4-9 投組 ESG 品質
    uni = elig[elig["date"].isin(rb)][["date", "ticker"]]
    epit = an.esg_asof(ds.esg, list(rb))
    hq = lab(hold)
    q = an.esg_quality(hq, epit, uni, ds.industries)
    q = q[q["date"] >= start]
    q.to_csv(out / "esg_quality_by_rebalance.csv", index=False)
    agg = q.groupby("portfolio")[["n", "esg_coverage", "esg_total", "e_score", "s_score", "g_score", "event_score",
                                   "low_esg_share", "industry_hhi", "top_industry_share"]].mean()
    agg.to_csv(tdir / "table_4_10_esg_quality.csv")
    # 長期間對照（開發／驗證／探索性評估）
    if not a.skip_long:
        config.BACKTEST_START = cfg["long_backtest_start"]
        t0 = time.time()
        res_l = pipeline.run(ds, p)
        print(f"長期間回測完成 {time.time()-t0:.0f}s", flush=True)
        WL = ret_wide_of(res_l, res_l.test_start, cut)
        lab(res_l.returns).to_csv(out / "strategy_returns_long.csv", index=False)
        rows = []
        for name, (s0, s1) in cfg["periods"].items():
            s1 = s1 or cfg["data_cutoff"]
            seg = WL[(WL.index >= pd.Timestamp(s0)) & (WL.index <= pd.Timestamp(s1))]
            for c in seg.columns:
                x = seg[c].dropna()
                if len(x) < 20:
                    continue
                rows.append({"period": name, "start": x.index.min().date(), "end": x.index.max().date(), "投組": c,
                             "days": len(x), "ann_return": (1 + x).prod() ** (252 / len(x)) - 1,
                             "ann_vol": x.std() * np.sqrt(252)})
        pd.DataFrame(rows).to_csv(tdir / "table_3_7_period_split.csv", index=False)
        config.BACKTEST_START = cfg["backtest_start"]

    # ---------------- 版本紀錄
    files = {}
    for f in sorted((ROOT / "data" / "raw" / "tej").glob("*.csv")) + [config.BENCH_FILE, config.VALUATION_FILE, config.LISTING_FILE]:
        files[str(f.relative_to(ROOT))] = sha256(f)
    qfiles = sorted((ROOT / "data" / "raw" / "daily_quotes").glob("*.csv")) + sorted((ROOT / "data" / "raw" / "daily_quotes_twse").glob("*.gz"))
    hq_ = hashlib.sha256()
    for f in qfiles:
        hq_.update(f.name.encode()); hq_.update(sha256(f).encode())
    files["data/raw/daily_quotes*（合計 %d 檔）" % len(qfiles)] = hq_.hexdigest()
    code = {str(f.relative_to(ROOT)): sha256(f) for f in sorted((ROOT / "src").rglob("*.py")) if "__pycache__" not in str(f)}
    code["scripts/research/run_research.py"] = sha256(Path(__file__))
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip() or None
    except Exception:
        commit = None
    import sklearn, scipy, statsmodels
    manifest = {"run_id": cfg["run_id"], "started": started, "finished": datetime.now().isoformat(timespec="seconds"),
                "git_commit": commit, "config": cfg, "python": platform.python_version(),
                "packages": {"pandas": pd.__version__, "numpy": np.__version__, "scikit-learn": sklearn.__version__,
                             "scipy": scipy.__version__, "statsmodels": statsmodels.__version__},
                "data_files_sha256": files, "code_sha256": code,
                "summary": {"rebalances": len(rb), "first_rebalance": str(rb[0].date()), "last_rebalance": str(rb[-1].date()),
                            "trainings": int(len(tl)), "universe_tickers_ever": int(elig["ticker"].nunique())}}
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("完成：", out)


if __name__ == "__main__":
    main()
