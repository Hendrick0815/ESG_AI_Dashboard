"""Plotly 圖表（顏色固定跟著「策略/標的」走，不會因為篩選而換色）。"""
from __future__ import annotations

from typing import Dict, Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from ..backtest import STRATEGIES

# 三個策略：實線＋分類色第 1–3 格。比較基準：各自固定的顏色＋不同虛線樣式，
# 顏色和線型同時不同，四條 ETF／指數線即使交錯也分得出來（色盲或黑白列印時靠線型區分）。
STRATEGY_COLORS = {"AI+ESG": "#2a78d6", "單純 AI": "#eb6834", "單純 ESG": "#1baf7a"}
BENCH_STYLES = {
    "^TWII":    ("#3f3e3b", "solid"),      # 加權指數：深灰實線（細），當作大盤參考線
    "0050.TW":  ("#4a3aa7", "dash"),       # 元大台灣50：紫
    "00850.TW": ("#e87ba4", "dashdot"),    # 元大臺灣ESG永續：粉
    "00878.TW": ("#eda100", "dot"),        # 國泰永續高股息：琥珀
    "0056.TW":  ("#008300", "longdash"),
}
BENCH_FALLBACK = [("#8a8984", "dash"), ("#6f6e69", "dot"), ("#a3a29c", "dashdot"), ("#52514e", "longdash")]
BENCH_GRAYS = [c for c, _ in BENCH_FALLBACK]
SERIES_PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
UP, DOWN = "#e34948", "#008300"   # 台股：紅漲綠跌
GRID = "rgba(128,128,128,0.18)"
# 深色主題時，原本偏暗的顏色換成較亮的版本（深灰、深紫在黑底上看不清楚）
DARK_SWAP = {"#3f3e3b": "#d6d5d0", "#4a3aa7": "#a594f9", "#52514e": "#bdbcb6", "#6f6e69": "#a8a7a1",
             "#008300": "#3fbf5f"}


def is_dark() -> bool:
    """目前網頁是否為深色主題（使用者在 ⋮ → Settings 切換，或跟著系統設定）。"""
    try:
        import streamlit as st
        return getattr(st.context.theme, "type", None) == "dark"
    except Exception:
        return False


def _bg() -> str:
    """標記外框用的背景色（跟網頁底色一樣，看起來像留白）。"""
    return "#0F1412" if is_dark() else "white"


def _c(color: str) -> str:
    return DARK_SWAP.get(color, color) if is_dark() else color


