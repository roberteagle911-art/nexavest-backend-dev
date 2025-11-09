from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import yfinance as yf

app = FastAPI(title="NexaVest Backend (Dev)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FINNHUB_API_KEY = "d47qudpr01qk80bi464gd47qudpr01qk80bi4650"
FINNHUB_URL = "https://finnhub.io/api/v1/quote"


class AnalyzeRequest(BaseModel):
    symbol: str
    amount: float


@app.get("/")
def home():
    return {"status": "ok", "message": "NexaVest Backend (Dev) running successfully"}


@app.post("/analyze")
def analyze_stock(request: AnalyzeRequest):
    symbol = request.symbol.upper()
    amount = request.amount

    try:
        # Try getting live data from Finnhub first
        res = requests.get(f"{FINNHUB_URL}?symbol={symbol}&token={FINNHUB_API_KEY}")
        data = res.json()

        if "c" in data and data["c"] != 0:
            current_price = data["c"]
            prev_close = data["pc"]
        else:
            raise Exception("Finnhub returned no data")

    except Exception:
        # Fallback to Yahoo Finance if Finnhub fails
        try:
            stock = yf.Ticker(symbol)
            hist = stock.history(period="5d")
            current_price = float(hist["Close"].iloc[-1])
            prev_close = float(hist["Close"].iloc[-2])
        except Exception:
            raise HTTPException(status_code=404, detail="Invalid stock symbol")

    # Calculate metrics
    volatility = round(abs(current_price - prev_close) / current_price, 3)
    expected_return = round((current_price - prev_close) / prev_close, 3)

    # Determine risk level
    if volatility < 0.02:
        risk = "Low"
    elif volatility < 0.05:
        risk = "Medium"
    else:
        risk = "High"

    # Calculate estimated value and gain/loss
    estimated_value = round(amount * (1 + expected_return), 2)
    gain_loss = round(estimated_value - amount, 2)

    # AI-like recommendation text
    ai_recommendation = (
        f"{symbol} is showing {risk.lower()} risk and {volatility} volatility. "
        f"If you invest ${amount}, your estimated value could be around ${estimated_value} "
        f"({'gain' if gain_loss > 0 else 'loss'} of ${abs(gain_loss)}). "
        f"This is ideal for {'conservative' if risk == 'Low' else 'balanced' if risk == 'Medium' else 'aggressive'} investors."
    )

    return {
        "symbol": symbol,
        "current_price": round(current_price, 2),
        "volatility": volatility,
        "expected_return": expected_return,
        "risk_category": risk,
        "estimated_value": estimated_value,
        "gain_loss": gain_loss,
        "ai_recommendation": ai_recommendation,
            }
