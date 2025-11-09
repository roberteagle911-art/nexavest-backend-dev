# api/main.py
import os
import requests
import yfinance as yf
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict
from datetime import datetime

app = FastAPI(title="NexaVest Smart Engine v3.0 (Dev)")

# CORS - allow your dev/prod frontends as needed. For dev we allow all.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # change to your frontend domain(s) in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Optional: Finnhub key (use env var in prod)
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")  # optional
FINNHUB_URL = "https://finnhub.io/api/v1/quote"
YAHOO_SEARCH_URL = "https://query1.finance.yahoo.com/v1/finance/search"
COINGECKO_SEARCH_URL = "https://api.coingecko.com/api/v3/search"
COINGECKO_PRICE_URL = "https://api.coingecko.com/api/v3/simple/price"
EXR_API = "https://api.exchangerate.host/latest"  # free exchange rates

# Currency mapping by known exchange suffix or exchange name
EXCHANGE_CURRENCY_MAP = {
    # suffix : currency code
    ".NS": "INR",  # NSE
    ".BO": "INR",  # BSE (rare)
    ".KS": "KRW",  # Korea
    ".KR": "KRW",
    ".T": "JPY",   # Tokyo
    ".L": "GBP",   # London
    ".AX": "AUD",  # Australia
    ".HK": "HKD",  # Hong Kong
    ".SZ": "CNY",  # Shenzhen
    ".SS": "CNY",  # Shanghai
    # default will be USD if unknown
}

# Simple helper models
class AnalyzeRequest(BaseModel):
    query: str       # company name, ticker, crypto name, etc.
    amount: float    # investment amount (in user's currency default we'll assume)

# Helper utilities
def safe_get(d: dict, *keys, default=None):
    for k in keys:
        if isinstance(d, dict) and k in d:
            return d[k]
    return default

def fetch_exchange_rate(from_cc: str, to_cc: str = "USD") -> Optional[float]:
    # Example: convert INR -> USD or vice versa; returns rate multiplier to convert from_cc -> to_cc
    try:
        r = requests.get(EXR_API, params={"base": from_cc, "symbols": to_cc}, timeout=6)
        j = r.json()
        if "rates" in j and to_cc in j["rates"]:
            return float(j["rates"][to_cc])
    except Exception:
        pass
    return None

def coin_gecko_search(query: str) -> List[dict]:
    try:
        r = requests.get(COINGECKO_SEARCH_URL, params={"query": query}, timeout=6)
        j = r.json()
        return j.get("coins", [])  # list of coin dicts
    except Exception:
        return []

def coin_gecko_price(coin_id: str, vs_currencies: List[str] = ["usd","inr"]) -> dict:
    try:
        vs = ",".join(vs_currencies)
        r = requests.get(COINGECKO_PRICE_URL, params={"ids": coin_id, "vs_currencies": vs}, timeout=6)
        return r.json().get(coin_id, {})
    except Exception:
        return {}

def yahoo_search(query: str) -> List[dict]:
    try:
        r = requests.get(YAHOO_SEARCH_URL, params={"q": query}, timeout=6)
        j = r.json()
        # `quotes` usually contains best matching results
        results = []
        for key in ("quotes", "news", "lists", "currencies"):
            if key in j and isinstance(j[key], list):
                results.extend(j[key])
        # ensure unique by symbol if present
        return results
    except Exception:
        return []

def fetch_price_with_yfinance(symbol: str, days: int = 7) -> Optional[dict]:
    """
    Returns dict with keys:
      current, prev_close, high, low, chart (list of {"date":"YYYY-MM-DD","price":float})
    """
    try:
        t = yf.Ticker(symbol)
        # fetch a little extra to be safe
        period = f"{max(7, days)}d"
        hist = t.history(period=period, interval="1d", actions=False)
        if hist is None or hist.empty:
            return None
        # ensure we have at least two rows
        closes = hist["Close"].tolist()
        highs = hist["High"].tolist() if "High" in hist.columns else closes
        lows = hist["Low"].tolist() if "Low" in hist.columns else closes
        timestamps = list(hist.index)
        current = float(closes[-1])
        prev_close = float(closes[-2]) if len(closes) >= 2 else current
        high = float(highs[-1]) if highs else current
        low = float(lows[-1]) if lows else current
        chart = []
        for ts, price in zip(timestamps, closes):
            date_str = ts.strftime("%Y-%m-%d")
            chart.append({"date": date_str, "price": round(float(price), 2)})
        return {"current": current, "prev_close": prev_close, "high": high, "low": low, "chart": chart}
    except Exception:
        return None

def fetch_price_with_finnhub(symbol: str) -> Optional[dict]:
    if not FINNHUB_API_KEY:
        return None
    try:
        r = requests.get(f"{FINNHUB_URL}?symbol={symbol}&token={FINNHUB_API_KEY}", timeout=6)
        j = r.json()
        if not j or "c" not in j or j.get("c") is None:
            return None
        current = float(j["c"])
        prev = float(j.get("pc", current))
        high = float(j.get("h", current))
        low = float(j.get("l", current))
        return {"current": current, "prev_close": prev, "high": high, "low": low, "chart": []}
    except Exception:
        return None