def _layout(fig: go.Figure, title: str = "", height: int = 420, y_title: str = "", pct_y: bool = False) -> go.Figure:
    # 圖例放在圖的「下方」：放上方時，圖例一換行就會蓋到標題（視窗窄、線條多時最明顯）。
    # 下方空間由 Plotly 自動撐開（margin.autoexpand），幾行圖例都不會重疊。
    fig.update_layout(
        title=dict(text=title, x=0, xanchor="left", y=1, yanchor="top", yref="container",
                   pad=dict(t=12, l=4), font=dict(size=15)),
        height=height, template="plotly_dark" if is_dark() else "plotly_white",
        margin=dict(l=10, r=10, t=48 if title else 16, b=10, autoexpand=True), hovermode="x unified",
        legend=dict(orientation="h", yanchor="top", y=-0.1, xanchor="left", x=0, title=None,
                    font=dict(size=12)),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_xaxes(showgrid=False, title=None)
    fig.update_yaxes(gridcolor=GRID, title=y_title or None, zeroline=False,
                     tickformat=".0%" if pct_y else None)
    return fig


def style_map(names) -> Dict[str, tuple]:
    """名稱 → (顏色, 線型, 線寬)。策略為實線粗線；比較基準為固定顏色＋各自的虛線樣式。"""
    m, g = {}, 0
    for n in names:
        if n in STRATEGY_COLORS:
            m[n] = (STRATEGY_COLORS[n], "solid", 2.4)
        elif n in BENCH_STYLES:
            c, d = BENCH_STYLES[n]
            m[n] = (_c(c), d, 1.4 if n == "^TWII" else 1.8)
        else:
            c, d = BENCH_FALLBACK[g % len(BENCH_FALLBACK)]
            m[n] = (_c(c), d, 1.8)
            g += 1
    return m


def color_map(names) -> Dict[str, str]:
    return {n: v[0] for n, v in style_map(names).items()}


def nav_chart(returns: pd.DataFrame, labels: Optional[Dict[str, str]] = None, title: str = "累積淨值",
              log_y: bool = False) -> go.Figure:
    labels = labels or {}
    df = returns.sort_values("date")
    from .. import config
    rest = [p for p in df["portfolio"].unique() if p not in STRATEGIES]
    rest.sort(key=lambda p: config.BENCHMARKS.index(p) if p in config.BENCHMARKS else 99)   # 基準固定順序
    order = [s for s in STRATEGIES if s in set(df["portfolio"])] + rest
    smap = style_map(order)
    fig = go.Figure()
    lows, highs = [], []
    for p in order:
        g = df[df["portfolio"] == p]
        nav = (1 + g["ret"].fillna(0)).cumprod()
        if len(nav):
            lows.append(float(nav.min()))
            highs.append(float(nav.max()))
        c, dash, width = smap[p]
        fig.add_trace(go.Scatter(
            x=g["date"], y=nav, mode="lines", name=labels.get(p, p),
            line=dict(color=c, width=width, dash=dash),
            hovertemplate="%{y:.3f}",
        ))
    fig.add_hline(y=1, line=dict(color=GRID, width=1))
    fig = _layout(fig, title, y_title="淨值（起點 = 1，對數刻度）" if log_y else "淨值（起點 = 1）")
    if log_y:
        nice = [0.5, 0.7, 1, 1.5, 2, 3, 5, 7, 10, 15, 20, 30, 50, 70, 100, 150, 200, 300, 500, 700, 1000]
        lo, hi = (min(lows), max(highs)) if lows else (1.0, 1.0)
        ticks = [v for v in nice if lo * 0.9 <= v <= hi * 1.1] or [1]
        fig.update_yaxes(type="log", tickvals=ticks, ticktext=[f"{v:g}" for v in ticks])
    return fig


def drawdown_chart(returns: pd.DataFrame, labels: Optional[Dict[str, str]] = None) -> go.Figure:
    from ..metrics import drawdown_series
    labels = labels or {}
    df = returns.sort_values("date")
    smap = style_map(df["portfolio"].unique())
    fig = go.Figure()
    for p, g in df.groupby("portfolio", sort=False):
        c, dash, width = smap[p]
        fig.add_trace(go.Scatter(x=g["date"], y=drawdown_series(g["ret"]), mode="lines", name=labels.get(p, p),
                                 line=dict(color=c, width=width, dash=dash),
                                 hovertemplate="%{y:.1%}"))
    return _layout(fig, "回撤（相對歷史高點）", height=320, pct_y=True)


def risk_return_scatter(perf: pd.DataFrame, labels: Optional[Dict[str, str]] = None) -> go.Figure:
    labels = labels or {}
    cmap = color_map(perf["portfolio"])
    fig = go.Figure()
    for _, r in perf.iterrows():
        fig.add_trace(go.Scatter(
            x=[r["ann_vol"]], y=[r["ann_return"]], mode="markers+text", name=labels.get(r["portfolio"], r["portfolio"]),
            text=[labels.get(r["portfolio"], r["portfolio"])], textposition="top center",
            marker=dict(size=12, color=cmap[r["portfolio"]], line=dict(width=2, color=_bg()),
                        symbol="circle" if r["portfolio"] in STRATEGIES else "diamond"),
            hovertemplate="年化波動 %{x:.1%}<br>年化報酬 %{y:.1%}<extra></extra>",
        ))
    fig = _layout(fig, "風險與報酬", height=420, y_title="年化報酬", pct_y=True)
    fig.update_xaxes(title="年化波動", tickformat=".0%", showgrid=True, gridcolor=GRID)
    fig.update_layout(showlegend=False, hovermode="closest")
    return fig


def price_chart(df: pd.DataFrame, candle: bool, title: str) -> go.Figure:
    fig = go.Figure()
    has_ohlc = candle and df[["open", "high", "low"]].notna().all(axis=None)
    if has_ohlc:
        fig.add_trace(go.Candlestick(x=df["date"], open=df["open"], high=df["high"], low=df["low"],
                                     close=df["close"], name="K 線",
                                     increasing_line_color=UP, decreasing_line_color=DOWN))
    else:
        fig.add_trace(go.Scatter(x=df["date"], y=df["close"], name="收盤價", line=dict(color=SERIES_PALETTE[0], width=2)))
    fig.add_trace(go.Scatter(x=df["date"], y=df["sma20"], name="月線 SMA20", line=dict(color=SERIES_PALETTE[1], width=1.5)))
    fig.add_trace(go.Scatter(x=df["date"], y=df["sma60"], name="季線 SMA60", line=dict(color=SERIES_PALETTE[6], width=1.5)))
    fig = _layout(fig, title, height=480, y_title="價格")
    fig.update_layout(xaxis_rangeslider_visible=False, dragmode="zoom")
    fig.update_xaxes(rangeselector=dict(x=1, xanchor="right", y=1.02, yanchor="bottom", buttons=[
        dict(count=1, label="1 月", step="month", stepmode="backward"),
        dict(count=3, label="3 月", step="month", stepmode="backward"),
        dict(count=6, label="半年", step="month", stepmode="backward"),
        dict(label="全部", step="all")]))
    return fig


def line_chart(df: pd.DataFrame, x: str, y: str, title: str, pct: bool = False, height: int = 320) -> go.Figure:
    fig = go.Figure(go.Scatter(x=df[x], y=df[y], mode="lines", line=dict(color=SERIES_PALETTE[0], width=2),
                               hovertemplate="%{y:.2%}" if pct else "%{y:.3f}", name=title))
    fig = _layout(fig, title, height=height, pct_y=pct)
    fig.update_layout(showlegend=False)
    return fig


def histogram(values: pd.Series, title: str) -> go.Figure:
    fig = go.Figure(go.Histogram(x=values, nbinsx=40, marker=dict(color=SERIES_PALETTE[0], line=dict(width=1, color=_bg())),
                                 hovertemplate="%{x:.1%}：%{y} 天<extra></extra>"))
    fig = _layout(fig, title, height=320, y_title="天數")
    fig.update_xaxes(tickformat=".0%")
    fig.update_layout(showlegend=False, hovermode="closest", bargap=0.02)
    return fig


def bar_h(df: pd.DataFrame, x: str, y: str, title: str, height: int = 420) -> go.Figure:
    d = df.sort_values(x)
    fig = go.Figure(go.Bar(x=d[x], y=d[y], orientation="h", marker=dict(color=SERIES_PALETTE[0]),
                           hovertemplate="%{y}：%{x:.3f}<extra></extra>"))
    fig = _layout(fig, title, height=height)
    fig.update_layout(showlegend=False, hovermode="closest")
    fig.update_xaxes(showgrid=True, gridcolor=GRID)
    return fig


def esg_radar(e: float, s: float, g: float, total: Optional[float]) -> go.Figure:
    cats = ["環境 E", "社會 S", "治理 G", "環境 E"]
    fig = go.Figure(go.Scatterpolar(r=[e, s, g, e], theta=cats, fill="toself", name="分數",
                                    line=dict(color=SERIES_PALETTE[2], width=2),
                                    fillcolor="rgba(27,175,122,0.25)", hovertemplate="%{theta}：%{r:.1f}<extra></extra>"))
    fig.update_layout(polar=dict(radialaxis=dict(range=[0, 100], gridcolor=GRID), angularaxis=dict(gridcolor=GRID),
                                 bgcolor="rgba(0,0,0,0)"),
                      height=380, showlegend=False, margin=dict(l=40, r=40, t=50, b=20),
                      title=dict(text=f"E / S / G 分項（總分 {total:.1f}）" if total is not None else "E / S / G 分項", x=0),
                      paper_bgcolor="rgba(0,0,0,0)")
    return fig


def scatter_peers(df: pd.DataFrame, x: str, y: str, label: str, highlight: str, title: str,
                  x_title: str, y_title: str) -> go.Figure:
    fig = go.Figure()
    other = df[df[label] != highlight]
    me = df[df[label] == highlight]
    fig.add_trace(go.Scatter(x=other[x], y=other[y], mode="markers+text", text=other[label], textposition="top center",
                             marker=dict(size=10, color="#8a8984", line=dict(width=2, color=_bg())), name="同業"))
    fig.add_trace(go.Scatter(x=me[x], y=me[y], mode="markers+text", text=me[label], textposition="top center",
                             marker=dict(size=14, color=SERIES_PALETTE[0], line=dict(width=2, color=_bg())), name="本檔"))
    fig = _layout(fig, title, height=420, y_title=y_title, pct_y=True)
    fig.update_xaxes(title=x_title, showgrid=True, gridcolor=GRID)
    fig.update_layout(hovermode="closest")
    return fig


def exposure_chart(risk_log: pd.DataFrame) -> go.Figure:
    """每天的持股比例（1 = 全部買股票；其餘為現金）。"""
    fig = go.Figure()
    for p in [s for s in STRATEGIES if s in set(risk_log["portfolio"])]:
        g = risk_log[risk_log["portfolio"] == p].sort_values("date")
        fig.add_trace(go.Scatter(x=g["date"], y=g["exposure"], mode="lines", name=p, line_shape="hv",
                                 line=dict(color=STRATEGY_COLORS.get(p, "#888"), width=1.8),
                                 hovertemplate="%{y:.0%}"))
    fig = _layout(fig, "每日持股比例（其餘為現金）", height=300, pct_y=True)
    fig.update_yaxes(range=[0, 1.05])
    return fig


def industry_bar(df: pd.DataFrame, x: str, y: str, title: str, pct: bool = True, height: int = 460) -> go.Figure:
    """正值紅、負值綠（台股習慣）。"""
    d = df.sort_values(x)
    fig = go.Figure(go.Bar(x=d[x], y=d[y], orientation="h",
                           marker=dict(color=[UP if v >= 0 else DOWN for v in d[x]]),
                           hovertemplate="%{y}：%{x:.1%}<extra></extra>" if pct else "%{y}：%{x:,.1f}<extra></extra>"))
    fig = _layout(fig, title, height=height)
    fig.update_layout(showlegend=False, hovermode="closest")
    fig.update_xaxes(showgrid=True, gridcolor=GRID, tickformat=".0%" if pct else None)
    return fig


def rank_ic_chart(ic: pd.DataFrame) -> go.Figure:
    colors = [SERIES_PALETTE[0] if v >= 0 else SERIES_PALETTE[1] for v in ic["rank_ic"]]
    fig = go.Figure(go.Bar(x=ic["date"], y=ic["rank_ic"], marker=dict(color=colors),
                           hovertemplate="%{x|%Y-%m-%d}：%{y:.3f}<extra></extra>"))
    fig.add_hline(y=0, line=dict(color="#8a8984", width=1))
    fig = _layout(fig, "每次調倉的 Rank IC（預測排名 vs 實際報酬排名）", height=340)
    fig.update_layout(showlegend=False, hovermode="closest")
    return fig



def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{alpha})"


