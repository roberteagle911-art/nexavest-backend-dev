from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import requests
import yfinance as yf

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/ping")
def ping():
    return {"status": "ok"}

@app.post("/analyze")
def analyze(asset: dict):
    try:
        name = asset.get("asset", "").upper()
        amount = float(asset.get("amount", 0))

        if not name:
            raise HTTPException(status_code=400, detail="Asset name required")

        # Handle crypto
        if "-" in name or "/" in name:
            pair = name.replace("/", "-").upper()
            url = f"https://api.coingecko.com/api/v3/simple/price?ids={pair.split('-')[0].lower()}&vs_currencies={pair.split('-')[1].lower()}"
            data = requests.get(url).json()
            if not data:
                raise HTTPException(status_code=404, detail="Crypto pair not found")
            price = list(data.values())[0][pair.split('-')[1].lower()]
            return {"asset": name, "type": "crypto", "price": price, "investment": amount}

        # Handle stocks/forex
        ticker = yf.Ticker(name)
        info = ticker.info
        price = info.get("currentPrice") or info.get("regularMarketPrice")

        if not price:
            raise HTTPException(status_code=404, detail="Asset not found")

        return {
            "asset": name,
            "type": info.get("quoteType", "stock"),
            "price": price,
            "currency": info.get("currency", "USD"),
            "investment": amount,
            "est_value": round(amount / price * price, 2),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
