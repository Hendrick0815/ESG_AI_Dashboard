"""證交所爬蟲：上市/上櫃股票清單、每日本益比/股價淨值比/殖利率。

- 清單：https://isin.twse.com.tw/isin/C_public.jsp?strMode=2（上市）/ strMode=4（上櫃）
  用 CFICode = ESVUFR 只留普通股，排除 ETF、權證、特別股、TDR。
- 估值：https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d（可查歷史任一交易日，僅上市）
- 三大法人買賣超：https://www.twse.com.tw/rwd/zh/fund/T86（每日，僅上市）
- 每日成交金額（選股票池用）：上市 MI_INDEX（type=ALLBUT0999）、上櫃 tpex dailyQuotes
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
T86_URL = "https://www.twse.com.tw/rwd/zh/fund/T86"
MI_INDEX_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
TPEX_QUOTES_URL = "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes"
FLOW_COLS = ["date", "ticker", "foreign_net", "trust_net", "dealer_net", "total_net"]
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


# ------------------------------------------------------------------ 三大法人買賣超（主力動向）
def parse_t86(payload: dict, date: pd.Timestamp) -> pd.DataFrame:
    """T86 回傳的 JSON → date, ticker, foreign_net, trust_net, dealer_net, total_net（單位：股）。
    外資 = 外陸資（不含外資自營商）＋外資自營商；欄位依名稱辨識。"""
    if not payload or payload.get("stat") != "OK" or not payload.get("data"):
        return pd.DataFrame(columns=FLOW_COLS)
    fields = [str(f) for f in payload["fields"]]
    df = pd.DataFrame(payload["data"], columns=fields)

    def num(pred):
        cols = [f for f in fields if pred(f)]
        return to_number(df[cols[0]]).fillna(0) if cols else pd.Series(0.0, index=df.index)

    foreign = num(lambda f: "外陸資買賣超" in f) + num(lambda f: "外資自營商買賣超" in f)
    trust = num(lambda f: "投信買賣超" in f)
    dealer = num(lambda f: f.startswith("自營商買賣超") and "(" not in f)
    total_cols = [f for f in fields if "三大法人買賣超" in f]
    total = to_number(df[total_cols[0]]) if total_cols else foreign + trust + dealer
    code_c = next(f for f in fields if "代號" in f)
    out = pd.DataFrame({
        "date": pd.Timestamp(date).normalize(),
        "code": df[code_c].astype(str).str.strip(),
        "foreign_net": foreign, "trust_net": trust, "dealer_net": dealer, "total_net": total,
    })
    out = out[out["code"].str.fullmatch(r"\d{4}")]
    out["ticker"] = out["code"] + ".TW"
    return out[FLOW_COLS].reset_index(drop=True)


def fetch_t86(date: pd.Timestamp) -> pd.DataFrame:
    params = {"date": pd.Timestamp(date).strftime("%Y%m%d"), "selectType": "ALLBUT0999", "response": "json"}
    r = _get(T86_URL, params=params)
    try:
        payload = r.json()
    except ValueError:
        return parse_t86({}, date)
    return parse_t86(payload, date)


def fetch_t86_series(dates: List[pd.Timestamp], sleep: float = 3.0, progress=None, on_chunk=None,
                     chunk: int = 20) -> pd.DataFrame:
    """依序抓多個交易日。on_chunk(df)：每抓 chunk 天就呼叫一次（用來邊抓邊存檔，中斷也不會白抓）。"""
    frames, pending = [], []
    for i, d in enumerate(dates, 1):
        try:
            df = fetch_t86(d)
            if not df.empty:
                frames.append(df)
                pending.append(df)
        except PermissionError:
            if on_chunk and pending:
                on_chunk(pd.concat(pending, ignore_index=True))
            raise
        except Exception as e:
            log.warning("%s 法人資料抓取失敗：%s", pd.Timestamp(d).date(), e)
        if progress:
            progress(i, len(dates), pd.Timestamp(d))
        if on_chunk and pending and (i % chunk == 0 or i == len(dates)):
            on_chunk(pd.concat(pending, ignore_index=True))
            pending = []
        if i < len(dates):
            time.sleep(sleep + random.random())
    if not frames:
        return pd.DataFrame(columns=FLOW_COLS)
    return pd.concat(frames, ignore_index=True)


# ------------------------------------------------------------------ 每日成交金額（選股票池）
def _value_table(tables: list, code_key: str, value_key: str) -> Optional[pd.DataFrame]:
    for t in tables or []:
        fields = [str(f) for f in (t.get("fields") or [])]
        code_c = next((f for f in fields if code_key in f), None)
        value_c = next((f for f in fields if value_key in f), None)
        if code_c and value_c and t.get("data"):
            df = pd.DataFrame(t["data"], columns=fields)
            return pd.DataFrame({"code": df[code_c].astype(str).str.strip(),
                                 "trade_value": to_number(df[value_c])})
    return None


def parse_trading_value(payload: dict, date: pd.Timestamp, suffix: str) -> pd.DataFrame:
    """MI_INDEX（上市）或 dailyQuotes（上櫃）JSON → date, ticker, trade_value（元）。只留 4 碼代號。"""
    cols = ["date", "ticker", "trade_value"]
    if not payload:
        return pd.DataFrame(columns=cols)
    code_key = "證券代號" if suffix == ".TW" else "代號"
    df = _value_table(payload.get("tables"), code_key, "成交金額")
    if df is None or df.empty:
        return pd.DataFrame(columns=cols)
    df = df[df["code"].str.fullmatch(r"\d{4}")].copy()
    df["ticker"] = df["code"] + suffix
    df["date"] = pd.Timestamp(date).normalize()
    return df[cols].reset_index(drop=True)


def fetch_trading_value(date: pd.Timestamp) -> pd.DataFrame:
    """某交易日全部上市＋上櫃股票的成交金額。非交易日回傳空表。"""
    d = pd.Timestamp(date)
    frames = []
    r = _get(MI_INDEX_URL, params={"date": d.strftime("%Y%m%d"), "type": "ALLBUT0999", "response": "json"})
    try:
        frames.append(parse_trading_value(r.json(), d, ".TW"))
    except ValueError:
        pass
    try:
        r = _get(TPEX_QUOTES_URL, params={"date": d.strftime("%Y/%m/%d"), "response": "json"})
        frames.append(parse_trading_value(r.json(), d, ".TWO"))
    except Exception as e:          # 上櫃抓不到時仍可只用上市
        log.warning("上櫃成交金額抓取失敗 %s：%s", d.date(), e)
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["date", "ticker", "trade_value"])


def rank_by_trading_value(end: pd.Timestamp, days: int = 20, sleep: float = 4.0, progress=None) -> pd.DataFrame:
    """往回找 days 個交易日，計算每檔平均成交金額 → ticker, avg_value, n_days（由大到小）。"""
    frames, d, tries = [], pd.Timestamp(end).normalize(), 0
    while len(frames) < days and tries < days * 2 + 10:
        if d.weekday() < 5:
            try:
                df = fetch_trading_value(d)
            except PermissionError:
                if len(frames) >= 5:      # 被證交所限流：已有 5 天以上就用現有的平均
                    log.warning("證交所限流，改用已抓到的 %d 個交易日", len(frames))
                    break
                raise
            if not df.empty:
                frames.append(df)
                if progress:
                    progress(len(frames), days, d)
            time.sleep(sleep)
        d -= pd.Timedelta(days=1)
        tries += 1
    if not frames:
        return pd.DataFrame(columns=["ticker", "avg_value", "n_days"])
    allv = pd.concat(frames, ignore_index=True)
    out = allv.groupby("ticker")["trade_value"].agg(avg_value="mean", n_days="size").reset_index()
    return out.sort_values("avg_value", ascending=False).reset_index(drop=True)