def detect_asset_type_and_symbol(query: str) -> dict:
    """
    Returns:
      {
        "type": "crypto" | "stock" | "fund" | "index" | "unknown",
        "symbol": "AAPL" or "066570.KS" or "bitcoin",
        "name": "Apple Inc",
        "exchange": "NSE" or "NASDAQ" or None,
        "source": "coingecko" | "yahoo" | "user",
      }
    """
    q = query.strip()
    if not q:
        return {"type": "unknown"}

    # 1) Try CoinGecko search first to detect crypto by name or symbol
    coins = coin_gecko_search(q)
    if coins:
        # prefer exact symbol match
        q_upper = q.upper()
        for c in coins:
            if "symbol" in c and c["symbol"].upper() == q_upper:
                return {"type": "crypto", "symbol": c["id"], "name": c.get("name"), "exchange": None, "source": "coingecko"}
        # otherwise use first coin
        first = coins[0]
        return {"type": "crypto", "symbol": first["id"], "name": first.get("name"), "exchange": None, "source": "coingecko"}

    # 2) If user typed something that already looks like a ticker with known suffix, treat as stock
    u = q.upper()
    for suf in EXCHANGE_CURRENCY_MAP.keys():
        if u.endswith(suf):
            # treat as symbol
            return {"type": "stock", "symbol": u, "name": q, "exchange": None, "source": "user"}

    # 3) Try Yahoo search to find best matches (stocks, funds, ETFs, indices)
    results = yahoo_search(q)
    if results:
        # The search result items often include 'symbol','shortname','exchange','quoteType'
        # We'll pick the first quote-like result that has a symbol
        best = None
        for item in results:
            sym = item.get("symbol") or item.get("id")
            if not sym:
                continue
            qtype = item.get("quoteType", "").lower()
            # prefer equities, funds, etf, index, mutualfund
            if qtype in ("equity", "et", "etf", "index", "mutualfund", "fund"):
                best = item
                break
            # fallback to any item with symbol
            if best is None:
                best = item
        if best:
            symbol = best.get("symbol") or best.get("id")
            name = best.get("shortname") or best.get("longname") or best.get("name") or q
            exchange = best.get("exchange") or best.get("exchDisp") or None
            qtype = best.get("quoteType", "").lower()
            atype = "stock"
            if "etf" in qtype:
                atype = "etf"
            elif "index" in qtype:
                atype = "index"
            elif "fund" in qtype or "mutualfund" in qtype:
                atype = "fund"
            return {"type": atype, "symbol": symbol, "name": name, "exchange": exchange, "source": "yahoo"}
    # 4) Fallback: if the string looks like an alphanumeric symbol (no spaces) treat as stock symbol
    if " " not in q and len(q) <= 10:
        return {"type": "stock", "symbol": q.upper(), "name": q, "exchange": None, "source": "user"}

    return {"type": "unknown"}

def map_currency_from_symbol_or_exchange(symbol: str, exchange: Optional[str] = None) -> str:
    # 1) try symbol suffix mapping
    sym = (symbol or "").upper()
    for suffix, cc in EXCHANGE_CURRENCY_MAP.items():
        if sym.endswith(suffix):
            return cc
    # 2) try exchange name
    if exchange:
        ex = exchange.upper()
        if "NSE" in ex or "BSE" in ex:
            return "INR"
        if "NASDAQ" in ex or "NASDAQNM" in ex or "NYSE" in ex:
            return "USD"
        if "KRX" in ex or "KOREA" in ex:
            return "KRW"
        if "TOKYO" in ex or "TSE" in ex:
            return "JPY"
        if "LONDON" in ex or "LSE" in ex:
            return "GBP"
    # 3) try yfinance info for currency
    try:
        t = yf.Ticker(symbol)
        info = t.info
        cur = info.get("currency")
        if cur:
            return cur.upper()
    except Exception:
        pass
    # default USD
    return "USD"

def classify_risk(volatility: float) -> (str, str):
    # return (risk_category, holding_period_string)
    if volatility < 0.02:
        return "Low", "12+ months"
    if volatility < 0.05:
        return "Medium", "3-12 months"
    return "High", "0-3 months"

