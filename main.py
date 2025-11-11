# main.py
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import yfinance as yf
import requests
import statistics
from datetime import datetime, timedelta

app = FastAPI(title="NexaVest Live Backend")

# Allow all origins (for frontend)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Input model
class AnalyzeRequest(BaseModel):
    asset: str
    amount: float


@app.get("/ping")
def ping():
    return {"status": "ok", "message": "NexaVest Live Backend running"}


# Detect asset type
def detect_asset_type(asset: str):
    asset = asset.lower().strip()
    if "/" in asset:
        return "forex"
    if asset.endswith("usd") or any(k in asset for k in ["btc", "eth", "sol", "bnb", "doge"]):
        return "crypto"
    return "stock"


# Get live stock price from Yahoo Finance
def get_stock_price(symbol: str):
    try:
        data = yf.Ticker(symbol)
        info = data.history(period="5d")
        if info.empty:
            raise ValueError("Invalid stock symbol")
        current_price = info["Close"].iloc[-1]
        prices = list(info["Close"])
        vol = statistics.pstdev(prices) / (sum(prices) / len(prices))
        return round(current_price, 2), round(vol, 4)
    except Exception:
        raise HTTPException(status_code=400, detail=f"Unable to fetch stock data for {symbol}")


# Get crypto price from CoinGecko API
def get_crypto_price(symbol: str):
    try:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={symbol}&vs_currencies=usd"
        res = requests.get(url, timeout=10).json()
        if symbol not in res:
            raise ValueError("Invalid crypto symbol")
        price = res[symbol]["usd"]
        return round(price, 2), 0.07  # assume 7% volatility (simplified)
    except Exception:
        raise HTTPException(status_code=400, detail=f"Unable to fetch crypto data for {symbol}")


# Get forex price from exchangerate.host
def get_forex_price(pair: str):
    try:
        base, quote = pair.split("/")
        url = f"https://api.exchangerate.host/latest?base={base.upper()}&symbols={quote.upper()}"
        res = requests.get(url, timeout=10).json()
        rate = res["rates"][quote.upper()]
        return round(rate, 4), 0.02
    except Exception:
        raise HTTPException(status_code=400, detail=f"Unable to fetch forex data for {pair}")


def suggest_risk(vol):
    if vol >= 0.06:
        return "High"
    elif vol >= 0.02:
        return "Medium"
    else:
        return "Low"


def holding_period(asset_type, risk):
    if asset_type == "crypto":
        return "Short (Highly volatile)"
    if risk == "High":
        return "Weeks to months"
    if risk == "Medium":
        return "6-12 months"
    return "12+ months"


@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    asset = req.asset.strip()
    amount = req.amount

    if not asset or amount <= 0:
        raise HTTPException(status_code=400, detail="Enter valid asset and amount")

    asset_type = detect_asset_type(asset)
    currency = "USD"

    # Determine live price
    if asset_type == "stock":
        price, vol = get_stock_price(asset)
    elif asset_type == "crypto":
        price, vol = get_crypto_price(asset)
    elif asset_type == "forex":
        price, vol = get_forex_price(asset)
    else:
        raise HTTPException(status_code=400, detail="Unknown asset type")

    risk = suggest_risk(vol)
    holding = holding_period(asset_type, risk)
    estimated_value = round(amount * price, 2)

    summary = f"{asset.upper()} is classified as a {asset_type} with {risk.lower()} risk. Estimated value is {estimated_value} {currency}. This is an informational analysis only."

    return {
        "asset": asset.upper(),
        "type": asset_type,
        "currency": currency,
        "current_price": price,
        "volatility": vol,
        "risk": risk,
        "holding_period": holding,
        "estimated_value": estimated_value,
        "summary": summary,
        "disclaimer": "This tool provides informational analysis only. It is NOT financial advice or a forecast. Always do your own research.",
                            }
