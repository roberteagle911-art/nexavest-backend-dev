# main.py
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import yfinance as yf
import math
import statistics
from typing import Optional

app = FastAPI(title="NexaVest Backend (stable detect & analyze)")

# CORS - allow your frontend domains (dev & prod)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://nexavest-frontend.vercel.app",
        "https://nexavest-frontend-dev.vercel.app",
        "https://nexavest-frontend.vercel.app/",
        "https://nexavest-backend.vercel.app",
        # add more origins you use
        "*",  # during development you can keep '*' but prefer the exact origins in production
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === CONFIG ===
FINNHUB_API_KEY = "d47qudpr01qk80bi464gd47qudpr01qk80bi4650"  # <--- your provided key
FINNHUB_BASE = "https://finnhub.io/api/v1"
COINGECKO_BASE = "https://api.coingecko.com/api/v3"
EXCHANGE_CONVERT = "https://api.exchangerate.host/convert"  # free convert endpoint

# === Request model ===
class AnalyzeRequest(BaseModel):
    query: str
    amount: Optional[float] = 0.0

# === Helpers ===
def finnhub_symbol_search(q: str):
    """Search Finnhub for matching symbols."""
    try:
        url = f"{FINNHUB_BASE}/search"
        r = requests.get(url, params={"q": q, "token": FINNHUB_API_KEY}, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None

def finnhub_quote(symbol: str):
    """Get Finnhub quote (c, h, l, pc)."""
    try:
        url = f"{FINNHUB_BASE}/quote"
        r = requests.get(url, params={"symbol": symbol, "token": FINNHUB_API_KEY}, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None

def coingecko_search(q: str):
    try:
        url = f"{COINGECKO_BASE}/search"
        r = requests.get(url, params={"query": q}, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None

def coingecko_price_by_id(coin_id: str, vs_currencies="usd"):
    try:
        url = f"{COINGECKO_BASE}/simple/price"
        r = requests.get(url, params={"ids": coin_id, "vs_currencies": vs_currencies}, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None

def convert_currency(amount: float, frm: str, to: str):
    """Use exchangerate.host to convert currencies (free)."""
    try:
        r = requests.get(EXCHANGE_CONVERT, params={"from": frm.upper(), "to": to.upper(), "amount": amount}, timeout=8)
        r.raise_for_status()
        j = r.json()
        return j.get("result", None)
    except Exception:
        return None

def safe_round(x, nd=3):
    try:
        return round(x, nd)
    except Exception:
        return x

def compute_stats_from_history(prices):
    """
    prices: list of closes (most recent last)
    returns (current_price, volatility, expected_return)
    volatility: stddev of daily returns
    expected_return: mean daily return
    """
    if not prices or len(prices) < 2:
        return None, 0.0, 0.0
    # compute daily returns
    returns = []
    for i in range(1, len(prices)):
        prev = prices[i-1]
        cur = prices[i]
        if prev == 0:
            continue
        r = (cur - prev) / prev
        returns.append(r)
    if not returns:
        return prices[-1], 0.0, 0.0
    volatility = statistics.pstdev(returns)  # population stddev
    expected_return = statistics.mean(returns)
    return prices[-1], volatility, expected_return

def risk_category_from_vol(volatility: float):
    if volatility < 0.02:
        return "Low"
    if volatility < 0.05:
        return "Medium"
    return "High"

def holding_period_by_asset_type(asset_type: str):
    if asset_type == "crypto":
        return "short (crypto is highly volatile)"
    if asset_type == "stock":
        return "12+ months"
    return "Varies"

# === Detection & Analysis core ===
def detect_and_analyze(query: str, amount: float):
    q = query.strip()
    # 1) Try Finnhub search (company/ticker)
    fh_search = finnhub_symbol_search(q)
    # preference: exact ticker-like input (e.g. RELIANCE.NS or AAPL) -> direct quote
    # If user input looks like ticker with dot or uppercase letters, try as-is first
    candidate = None
    asset_type = "unknown"
    market = "Unknown"
    currency = "USD"
    analysis = {}

    # If input looks like a ticker (contains dot or is uppercase with no spaces) try direct
    maybe_ticker_try = False
    if "." in q or (q.isupper() and " " not in q and len(q) <= 10):
        maybe_ticker_try = True

    # If Finnhub search returned results, try to pick a stock/common-stock
    if fh_search and "result" in fh_search and len(fh_search["result"]) > 0:
        # pick first match with type 'Common Stock' or best match
        for r in fh_search["result"]:
            # r contains: description, displaySymbol, symbol, type
            # prioritise common stock and matches in description
            if r.get("type") == "Common Stock":
                candidate = {
                    "symbol": r.get("symbol"),
                    "display": r.get("description") or r.get("displaySymbol") or r.get("symbol"),
                    "type": "stock",
                }
                break
        if not candidate:
            # fallback to first result
            top = fh_search["result"][0]
            candidate = {
                "symbol": top.get("symbol"),
                "display": top.get("description") or top.get("displaySymbol") or top.get("symbol"),
                "type": top.get("type") or "stock"
            }

    # If user typed a direct ticker-like, override candidate to that symbol
    if maybe_ticker_try and not candidate:
        candidate = {"symbol": q.upper(), "display": q.upper(), "type": "stock"}

    # 2) If candidate is found and likely stock -> use Finnhub quote + yfinance history fallback
    if candidate and candidate["type"] in ("Common Stock", "stock", "ETF", "Index"):
        symbol = candidate["symbol"]
        # attempt to fetch Finnhub quote
        quote = finnhub_quote(symbol)
        if quote and quote.get("c", 0) != 0:
            # Finnhub returned quote
            current_price = quote.get("c", 0.0)
            # get history via yfinance to compute vol/returns
            try:
                yf_symbol = symbol
                # If symbol contains '^' or unusual char, replace for yfinance best-effort
                yf_ticker = yf.Ticker(yf_symbol)
                hist = yf_ticker.history(period="7d", interval="1d")
                closes = hist["Close"].tolist() if not hist.empty else []
            except Exception:
                closes = []
            # fallback: use Finnhub's h/l/pc to build a simple price list
            if not closes:
                # create synthetic history from pc and c
                prev_close = quote.get("pc", None)
                if prev_close:
                    closes = [prev_close, current_price]
                else:
                    closes = [current_price]
            cur, vol, exp_ret = compute_stats_from_history(closes)
            asset_type = "stock"
            market = "Finnhub"
            # detect INR (NSE) if symbol endswith .NS or symbol contains NSE etc.
            if symbol.upper().endswith(".NS") or "NSE" in symbol.upper() or ".BO" in symbol.upper():
                currency = "INR"
            else:
                # if Finnhub indicates currency in other endpoints: we skip for now
                currency = "USD"
            # If INR needed but price in USD, convert
            if currency == "INR" and cur is not None:
                # if price looks like USD (small decimal) attempt convert
                # we'll convert cur USD->INR using exchangerate.host
                conv = convert_currency(cur, "USD", "INR")
                if conv:
                    cur_inr = conv
                else:
                    cur_inr = cur
            else:
                cur_inr = cur
            est_val = None
            gain_loss = None
            if cur is not None:
                # If currency is INR and user amount might be INR, we must preserve currency in result.
                est_val = amount  # we'll compute estimated value based on expected_return
                # Apply expected return (simple)
                try:
                    est_value_calc = amount * (1 + exp_ret) if exp_ret is not None else amount
                    est_val = safe_round(est_value_calc, 2)
                    gain_loss = safe_round(est_val - amount, 2)
                except Exception:
                    est_val = amount
                    gain_loss = 0.0
            analysis = {
                "asset": candidate["display"],
                "type": asset_type,
                "symbol": symbol,
                "market": market,
                "currency": currency,
                "current_price": safe_round(cur_inr, 4) if cur_inr is not None else None,
                "volatility": safe_round(vol, 3),
                "expected_return": safe_round(exp_ret, 3),
                "risk_category": risk_category_from_vol(vol),
                "holding_period": holding_period_by_asset_type(asset_type),
                "est_value": est_val,
                "gain_loss": gain_loss,
                "ai_recommendation": f"{candidate['display']} shows {risk_category_from_vol(vol).lower()} risk and {safe_round(vol,3)} volatility."
            }
            return analysis

    # 3) Try CoinGecko for crypto (search)
    cg = coingecko_search(q)
    if cg and "coins" in cg and len(cg["coins"]) > 0:
        coin = cg["coins"][0]  # top match
        coin_id = coin.get("id")
        price_info = coingecko_price_by_id(coin_id, vs_currencies="usd,inr")
        if price_info and coin_id in price_info:
            usd_price = price_info[coin_id].get("usd", 0.0)
            inr_price = price_info[coin_id].get("inr", None)
            # Crypto volatility estimate: use 30-day OHLC? CoinGecko has market_chart but we'll approximate
            # For simplicity set a default high volatility if no historical data
            vol = 0.07
            exp_ret = 0.0
            est_value = amount * (1 + exp_ret)
            gain_loss = safe_round(est_value - amount, 2)
            analysis = {
                "asset": coin.get("name"),
                "type": "crypto",
                "symbol": coin.get("symbol"),
                "market": "CoinGecko",
                "currency": "USD",
                "current_price": safe_round(usd_price, 6),
                "inr_price": safe_round(inr_price, 4) if inr_price is not None else None,
                "volatility": vol,
                "expected_return": exp_ret,
                "risk_category": "High",
                "holding_period": holding_period_by_asset_type("crypto"),
                "est_value": safe_round(est_value, 2),
                "gain_loss": gain_loss,
                "ai_recommendation": f"{coin.get('name')} is a crypto asset with high volatility. Only suitable for aggressive investors."
            }
            return analysis

    # 4) Fallback: try yfinance by symbol guesses
    # Try raw input, and input + .NS (NSE) and input + .BO (BSE) and prefix exchanges
    guesses = [q, q.upper(), f"{q.upper()}.NS", f"{q.upper()}.BO"]
    for g in guesses:
        try:
            t = yf.Ticker(g)
            hist = t.history(period="7d", interval="1d")
            closes = hist["Close"].tolist() if not hist.empty else []
            if closes:
                cur, vol, exp_ret = compute_stats_from_history(closes)
                curr_price = cur
                asset_type = "stock"
                market = "yfinance"
                # detect currency: if .NS or .BO -> INR
                currency = "INR" if g.endswith(".NS") or g.endswith(".BO") else "USD"
                est_val = amount * (1 + exp_ret) if exp_ret is not None else amount
                gain_loss = safe_round(est_val - amount, 2)
                analysis = {
                    "asset": g,
                    "type": asset_type,
                    "symbol": g,
                    "market": market,
                    "currency": currency,
                    "current_price": safe_round(curr_price, 4) if curr_price is not None else None,
                    "volatility": safe_round(vol, 3),
                    "expected_return": safe_round(exp_ret, 3),
                    "risk_category": risk_category_from_vol(vol),
                    "holding_period": holding_period_by_asset_type("stock"),
                    "est_value": safe_round(est_val, 2),
                    "gain_loss": gain_loss,
                    "ai_recommendation": f"{g} shows {risk_category_from_vol(vol).lower()} risk and {safe_round(vol,3)} volatility."
                }
                return analysis
        except Exception:
            continue

    # 5) If everything fails, return helpful message
    raise HTTPException(status_code=404, detail="Unable to identify asset from query. Try ticker (AAPL / RELIANCE.NS), crypto name (bitcoin), or company name (Apple).")

# === Routes ===
@app.get("/")
def home():
    return {"status": "ok", "message": "NexaVest Backend running."}

@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    if not req.query or req.query.strip() == "":
        raise HTTPException(status_code=400, detail="Please provide a query (company/ticker/crypto/fund).")
    try:
        result = detect_and_analyze(req.query, req.amount or 0.0)
        return result
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")
