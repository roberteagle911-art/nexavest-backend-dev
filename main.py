# main.py
"""
NexaVest — Real-time market analyzer (FastAPI)
Designed for deployment on Render (or any Python host).
Features:
 - /ping health check
 - /analyze POST endpoint: { "asset": "<name or ticker or pair>", "amount": <number>, "amount_currency": "USD"|"INR"|... (optional) }
 - auto-detects stock / crypto / forex
 - company name -> ticker search (Yahoo search)
 - live quote + historical returns (90 days) -> volatility, annualized return
 - risk classification and suggested holding period
 - returns currency-aware estimated values and summary
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict, Any
import requests
import yfinance as yf
import numpy as np
from datetime import datetime, timedelta
import math
import time

app = FastAPI(title="NexaVest Live Backend")

# CORS for frontend (set to your frontend domain in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Configurable parameters ----------
HIST_DAYS = 90  # days of history used for volatility & mean return
ANNUAL_TRADING_DAYS = 252
COINGECKO_TIMEOUT = 10
YAHOO_TIMEOUT = 10
FOREX_TIMEOUT = 10

# ---------- Request/Response models ----------
class AnalyzeRequest(BaseModel):
    asset: str
    amount: float
    amount_currency: Optional[str] = None  # if user specifies the currency of amount, else assume same as asset currency

# ---------- Utilities ----------
def now_iso():
    return datetime.utcnow().isoformat()

def safe_get_json(url, timeout=10, params=None, headers=None):
    try:
        r = requests.get(url, timeout=timeout, params=params, headers=headers)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        raise RuntimeError(f"Failed to fetch {url}: {e}")

def search_yahoo_symbol(name: str) -> Optional[str]:
    """Search Yahoo Finance for a company name -> return best symbol (may include .NS or .BO for India)."""
    url = "https://query2.finance.yahoo.com/v1/finance/search"
    try:
        data = safe_get_json(url, timeout=YAHOO_TIMEOUT, params={"q": name})
        quotes = data.get("quotes", [])
        if not quotes:
            return None
        # prefer EQUITY or ETF; try to find an Indian listing if name contains India/Kerala etc
        for q in quotes:
            qt = q.get("quoteType", "").upper()
            if qt in ("EQUITY", "ETF"):
                return q.get("symbol")
        # fallback to first symbol
        return quotes[0].get("symbol")
    except Exception:
        return None

def get_yahoo_quote(symbol: str) -> Dict[str, Any]:
    """Return latest price and currency and raw quote dict for symbol."""
    url = "https://query1.finance.yahoo.com/v7/finance/quote"
    data = safe_get_json(url, params={"symbols": symbol}, timeout=YAHOO_TIMEOUT)
    res = data.get("quoteResponse", {}).get("result", [])
    if not res:
        raise HTTPException(status_code=404, detail=f"No quote for symbol {symbol}")
    q = res[0]
    price = q.get("regularMarketPrice") or q.get("postMarketPrice") or q.get("regularMarketPreviousClose")
    currency = q.get("currency") or "USD"
    return {"price": price, "currency": currency, "raw": q}

def fetch_yahoo_history(symbol: str, days: int = HIST_DAYS) -> np.ndarray:
    """Return numpy array of daily close prices for last `days` trading days."""
    end = datetime.utcnow().date()
    start = end - timedelta(days=int(days * 1.8))  # window to ensure enough trading days
    try:
        tk = yf.Ticker(symbol)
        hist = tk.history(start=start.isoformat(), end=end.isoformat(), interval="1d", actions=False, threads=False)
        # hist index may include weekends trimmed; take last `days` rows with 'Close'
        closes = hist["Close"].dropna().values
        if len(closes) < 5:
            raise RuntimeError("Not enough history")
        return np.array(closes[-days:])
    except Exception as e:
        raise RuntimeError(f"Failed to fetch history for {symbol}: {e}")

def coin_gecko_price(query: str):
    """Search coin and return price in USD with id and symbol."""
    # search to discover coin id
    search_url = f"https://api.coingecko.com/api/v3/search"
    try:
        data = safe_get_json(search_url, timeout=COINGECKO_TIMEOUT, params={"query": query})
        coins = data.get("coins", [])
        if not coins:
            return None
        coin = coins[0]  # best match
        cid = coin.get("id")
        price_data = safe_get_json(f"https://api.coingecko.com/api/v3/simple/price", timeout=COINGECKO_TIMEOUT,
                                   params={"ids": cid, "vs_currencies": "usd"})
        price = price_data.get(cid, {}).get("usd")
        if price is None:
            return None
        return {"id": cid, "symbol": coin.get("symbol").upper(), "name": coin.get("name"), "price": price, "currency": "USD"}
    except Exception:
        return None

def forex_rate(pair: str):
    """Return rate for a pair like 'USD/INR' using exchangerate.host"""
    p = pair.upper().replace(" ", "")
    if "/" not in p and len(p) == 6:
        p = p[:3] + "/" + p[3:]
    if "/" not in p:
        return None
    base, quote = p.split("/")
    try:
        data = safe_get_json("https://api.exchangerate.host/latest", timeout=FOREX_TIMEOUT, params={"base": base, "symbols": quote})
        rate = data.get("rates", {}).get(quote)
        if rate is None:
            return None
        return {"pair": f"{base}/{quote}", "price": float(rate), "currency": quote}
    except Exception:
        return None

def compute_vol_and_annual_return(prices: np.ndarray):
    """
    Compute daily returns, mean daily return, daily std, then annualize:
      - annual_volatility = std_daily * sqrt(ANNUAL_TRADING_DAYS)
      - annual_return = mean_daily * ANNUAL_TRADING_DAYS
    Returns (annual_volatility, annual_return)
    """
    if len(prices) < 3:
        return None, None
    # compute logarithmic returns for stability
    returns = np.diff(np.log(prices))
    mean_daily = float(np.mean(returns))
    std_daily = float(np.std(returns, ddof=0))
    annual_vol = std_daily * math.sqrt(ANNUAL_TRADING_DAYS)
    annual_ret = mean_daily * ANNUAL_TRADING_DAYS  # approx
    return round(float(annual_vol), 6), round(float(annual_ret), 6)

def classify_risk_by_vol(annual_vol: float):
    """
    Classify risk by annualized volatility:
      - Low: vol < 0.20 (20%)
      - Medium: 0.20 <= vol < 0.5
      - High: vol >= 0.5
    These thresholds are tunable.
    """
    if annual_vol is None:
        return "Unknown"
    if annual_vol >= 0.5:
        return "High"
    if annual_vol >= 0.2:
        return "Medium"
    return "Low"

def suggest_holding(risk_label: str, annual_return: Optional[float]):
    if risk_label == "High":
        return "Short (days to months)"
    if risk_label == "Medium":
        return "6-12 months"
    if risk_label == "Low":
        return "12+ months"
    # fallback using expected return
    if annual_return is not None and annual_return > 0.15:
        return "6-12 months"
    return "6-12 months"

def currency_convert(amount: float, from_currency: str, to_currency: str):
    """Convert amount using exchangerate.host (live). Returns converted amount and rate used."""
    if from_currency.upper() == to_currency.upper():
        return amount, 1.0
    try:
        res = safe_get_json("https://api.exchangerate.host/convert", params={"from": from_currency, "to": to_currency, "amount": amount})
        if res and "result" in res:
            return float(res["result"]), float(res.get("info", {}).get("rate", 1.0))
    except Exception:
        pass
    raise RuntimeError("Currency conversion failed")

# ---------- End utilities ----------

@app.get("/ping")
def ping():
    return {"status": "ok", "time": now_iso()}

@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    """
    Request body:
      { "asset": "Reliance" | "RELIANCE.NS" | "AAPL" | "BTC" | "USD/INR", "amount": 1000, "amount_currency": "INR" (optional) }
    Response includes live price, volatility, annualized return, risk_label, suggestion, estimated_value (in asset currency),
    and if amount_currency provided, also shows converted amounts.
    """
    asset_input = req.asset.strip()
    amount = float(req.amount)
    amount_currency = (req.amount_currency or "").upper() if req.amount_currency else None

    if not asset_input or amount <= 0:
        raise HTTPException(status_code=400, detail="Provide valid 'asset' and positive 'amount'")

    # 1) Detect asset class
    lower = asset_input.lower()
    is_forex = "/" in asset_input or (len(asset_input.replace(" ", "")) == 6 and asset_input[:3].isalpha() and asset_input[3:].isalpha())
    # Common crypto identifiers
    crypto_tokens = ["btc", "bitcoin", "eth", "ethereum", "bnb", "doge", "dogecoin", "sol", "solana", "ada", "matic", "ltc", "avax"]
    is_crypto = any(tok in lower for tok in crypto_tokens)

    try:
        if is_forex:
            # Forex pair
            fx = forex_rate(asset_input)
            if not fx:
                raise HTTPException(status_code=404, detail="Forex pair not found")
            cur = fx["currency"]
            current_price = float(fx["price"])
            # volatility & returns aren't meaningful same as stocks — use defaults
            annual_vol = 0.12
            annual_ret = 0.02
            risk = classify_risk_by_vol(annual_vol)
            holding = suggest_holding(risk, annual_ret)
            est_value = round(amount * (1 + annual_ret), 2)
            resp = {
                "asset": fx["pair"],
                "type": "forex",
                "currency": cur,
                "current_price": current_price,
                "volatility": annual_vol,
                "annual_return": annual_ret,
                "risk": risk,
                "holding_period": holding,
                "estimated_value": est_value,
                "summary": f"Forex pair {fx['pair']} rate {current_price} {cur}.",
                "disclaimer": "Informational only. Not financial advice."
            }
            # convert amount if user provided a different amount_currency
            if amount_currency and amount_currency != cur:
                try:
                    conv, rate = currency_convert(amount, amount_currency, cur)
                    resp["amount_in_asset_currency"] = round(conv, 4)
                    resp["conversion_rate"] = rate
                except Exception:
                    resp["conversion_error"] = "Conversion failed"
            return resp

        if is_crypto:
            cg = coin_gecko_price(asset_input)
            if not cg:
                # try exact symbol uppercase maybe
                cg = coin_gecko_price(lower)
            if not cg:
                raise HTTPException(status_code=404, detail="Crypto not found")
            price = float(cg["price"])
            # use typical crypto vol/return assumptions
            # compute simple historic pct via CoinGecko market_chart (7d) if available (optional)
            annual_vol = 0.9  # high by default (90%)
            annual_ret = 0.25  # assumed
            risk = classify_risk_by_vol(annual_vol)
            holding = suggest_holding(risk, annual_ret)
            est_value = round(amount * (1 + annual_ret), 2)
            resp = {
                "asset": cg["name"],
                "symbol": cg["symbol"],
                "type": "crypto",
                "currency": "USD",
                "current_price": price,
                "volatility": annual_vol,
                "annual_return": annual_ret,
                "risk": risk,
                "holding_period": holding,
                "estimated_value": est_value,
                "summary": f"{cg['name']} price {price} USD (CoinGecko).",
                "disclaimer": "Informational only. Not financial advice."
            }
            if amount_currency and amount_currency != "USD":
                try:
                    conv, rate = currency_convert(amount, amount_currency, "USD")
                    resp["amount_in_USD"] = round(conv, 4)
                    resp["conversion_rate"] = rate
                except Exception:
                    resp["conversion_error"] = "Conversion failed"
            return resp

        # Otherwise treat as stock / company
        # If user supplied ticker (contains '.', or all uppercase short codes), accept directly; else search by company name
        symbol_candidate = asset_input.upper()
        # allow inputs like "reliance" -> prefer search symbol
        found_symbol = None
        # if looks like explicit symbol (contains dot like .NS or all uppercase letters numbers and maybe dot)
        if "." in symbol_candidate or (symbol_candidate.isalnum() and len(symbol_candidate) <= 6):
            # try direct quote first
            try:
                q = get_yahoo_quote(symbol_candidate)
                found_symbol = symbol_candidate
            except Exception:
                found_symbol = None
        if not found_symbol:
            found_symbol = search_yahoo_symbol(asset_input)
        if not found_symbol:
            raise HTTPException(status_code=404, detail="Stock/company not found")

        # get live price
        quote = get_yahoo_quote(found_symbol)
        price = float(quote["price"])
        currency = quote["currency"] or "USD"

        # fetch historical close series
        prices = None
        annual_vol = None
        annual_ret = None
        try:
            hist = fetch_yahoo_history(found_symbol, days=HIST_DAYS)
            prices = hist
            annual_vol, annual_ret = compute_vol_and_annual_return(prices)
        except Exception:
            # if history fails, fallback to small defaults
            annual_vol = 0.25
            annual_ret = 0.05

        risk = classify_risk_by_vol(annual_vol)
        holding = suggest_holding(risk, annual_ret)
        # expected_return as percent string
        expected_return_pct = f"{round(float(annual_ret) * 100, 2)}%" if annual_ret is not None else "N/A"
        est_value = round(amount * (1 + (annual_ret if annual_ret is not None else 0.05)), 2)

        resp = {
            "asset": quote["raw"].get("longName") or found_symbol,
            "symbol": found_symbol,
            "type": "stock",
            "exchange": quote["raw"].get("exchange", "Unknown"),
            "currency": currency,
            "current_price": price,
            "volatility_annual": annual_vol,
            "annual_return": annual_ret,
            "expected_return": expected_return_pct,
            "risk": risk,
            "holding_period": holding,
            "estimated_value": est_value,
            "summary": f"{quote['raw'].get('longName') or found_symbol} price {price} {currency}. Annualized volatility {round(annual_vol,4)}.",
            "disclaimer": "Informational only. Not financial advice."
        }

        # If user provided amount_currency and it's different, present converted amount
        if amount_currency and amount_currency != currency:
            try:
                converted, rate = currency_convert(amount, amount_currency, currency)
                resp["amount_in_asset_currency"] = round(converted, 4)
                resp["conversion_rate"] = rate
            except Exception:
                resp["conversion_error"] = "Conversion failed"

        return resp

    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
