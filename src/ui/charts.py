"""Plotly 圖表（顏色固定跟著「策略/標的」走，不會因為篩選而換色）。"""
from __future__ import annotations

from typing import Dict, Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from ..backtest import STRATEGIES

# 三個策略用分類色第 1–3 格；比較基準一律灰階＋虛線（以線型區分，不佔用彩色）
STRATEGY_COLORS = {"AI+ESG": "#2a78d6", "單純 AI": "#eb6834", "單純 ESG": "#1baf7a"}
BENCH_GRAYS = ["#52514e", "#8a8984", "#6f6e69", "#a3a29c", "#3f3e3b"]
SERIES_PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
UP, DOWN = "#e34948", "#008300"   # 台股：紅漲綠跌
GRID = "rgba(128,128,128,0.18)"


def _layout(fig: go.Figure, title: str = "", height: int = 420, y_title: str = "", pct_y: bool = False) -> go.Figure:
    # 圖例放在圖的「下方」：放上方時，圖例一換行就會蓋到標題（視窗窄、線條多時最明顯）。
    # 下方空間由 Plotly 自動撐開（margin.autoexpand），幾行圖例都不會重疊。
    fig.update_layout(
        title=dict(text=title, x=0, xanchor="left", y=1, yanchor="top", yref="container",
                   pad=dict(t=12, l=4), font=dict(size=15)),
        height=height, template="plotly_white",
        margin=dict(l=10, r=10, t=48 if title else 16, b=10, autoexpand=True), hovermode="x unified",
        legend=dict(orientation="h", yanchor="top", y=-0.1, xanchor="left", x=0, title=None,
                    font=dict(size=12)),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_xaxes(showgrid=False, title=None)
    fig.update_yaxes(gridcolor=GRID, title=y_title or None, zeroline=False,
                     tickformat=".0%" if pct_y else None)
    return fig


def color_map(names) -> Dict[str, str]:
    m, g = {}, 0
    for n in names:
        if n in STRATEGY_COLORS:
            m[n] = STRATEGY_COLORS[n]
        else:
            m[n] = BENCH_GRAYS[g % len(BENCH_GRAYS)]
            g += 1
    return m


def nav_chart(returns: pd.DataFrame, labels: Optional[Dict[str, str]] = None, title: str = "累積淨值") -> go.Figure:
    labels = labels or {}
    df = returns.sort_values("date")
    order = [s for s in STRATEGIES if s in set(df["portfolio"])] + \
            [p for p in df["portfolio"].unique() if p not in STRATEGIES]
    cmap = color_map(order)
    fig = go.Figure()
    for p in order:
        g = df[df["portfolio"] == p]
        nav = (1 + g["ret"].fillna(0)).cumprod()
        is_bench = p not in STRATEGIES
        fig.add_trace(go.Scatter(
            x=g["date"], y=nav, mode="lines", name=labels.get(p, p),
            line=dict(color=cmap[p], width=2, dash="dot" if is_bench else "solid"),
            hovertemplate="%{y:.3f}",
        ))
    fig.add_hline(y=1, line=dict(color=GRID, width=1))
    return _layout(fig, title, y_title="淨值（起點 = 1）")


def drawdown_chart(returns: pd.DataFrame, labels: Optional[Dict[str, str]] = None) -> go.Figure:
    from ..metrics import drawdown_series
    labels = labels or {}
    df = returns.sort_values("date")
    cmap = color_map(df["portfolio"].unique())
    fig = go.Figure()
    for p, g in df.groupby("portfolio", sort=False):
        fig.add_trace(go.Scatter(x=g["date"], y=drawdown_series(g["ret"]), mode="lines", name=labels.get(p, p),
                                 line=dict(color=cmap[p], width=2, dash="solid" if p in STRATEGIES else "dot"),
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
            marker=dict(size=12, color=cmap[r["portfolio"]], line=dict(width=2, color="white"),
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
    fig = go.Figure(go.Histogram(x=values, nbinsx=40, marker=dict(color=SERIES_PALETTE[0], line=dict(width=1, color="white")),
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
                             marker=dict(size=10, color="#8a8984", line=dict(width=2, color="white")), name="同業"))
    fig.add_trace(go.Scatter(x=me[x], y=me[y], mode="markers+text", text=me[label], textposition="top center",
                             marker=dict(size=14, color=SERIES_PALETTE[0], line=dict(width=2, color="white")), name="本檔"))
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


__all__ = ["nav_chart", "drawdown_chart", "exposure_chart", "industry_bar", "risk_return_scatter", "price_chart", "line_chart", "histogram",
           "bar_h", "esg_radar", "scatter_peers", "rank_ic_chart", "STRATEGY_COLORS", "px"]
