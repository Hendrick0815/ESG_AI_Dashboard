"""模型解釋：特徵重要性、Rank IC、訓練紀錄、SHAP。"""
import numpy as np
import pandas as pd
import streamlit as st

from src.features import TECH_LABELS
from src.metrics import fmt_num, fmt_pct
from src.pipeline import rank_ic
from src.ui import charts
from src.ui.common import get_result, metric_cards, require_prices, setup_page, show_notes, sidebar_data, sidebar_strategy
from src.utils import to_csv_bytes

setup_page("模型解釋", "🧠")
ds, mode, demo_set = sidebar_data()
require_prices(ds)
params = sidebar_strategy(ds)
res = get_result(mode, demo_set, params)
if res is None:
    st.stop()

st.title("🧠 模型解釋")
st.caption(f"模型：{params.model_name}｜預測未來 {params.hold_days} 個交易日的相對報酬｜共訓練 {len(res.train_log)} 次")
show_notes([n for n in res.notes if "示範" in n])

ic = rank_ic(res.evaluation)
ev = res.evaluation.dropna(subset=["pred", "fwd_ret"])
cards = [("平均 Rank IC", fmt_num(ic["rank_ic"].mean(), 3) if not ic.empty else "-",
          "預測排名與實際報酬排名的相關；0.03～0.05 就算有用"),
         ("IC > 0 的比例", fmt_pct((ic["rank_ic"] > 0).mean()) if not ic.empty else "-")]
if not ev.empty:
    hits = []
    for _, g in ev.groupby("date"):
        top = g.nlargest(params.top_n, "pred")
        hits.append(top["fwd_ret"].mean() - g["fwd_ret"].mean())
    cards.append((f"Top {params.top_n} 平均超額報酬（每期）", fmt_pct(np.mean(hits)), "前 N 檔比全部股票多賺多少（未扣成本）"))
cards.append(("可評估的調倉次數", f"{ic['date'].nunique() if not ic.empty else 0}"))
metric_cards(cards, min_width=190)

a, b = st.columns(2)
with a:
    if res.importance.empty:
        st.info("沒有特徵重要性（模型未訓練）")
    else:
        imp = res.importance.head(15).copy()
        imp["名稱"] = imp["feature"].map(lambda f: TECH_LABELS.get(f, f))
        st.plotly_chart(charts.bar_h(imp, "importance", "名稱", "特徵重要性（最後一次訓練）"), width="stretch")
with b:
    if not ic.empty:
        st.plotly_chart(charts.rank_ic_chart(ic), width="stretch")

with st.expander("SHAP 分析（需安裝 shap，可能較慢）"):
    try:
        import shap
        if res.model is None or res.last_X is None or res.last_X.empty:
            st.info("沒有可解釋的模型")
        elif st.button("計算 SHAP"):
            X = res.last_X
            vals = np.mean([np.abs(shap.TreeExplainer(m).shap_values(X)) for m in res.model.models], axis=0)
            shap_df = pd.DataFrame({"feature": X.columns, "mean_abs_shap": vals.mean(axis=0)})
            shap_df["名稱"] = shap_df["feature"].map(lambda f: TECH_LABELS.get(f, f))
            st.plotly_chart(charts.bar_h(shap_df.nlargest(15, "mean_abs_shap"), "mean_abs_shap", "名稱",
                                         f"SHAP 平均影響（{res.latest_date:%Y-%m-%d} 的預測）"), width="stretch")
    except ImportError:
        st.caption("尚未安裝 shap（pip install shap）。")

with st.expander("使用的特徵"):
    info = res.panel_info
    rows = [{"特徵": f, "名稱": TECH_LABELS.get(f, f), "類別": k, "AI 模型使用": "是"}
            for k, fs in [("技術面", info["tech_features"]),
                          ("估值／財務", info["fin_features"])] for f in fs]
    rows += [{"特徵": f, "名稱": TECH_LABELS.get(f, f), "類別": "ESG", "AI 模型使用": "否（選股時融合）"}
             for f in info["esg_features"]]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption(f"ESG 資料涵蓋率（回測樣本中有 ESG 分數的比例）：{info['esg_coverage']:.0%}")

with st.expander("訓練紀錄"):
    st.dataframe(res.train_log, hide_index=True, width="stretch")

st.download_button("下載模型預測與實際報酬 CSV", to_csv_bytes(res.evaluation), "model_predictions.csv", "text/csv")
