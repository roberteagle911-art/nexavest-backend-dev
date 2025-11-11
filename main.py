# main.py
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import math

app = FastAPI(title="NexaVest Backend (Dev)")

# Allow your frontend domains here (or "*" for dev)
origins = ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalyzeRequest(BaseModel):
    asset: str
    amount: float


@app.get("/ping")
async def ping():
    return {"status": "ok", "message": "NexaVest backend running"}


def detect_asset_type(asset: str):
    """Simple heuristic to detect asset type.
       - forex pairs: contain '/' (e.g. 'USD/INR', 'XAU/USD')
       - crypto: contains 'coin' or endswith 'usd' or common crypto names
       - stock: otherwise treat as stock/code
    """
    a = asset.strip().lower()
    # forex detection
    if "/" in a or len(a.split()) == 1 and any(sep in a for sep in ["/"]):
        return "forex"
    # common crypto clues
    crypto_clues = ["coin", "btc", "eth", "bnb", "doge", "usdt", "usdc", "sol", "avax", "ada", "matic"]
    if any(clue in a for clue in crypto_clues) or a.endswith("usd") or a.endswith("btc"):
        return "crypto"
    # fallback: stock
    return "stock"


def mock_price_for(asset_type: str, asset: str):
    """Return a mock current price for dev/testing (not production).
       In prod, you should call a real price API (Yahoo/AlphaVantage/CoinGecko).
    """
    base = 100.0
    if asset_type == "crypto":
        # crypto can be volatile / smaller unit:
        if "btc" in asset.lower():
            return 60000.0
        if "eth" in asset.lower():
            return 3500.0
        return 2.5  # small alt coin
    if asset_type == "forex":
        # for XAU/USD (gold) give a large value, else typical forex ~1-80
        if "xau" in asset.lower() or "gold" in asset.lower():
            return 2000.0
        return 75.0
    # stock
    # if user provided symbol like AAPL or Apple, give some reasonable stock price
    if "aapl" in asset.lower() or "apple" in asset.lower():
        return 268.47
    if "reliance" in asset.lower() or ".ns" in asset.lower():
        return 1489.30
    # generic
    return base


def mock_volatility_for(asset_type: str):
    if asset_type == "crypto":
        return 0.07
    if asset_type == "forex":
        return 0.02
    return 0.017


def suggest_risk(vol):
    if vol is None:
        return "Unknown"
    if vol >= 0.06:
        return "High"
    if vol >= 0.02:
        return "Medium"
    return "Low"


def suggest_holding_period(asset_type: str, risk_level: str):
    if asset_type == "crypto":
        return "Short (crypto is highly volatile)"
    if risk_level == "High":
        return "Short-term (weeks to months)"
    if risk_level == "Medium":
        return "6-12 months"
    return "12+ months"


@app.post("/analyze")
async def analyze(req: AnalyzeRequest):
    asset = req.asset.strip()
    amount = req.amount
    if not asset or amount is None or amount <= 0:
        raise HTTPException(status_code=400, detail="Provide valid 'asset' and positive 'amount'.")

    asset_type = detect_asset_type(asset)
    current_price = mock_price_for(asset_type, asset)
    volatility = mock_volatility_for(asset_type)
    expected_return = -0.005 if asset_type == "stock" else (0.0 if asset_type == "crypto" else 0.0)

    # compute estimated value after expected return (simple model)
    est_value = round(amount * (1 + expected_return), 2)
    gain_loss_value = round(est_value - amount, 2)

    risk = suggest_risk(volatility)
    holding = suggest_holding_period(asset_type, risk)

    # build a short human-friendly summary (safest possible language)
    summary = (
        f"{asset} shows {risk.lower()} risk with volatility {volatility:.3f}. "
        f"This is an informational analysis only — not financial advice."
    )

    response = {
        "asset": asset,
        "type": asset_type,
        "symbol": asset.upper(),
        "market": "mock",
        "currency": "INR" if ".ns" in asset.lower() or "reliance" in asset.lower() else ("USD" if asset_type != "forex" else "USD"),
        "current_price": round(current_price, 2),
        "volatility": round(volatility, 3),
        "expected_return": expected_return,
        "risk": risk,
        "holding_period": holding,
        "estimated_value": est_value,
        "gain_loss": gain_loss_value,
        "summary": summary,
    }
    return response
