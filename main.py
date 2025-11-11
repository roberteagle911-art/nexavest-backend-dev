from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import requests
from datetime import datetime

app = FastAPI(title="NexaVest Realtime API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/ping")
def ping():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}

def get_stock_price(symbol: str):
    url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={symbol}"
    r = requests.get(url, timeout=10).json()
    try:
        quote = r["quoteResponse"]["result"][0]
        price = quote.get("regularMarketPrice")
        curr = quote.get("currency", "USD")
        if price is None:
            raise ValueError
        return price, curr
    except Exception:
        raise HTTPException(status_code=404, detail="Stock not found")

def get_crypto_price(symbol: str):
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={symbol.lower()}&vs_currencies=usd"
    r = requests.get(url, timeout=10).json()
    if symbol.lower() not in r:
        raise HTTPException(status_code=404, detail="Crypto not found")
    return r[symbol.lower()]["usd"], "USD"

def get_forex_price(pair: str):
    try:
        base, quote = pair.upper().split("/")
        url = f"https://api.exchangerate.host/latest?base={base}&symbols={quote}"
        data = requests.get(url, timeout=10).json()
        return data["rates"][quote], quote
    except Exception:
        raise HTTPException(status_code=404, detail="Forex pair invalid")

@app.post("/analyze")
def analyze(payload: dict):
    asset = payload.get("asset", "").strip()
    amount = float(payload.get("amount", 0))
    if not asset or amount <= 0:
        raise HTTPException(status_code=400, detail="Provide asset and amount")

    if "/" in asset:
        price, currency = get_forex_price(asset)
        atype = "forex"
    elif asset.lower() in ["bitcoin","btc","ethereum","eth","dogecoin","solana","sol"]:
        price, currency = get_crypto_price(asset)
        atype = "crypto"
    else:
        price, currency = get_stock_price(asset)
        atype = "stock"

    risk = "High" if atype=="crypto" else ("Medium" if atype=="forex" else "Low")
    est_val = round(amount * (1 + (0.05 if atype=="stock" else 0.02)),2)

    return {
        "asset": asset.upper(),
        "type": atype,
        "currency": currency,
        "current_price": price,
        "risk": risk,
        "expected_return": "5%" if atype=="stock" else "2%" if atype=="forex" else "8%",
        "holding_period": "12+ months" if atype=="stock" else "6-12 months" if atype=="forex" else "Short",
        "estimated_value": est_val,
        "summary": f"{asset.upper()} detected as {atype}. Risk level {risk}. Estimated value {est_val} {currency}.",
        "disclaimer": "Informational only – not financial advice."
    }
