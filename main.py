from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import requests
import yfinance as yf
from forex_python.converter import CurrencyRates
from datetime import datetime

app = FastAPI(title="NexaVest Real-Time Market Analyzer")

# --- Enable CORS for frontend communication ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Ping route for health check ---
@app.get("/ping")
def ping():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

# --- Helper to fetch live crypto price ---
def fetch_crypto(symbol: str):
    symbol = symbol.lower()
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={symbol}&vs_currencies=usd"
    r = requests.get(url).json()
    if symbol not in r:
        raise HTTPException(status_code=404, detail="Crypto not found")
    return r[symbol]["usd"]

# --- Helper to fetch forex price ---
def fetch_forex(pair: str):
    c = CurrencyRates()
    try:
        base, quote = pair.upper().split("/")
        rate = c.get_rate(base, quote)
        return rate
    except Exception:
        raise HTTPException(status_code=404, detail="Invalid forex pair")

# --- Main analysis endpoint ---
@app.post("/analyze")
def analyze(data: dict):
    try:
        asset = data.get("asset", "").strip()
        amount = float(data.get("amount", 0))

        if not asset:
            raise HTTPException(status_code=400, detail="Asset name required")

        # Detect type
        result = {"asset": asset}

        # --- Crypto Detection ---
        if asset.lower() in ["bitcoin", "btc", "eth", "ethereum", "dogecoin", "solana"]:
            price = fetch_crypto(asset.lower())
            result.update({
                "type": "crypto",
                "symbol": asset.upper(),
                "currency": "USD",
                "current_price": price,
                "market": "Crypto",
                "expected_return": 0.08,
                "volatility": "High",
                "risk": "High",
                "est_value": round(amount * (1 + 0.08), 2)
            })
            return result

        # --- Forex Detection ---
        if "/" in asset:
            rate = fetch_forex(asset)
            result.update({
                "type": "forex",
                "symbol": asset.upper(),
                "currency": "Quote Currency",
                "current_price": rate,
                "market": "Forex",
                "expected_return": 0.02,
                "volatility": "Medium",
                "risk": "Medium",
                "est_value": round(amount * (1 + 0.02), 2)
            })
            return result

        # --- Stock Detection ---
        ticker = yf.Ticker(asset)
        info = ticker.info
        price = info.get("currentPrice") or info.get("regularMarketPrice")

        if not price:
            raise HTTPException(status_code=404, detail="Stock not found")

        result.update({
            "type": "stock",
            "symbol": asset.upper(),
            "market": info.get("exchange", "Unknown"),
            "currency": info.get("currency", "USD"),
            "current_price": price,
            "expected_return": 0.05,
            "volatility": "Moderate",
            "risk": "Medium",
            "est_value": round(amount * (1 + 0.05), 2)
        })
        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- Legal disclaimer route ---
@app.get("/disclaimer")
def disclaimer():
    return {
        "message": (
            "This tool provides informational analysis only. "
            "It is NOT financial advice or a forecast. "
            "Past performance is not indicative of future results. "
            "Always do your own research."
        )
    }
