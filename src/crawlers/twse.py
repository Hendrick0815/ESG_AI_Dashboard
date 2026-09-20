"""證交所爬蟲：上市/上櫃股票清單、每日本益比/股價淨值比/殖利率。

- 清單：https://isin.twse.com.tw/isin/C_public.jsp?strMode=2（上市）/ strMode=4（上櫃）
  用 CFICode = ESVUFR 只留普通股，排除 ETF、權證、特別股、TDR。
- 估值：https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d（可查歷史任一交易日，僅上市）
解析函式（parse_*）和抓取分開，方便用離線資料測試。
"""
from __future__ import annotations

import logging
import random
import time
from typing import Iterable, List, Optional

import pandas as pd
import requests

from ..utils import to_number

log = logging.getLogger(__name__)

ISIN_URL = "https://isin.twse.com.tw/isin/C_public.jsp?strMode={mode}"
BWIBBU_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
COMMON_STOCK_CFI = "ESVUFR"
MARKETS = {"上市": (2, ".TW"), "上櫃": (4, ".TWO")}


def _get(url: str, params: Optional[dict] = None, retries: int = 3, timeout: int = 20) -> requests.Response:
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            if b"FOR SECURITY REASONS" in r.content[:2000]:
                # 證交所防火牆擋下（常見於雲端主機或短時間請求太多次），重試也沒用
                raise PermissionError("證交所防火牆拒絕這次連線（FOR SECURITY REASONS）。"
                                      "請在自己的電腦執行，或等幾分鐘後再試。")
            return r
        except PermissionError:
            raise
        except Exception as e:  # 網路錯誤就退避重試
            last = e
            time.sleep(2 + i * 3 + random.random())
    raise RuntimeError(f"連線失敗：{url}（{last}）")


# ------------------------------------------------------------------ 股票清單
def parse_isin_table(html: str, market: str) -> pd.DataFrame:
    """用 BeautifulSoup 解析（ISIN 頁的 HTML 不標準，pandas.read_html 常需要額外套件）。"""
    from bs4 import BeautifulSoup

    suffix = MARKETS[market][1]
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    header: list = []
    for tr in soup.find_all("tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if not header:
            if cells and "有價證券代號" in cells[0]:
                header = cells
            continue
        if len(cells) < len(header):          # 「股票」「ETF」等分類標題列
            continue
        rec = dict(zip(header, cells))
        parts = cells[0].replace("\u3000", " ").split(None, 1)
        if len(parts) != 2:
            continue
        code, name = parts[0].strip(), parts[1].strip()
        cfi = next((v for k, v in rec.items() if "CFI" in k), None)
        if cfi is not None and cfi != COMMON_STOCK_CFI:
            continue
        if not (code.isdigit() and len(code) == 4):
            continue
        industry = next((v for k, v in rec.items() if "產業" in k), "")
        rows.append({"ticker": f"{code}{suffix}", "code": code, "name": name,
                     "market": market, "industry": industry})
    if not header:
        raise ValueError("ISIN 頁面格式不符（找不到表頭），可能被擋或網頁改版")
    return pd.DataFrame(rows, columns=["ticker", "code", "name", "market", "industry"])


def fetch_listing(markets: Iterable[str] = ("上市", "上櫃")) -> pd.DataFrame:
    frames = []
    for m in markets:
        mode = MARKETS[m][0]
        r = _get(ISIN_URL.format(mode=mode))
        # 用 cp950 解碼，比 big5 多支援「碁、堃」等字
        html = r.content.decode("cp950", errors="replace")
        frames.append(parse_isin_table(html, m))
        log.info("%s 普通股 %d 檔", m, len(frames[-1]))
    return pd.concat(frames, ignore_index=True).drop_duplicates("ticker")


# ------------------------------------------------------------------ 估值（本益比等）
def parse_bwibbu(payload: dict, date: pd.Timestamp) -> pd.DataFrame:
    """BWIBBU_d 回傳的 JSON → date, ticker, pe, pb, dividend_yield。欄位依名稱辨識，順序改了也能用。"""
    if not payload or payload.get("stat") != "OK" or not payload.get("data"):
        return pd.DataFrame(columns=["date", "ticker", "pe", "pb", "dividend_yield"])
    fields = [str(f) for f in payload["fields"]]
    df = pd.DataFrame(payload["data"], columns=fields)

    def col(*keys):
        return next((f for f in fields if any(k in f for k in keys)), None)

    code_c, pe_c, pb_c, dy_c = col("證券代號"), col("本益比"), col("股價淨值比"), col("殖利率")
    out = pd.DataFrame({
        "date": pd.Timestamp(date).normalize(),
        "code": df[code_c].astype(str).str.strip(),
        "pe": to_number(df[pe_c]) if pe_c else float("nan"),
        "pb": to_number(df[pb_c]) if pb_c else float("nan"),
        "dividend_yield": to_number(df[dy_c]) / 100 if dy_c else float("nan"),
    })
    out = out[out["code"].str.fullmatch(r"\d{4}")]
    out["ticker"] = out["code"] + ".TW"
    return out[["date", "ticker", "pe", "pb", "dividend_yield"]].reset_index(drop=True)


def fetch_valuation(date: pd.Timestamp) -> pd.DataFrame:
    params = {"date": pd.Timestamp(date).strftime("%Y%m%d"), "selectType": "ALL", "response": "json"}
    r = _get(BWIBBU_URL, params=params)
    try:
        payload = r.json()
    except ValueError:
        return parse_bwibbu({}, date)
    return parse_bwibbu(payload, date)


def fetch_valuation_series(dates: List[pd.Timestamp], sleep: float = 3.0, progress=None) -> pd.DataFrame:
    """依序抓多個交易日（證交所限制頻率，每次間隔約 3 秒）。"""
    frames = []
    for i, d in enumerate(dates, 1):
        try:
            df = fetch_valuation(d)
            if not df.empty:
                frames.append(df)
            else:
                log.warning("%s 沒有估值資料（可能非交易日）", pd.Timestamp(d).date())
        except PermissionError:
            raise                      # 被防火牆擋就停止，不要一直重試
        except Exception as e:
            log.warning("%s 估值抓取失敗：%s", pd.Timestamp(d).date(), e)
        if progress:
            progress(i, len(dates), pd.Timestamp(d))
        if i < len(dates):
            time.sleep(sleep + random.random())
    if not frames:
        return pd.DataFrame(columns=["date", "ticker", "pe", "pb", "dividend_yield"])
    return pd.concat(frames, ignore_index=True)