@app.post("/api/analyze")
def analyze(request: AnalyzeRequest):
    q = request.query.strip()
    amount = float(request.amount or 0)

    if not q:
        raise HTTPException(status_code=400, detail="Please provide a company name, ticker, or crypto")

    detected = detect_asset_type_and_symbol(q)

    if detected.get("type") == "unknown":
        raise HTTPException(status_code=404, detail="Could not detect asset from query")

    # If crypto -> use CoinGecko
    if detected["type"] == "crypto":
        coin_id = detected["symbol"]  # coin id on coingecko, e.g., 'bitcoin'
        coin_name = detected.get("name") or coin_id
        # get price in usd and inr
        prices = coin_gecko_price(coin_id, vs_currencies=["usd","inr"])
        if not prices:
            raise HTTPException(status_code=502, detail="Unable to fetch crypto price from CoinGecko")
        usd_price = float(prices.get("usd", 0))
        inr_price = float(prices.get("inr", 0)) if "inr" in prices else None

        # Attempt to compute a simple volatility using 7-day coin market chart (optional)
        # We'll instead return a placeholder volatility using percent change 24h if available via coins search
        # For simplicity, set volatility to 0.07 for crypto if no better data
        volatility = 0.07

        # expected return unknown here — set 0.0 baseline
        expected_return = 0.0

        estimated_value_usd = round(amount * (1 if False else 1), 2)  # amount assumed in USD by default for crypto
        # But if user used numeric amount and meant INR, they likely used INR — we keep amount as user-specified
        # We will return both USD and INR prices and compute estimated value in both if possible
        # Gain/loss can't be estimated without prev price; keep 0.0

        response = {
            "query": q,
            "asset_type": "crypto",
            "symbol": coin_id,
            "name": coin_name,
            "market": "CoinGecko",
            "currency": "USD",
            "current_price_usd": round(usd_price, 2),
            "current_price_inr": round(inr_price, 2) if inr_price else None,
            "volatility": volatility,
            "expected_return": expected_return,
            "risk_category": "High",
            "holding_period": "Short (crypto is highly volatile)",
            "estimated_value": None,
            "gain_loss": None,
            "ai_recommendation": f"{coin_name} is a crypto asset with high volatility. Only suitable for aggressive investors."
        }
        return response

    # Else: stock / fund / index / etf
    symbol = detected.get("symbol")
    name = detected.get("name") or symbol
    exchange = detected.get("exchange")

    # Try yfinance history first (best general)
    price_data = fetch_price_with_yfinance(symbol, days=7)

    # If not available, try Finnhub if configured
    if not price_data:
        price_data = fetch_price_with_finnhub(symbol)

    # If still not available, attempt alternative guesses:
    if not price_data:
        # Try appending common suffixes for Indian stocks if query seems like company name without suffix
        if not "." in symbol and len(symbol) <= 8:
            # try .NS (NSE)
            trial = fetch_price_with_yfinance(symbol + ".NS", days=7)
            if trial:
                symbol = symbol + ".NS"
                price_data = trial
                exchange = exchange or "NSE"
        # final fallback: fail
    if not price_data:
        raise HTTPException(status_code=502, detail=f"Unable to fetch market data for symbol '{symbol}'")

    current = float(price_data["current"])
    prev_close = float(price_data["prev_close"])
    high = float(price_data.get("high", current))
    low = float(price_data.get("low", current))
    chart = price_data.get("chart", [])

    # compute volatility & returns
    try:
        volatility = round(abs(high - low) / current, 3) if current != 0 else 0.0
    except Exception:
        volatility = 0.0
    try:
        expected_return = round((current - prev_close) / prev_close, 3) if prev_close != 0 else 0.0
    except Exception:
        expected_return = 0.0

    # determine currency
    currency = map_currency_from_symbol_or_exchange(symbol, exchange)

    # risk & holding period
    risk_cat, holding = classify_risk(volatility)

    # estimated value & gain/loss (assume amount entered is in user's local currency — we will present estimated in that currency)
    # For retail simplicity: assume user's 'amount' is in the asset's local currency (INR for .NS, USD for US tickers). If you want to allow user currency argument later, add conversion.
    estimated_value = round(amount * (1 + expected_return), 2)
    gain_loss = round(estimated_value - amount, 2)

    # AI-style recommendation (template-based)
    ai_reco = (
        f"{name} ({symbol}) shows {risk_cat.lower()} volatility ({volatility}). "
        f"Short-term expected return ~{expected_return*100:.2f}%. "
        f"Suggested holding period: {holding}. "
    )

    result = {
        "query": q,
        "asset_type": "stock" if detected["type"] in ("stock","etf","index","fund") else detected["type"],
        "symbol": symbol,
        "name": name,
        "market": exchange or "Unknown",
        "currency": currency,
        "current_price": round(current, 4) if current is not None else None,
        "prev_close": round(prev_close, 4) if prev_close is not None else None,
        "volatility": volatility,
        "expected_return": expected_return,
        "risk_category": risk_cat,
        "holding_period": holding,
        "estimated_value": estimated_value,
        "gain_loss": gain_loss,
        "ai_recommendation": ai_reco,
        "chart": chart  # list of {date, price}
    }

    return result

@app.get("/")
def home():
    return {"status": "ok", "message": "NexaVest Smart Engine v3.0 (Dev) is live"}
