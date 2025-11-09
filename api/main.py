from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import yfinance as yf

app = FastAPI(title="NexaVest Backend (Dev)")

# CORS setup
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

# Finnhub API key
FINNHUB_API_KEY = "d47qudpr01qk80bi464gd47qudpr01qk80bi4650"
FINNHUB_URL = "https://finnhub.io/api/v1/quote"

class AnalyzeRequest(BaseModel):
    symbol: str
    amount: float

@app.get("/")
def home():
    return {"status": "ok", "message": "NexaVest Backend Dev is running successfully ✅"}

@app.post("/analyze")
def analyze_stock(request: AnalyzeRequest):
    symbol = request.symbol.upper()
    amount = request.amount

    try:
        # Try Finnhub first
        res = requests.get(f"{FINNHUB_URL}?symbol={symbol}&token={FINNHUB_API_KEY}")
        data = res.json()

        if "c" in data and data["c"] != 0:
            current = data["c"]
            high = data["h"]
            low = data["l"]
            prev = data["pc"]
        else:
            # Fallback to yfinance if Finnhub has no data
            stock = yf.Ticker(symbol)
            hist = stock.history(period="5d")
            current = hist["Close"].iloc[-1]
            high = hist["High"].iloc[-1]
            low = hist["Low"].iloc[-1]
            prev = hist["Close"].iloc[-2]

        # Calculate volatility & expected return
        volatility = round((high - low) / current, 3)
        expected_return = round((current - prev) / prev, 3)

        # Risk classification
        if volatility < 0.02:
            risk = "Low"
        elif volatility < 0.05:
            risk = "Medium"
        else:
            risk = "High"

        # AI-like recommendation text
        ai_recommendation = (
            f"{symbol} has {risk.lower()} risk and volatility of {volatility}. "
            f"It’s a suitable choice for {('conservative' if risk == 'Low' else 'balanced' if risk == 'Medium' else 'aggressive')} investors."
        )

        return {
            "symbol": symbol,
            "current_price": round(current, 2),
            "expected_return": expected_return,
            "volatility": volatility,
            "risk_category": risk,
            "ai_recommendation": ai_recommendation,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")