def forecast_chart(path: pd.DataFrame, strategy: str, title: str = "", height: int = 300) -> go.Figure:
    """持有期間預估：95%／68% 區間（色帶）、模型預期（虛線）、實際走勢（實線）、加權指數（灰色細線）。"""
    color = _c(STRATEGY_COLORS.get(strategy, SERIES_PALETTE[0]))
    x = path["date"]
    fig = go.Figure()
    for lo, hi, alpha, name in [("lo95", "hi95", 0.12, "95% 區間"), ("lo68", "hi68", 0.22, "68% 區間")]:
        fig.add_trace(go.Scatter(x=x, y=path[hi], mode="lines", line=dict(width=0), showlegend=False,
                                 hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=x, y=path[lo], mode="lines", line=dict(width=0), fill="tonexty",
                                 fillcolor=_rgba(color, alpha), name=name, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=x, y=path["expected"], mode="lines", name="模型預估",
                             line=dict(color=color, width=2, dash="dash"), hovertemplate="%{y:+.1%}"))
    if path["actual"].notna().sum() > 1:
        fig.add_trace(go.Scatter(x=x, y=path["actual"], mode="lines+markers", name="實際",
                                 line=dict(color=color, width=2.6), marker=dict(size=4), hovertemplate="%{y:+.1%}"))
    if path["market"].notna().sum() > 1:
        fig.add_trace(go.Scatter(x=x, y=path["market"], mode="lines", name="加權指數（實際）",
                                 line=dict(color=_c("#3f3e3b"), width=1.2, dash="dot"), hovertemplate="%{y:+.1%}"))
    fig.add_hline(y=0, line=dict(color=GRID, width=1))
    fig = _layout(fig, title, height=height, pct_y=True)
    fig.update_xaxes(tickformat="%m/%d", rangebreaks=[dict(bounds=["sat", "mon"])])   # 不畫週末空白
    return fig

__all__ = ["nav_chart", "drawdown_chart", "exposure_chart", "industry_bar", "risk_return_scatter", "price_chart", "line_chart", "histogram",
           "bar_h", "esg_radar", "scatter_peers", "rank_ic_chart", "forecast_chart", "STRATEGY_COLORS", "style_map", "px"]
