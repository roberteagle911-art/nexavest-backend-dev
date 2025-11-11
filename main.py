from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import requests
from datetime import datetime

app = FastAPI(title="NexaVest AI Backend", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/ping")
def ping():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}


def search_symbol(name: str):
    url = f"https://query2.finance.yahoo.com/v1/finance/search?q={name}"
    r = requests.get(url, timeout=10).json()
    if "quotes" in r and r["quotes"]:
        return r["quotes"][0]["symbol"]
    raise HTTPException(status_code=404, detail="Company not found")


def get_stock_price(symbol: str):
    url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={symbol}"
    r = requests.get(url, timeout=10).json()
    q = r.get("quoteResponse", {}).get("result", [])
    if not q:
        raise HTTPException(status_code=404, detail="Stock not found")
    info = q[0]
    return {
        "name": info.get("longName") or symbol,
        "symbol": info.get("symbol"),
        "price": info.get("regularMarketPrice"),
        "currency": info.get("currency", "USD"),
    }


def get_crypto_price(symbol: str):
    search = requests.get(
        f"https://api.coingecko.com/api/v3/search?query={symbol}", timeout=10
    ).json()
    if not search.get("coins"):
        raise HTTPException(status_code=404, detail="Crypto not found")
    coin = search["coins"][0]
    cid = coin["id"]
    price = requests.get(
        f"https://api.coingecko.com/api/v3/simple/price?ids={cid}&vs_currencies=usd",
        timeout=10,
    ).json()
    return {
        "name": coin["name"],
        "symbol": coin["symbol"].upper(),
        "price": price[cid]["usd"],
        "currency": "USD",
    }


def get_forex_rate(pair: str):
    p = pair.upper().replace(" ", "")
    if not "/" in p and len(p) == 6:
        p = f"{p[:3]}/{p[3:]}"
    base, quote = p.split("/")
    r = requests.get(
        f"https://api.exchangerate.host/latest?base={base}&symbols={quote}", timeout=10
    ).json()
    rate = r.get("rates", {}).get(quote)
    if not rate:
        raise HTTPException(status_code=404, detail="Invalid forex pair")
    return {"pair": p, "price": rate, "currency": quote}


@app.post("/analyze")
def analyze(data: dict):
    asset = data.get("asset", "").strip()
    amount = float(data.get("amount", 0))

    if not asset or amount <= 0:
        raise HTTPException(status_code=400, detail="Provide valid asset and amount")

    # Determine asset type
    lower = asset.lower()
    atype = "stock"
    if "/" in lower:
        atype = "forex"
        info = get_forex_rate(asset)
    elif any(c in lower for c in ["btc", "bitcoin", "eth", "doge", "bnb", "sol"]):
        atype = "crypto"
        info = get_crypto_price(asset)
    else:
        symbol = search_symbol(asset)
        info = get_stock_price(symbol)

    price = info["price"]
    currency = info["currency"]

    # Simple metrics
    if atype == "crypto":
        risk, ret, hold = "High", "8%", "Short-term"
    elif atype == "forex":
        risk, ret, hold = "Medium", "2%", "6–12 months"
    else:
        risk, ret, hold = "Low", "5%", "12+ months"

    est_val = round(amount * (1 + float(ret.strip('%')) / 100), 2)

    return {
        "asset": asset,
        "type": atype,
        "currency": currency,
        "current_price": price,
        "risk": risk,
        "expected_return": ret,
        "holding_period": hold,
        "estimated_value": est_val,
        "summary": f"{asset.title()} detected as {atype} with {risk} risk and expected return of {ret}.",
        "disclaimer": "Informational only — not financial advice.",
    }
