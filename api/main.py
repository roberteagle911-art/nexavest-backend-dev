from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import yfinance as yf

app = FastAPI(title="NexaVest Backend (Dev)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://nexavest-frontend-dev.vercel.app",
        "http://localhost:5173"
    ],
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
    return {"status": "ok", "message": "NexaVest Backend (Enhanced) ✅"}

@app.post("/analyze")
def analyze_stock(request: AnalyzeRequest):
    symbol = request.symbol.upper()
    amount = request.amount

    try:
        res = requests.get(f"{FINNHUB_URL}?symbol={symbol}&token={FINNHUB_API_KEY}")
        data = res.json()

        if "c" in data and data["c"] != 0:
            current = data["c"]
            high = data["h"]
            low = data["l"]
            prev = data["pc"]
        else:
            stock = yf.Ticker(symbol)
            hist = stock.history(period="5d")
            current = hist["Close"].iloc[-1]
            high = hist["High"].iloc[-1]
            low = hist["Low"].iloc[-1]
            prev = hist["Close"].iloc[-2]

        volatility = round((high - low) / current, 3)
        expected_return = round((current - prev) / prev, 3)

        # Risk Category
        if volatility < 0.02:
            risk = "Low"
        elif volatility < 0.05:
            risk = "Medium"
        else:
            risk = "High"

        # Estimated return in money
        estimated_value = round(amount * (1 + expected_return), 2)
        gain_or_loss = round(estimated_value - amount, 2)
        status = "gain" if gain_or_loss >= 0 else "loss"

        ai_recommendation = (
            f"{symbol} is showing {risk.lower()} risk and {volatility} volatility. "
            f"If you invest ${amount}, your estimated value could be around ${estimated_value} "
            f"({status} of ${abs(gain_or_loss)}). "
            f"This is ideal for {('conservative' if risk == 'Low' else 'balanced' if risk == 'Medium' else 'aggressive')} investors."
        )

        return {
            "symbol": symbol,
            "current_price": round(current, 2),
            "expected_return": expected_return,
            "volatility": volatility,
            "risk_category": risk,
            "estimated_value": estimated_value,
            "gain_or_loss": gain_or_loss,
            "ai_recommendation": ai_recommendation
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")
