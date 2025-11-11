from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import yfinance as yf
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="NexaVest AI - Smart Market Analyzer")

# Allow frontend calls
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class AnalyzeRequest(BaseModel):
    asset: str
    amount: float
    amount_currency: str

# --- Smart normalization ---
def normalize_asset_name(asset: str) -> str:
    asset = asset.strip().upper()

    # Crypto
    if asset in ["BTC", "ETH", "DOGE", "SOL", "XRP"]:
        return f"{asset}-USD"

    # Forex
    if "/" in asset or "-" in asset:
        return asset.replace("/", "-").upper()

    # Indian stocks
    indian_map = {
        "RELIANCE": "RELIANCE.NS",
        "INFY": "INFY.NS",
        "TCS": "TCS.NS",
        "HDFC": "HDFCBANK.NS",
        "ICICI": "ICICIBANK.NS",
        "SBIN": "SBIN.NS",
        "ADANI": "ADANIENT.NS",
        "ONGC": "ONGC.NS",
        "LT": "LT.NS"
    }

    if asset in indian_map:
        return indian_map[asset]

    # Default → assume U.S. ticker
    return asset

@app.post("/analyze")
async def analyze_asset(req: AnalyzeRequest):
    symbol = normalize_asset_name(req.asset)
    data = yf.Ticker(symbol)

    try:
        info = data.info
        price = info.get("regularMarketPrice")
        if price is None:
            raise ValueError("No market data available")

        name = info.get("longName", symbol)
        currency = info.get("currency", req.amount_currency)

        beta = info.get("beta", 1)
        risk = "Low" if beta < 0.8 else "Moderate" if beta < 1.2 else "High"
        expected_return = f"{round(beta * 7, 2)}%"

        return {
            "asset": name,
            "symbol": symbol,
            "currency": currency,
            "current_price": price,
            "risk": risk,
            "expected_return": expected_return,
            "holding_period": "6–12 months",
            "suggestion": "Hold or accumulate on dips" if risk != "High" else "Watch for volatility",
            "disclaimer": "Informational analysis only. Not financial advice or forecast."
        }

    except Exception:
        raise HTTPException(status_code=404, detail="Stock/company not found")

@app.get("/")
def home():
    return {"message": "NexaVest backend is live 🚀"}
