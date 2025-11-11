from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import requests
from datetime import datetime

app = FastAPI(title="NexaVest Live Backend")

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

def search_symbol_by_name(name):
    url = f"https://query2.finance.yahoo.com/v1/finance/search?q={name}"
    data = requests.get(url, timeout=10).json()
    if "quotes" in data and data["quotes"]:
        return data["quotes"][0]["symbol"]
    raise HTTPException(status_code=404, detail="Company not found")

def get_stock_price(symbol):
    url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={symbol}"
    r = requests.get(url, timeout=10).json()
    result = r.get("quoteResponse", {}).get("result", [])
    if not result:
        raise HTTPException(status_code=404, detail="Stock not found")
    info = result[0]
    return info.get("regularMarketPrice"), info.get("currency", "USD")

def get_crypto_price(symbol):
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={symbol.lower()}&vs_currencies=usd"
    r = requests.get(url, timeout=10).json()
    if symbol.lower() not in r:
        raise HTTPException(status_code=404, detail="Crypto not found")
    return r[symbol.lower()]["usd"], "USD"

def get_forex_rate(pair):
    base, quote = pair.upper().split("/")
    url = f"https://api.exchangerate.host/latest?base={base}&symbols={quote}"
    r = requests.get(url, timeout=10).json()
    if "rates" not in r or quote not in r["rates"]:
        raise HTTPException(status_code=404, detail="Invalid forex pair")
    return r["rates"][quote], quote

@app.post("/analyze")
def analyze(data: dict):
    asset = data.get("asset", "").strip()
    amount = float(data.get("amount", 0))
    if not asset or amount <= 0:
        raise HTTPException(status_code=400, detail="Provide valid asset and amount")

    # Detect and normalize asset
    atype = "stock"
    price = 0
    currency = "USD"

    if "/" in asset:
        atype = "forex"
        price, currency = get_forex_rate(asset)
    elif asset.lower() in ["bitcoin","btc","eth","ethereum","solana","dogecoin","bnb"]:
        atype = "crypto"
        price, currency = get_crypto_price(asset)
    else:
        symbol = search_symbol_by_name(asset)
        price, currency = get_stock_price(symbol)

    # Simple metrics
    if atype == "crypto":
        risk, ret, hold = "High", "8%", "Short-term"
    elif atype == "forex":
        risk, ret, hold = "Medium", "2%", "6-12 months"
    else:
        risk, ret, hold = "Low", "5%", "12+ months"

    est_val = round(amount * (1 + float(ret.strip('%'))/100), 2)

    return {
        "asset": asset.upper(),
        "type": atype,
        "currency": currency,
        "current_price": price,
        "expected_return": ret,
        "risk": risk,
        "holding_period": hold,
        "estimated_value": est_val,
        "summary": f"{asset.title()} detected as {atype} with {risk} risk and expected return of {ret}.",
        "disclaimer": "Informational only – not financial advice."
    }

@app.get("/disclaimer")
def disclaimer():
    return {"text": "This tool provides informational analysis only. It is not financial advice."}
