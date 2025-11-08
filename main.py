from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
import random

app = FastAPI()

# ✅ Allow frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ Your real Finnhub API key
FINNHUB_API_KEY = "d47qudpr01qk80bi464gd47qudpr01qk80bi4650"

@app.get("/")
def root():
    return {"status": "ok", "message": "Welcome to NexaVest Backend"}

@app.post("/analyze")
def analyze_stock(request: dict):
    symbol = request.get("symbol", "AAPL")
    amount = request.get("amount", 1000)

    # ✅ Fetch real-time stock data from Finnhub
    url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={FINNHUB_API_KEY}"
    res = requests.get(url)
    data = res.json()

    if "c" not in data:
        return {"error": "Invalid stock symbol or API limit reached"}

    current_price = data["c"]
    high = data["h"]
    low = data["l"]

    # ⚙️ Basic Analysis Logic
    volatility = round((high - low) / current_price, 3) if current_price else 0
    expected_return = round(random.uniform(0.05, 0.25), 3)
    risk_category = "High" if volatility > 0.4 else "Medium" if volatility > 0.2 else "Low"

    return {
        "symbol": symbol,
        "price": current_price,
        "volatility": volatility,
        "expected_return": expected_return,
        "risk_category": risk_category,
    }

@app.post("/ai_recommend")
def ai_recommend(request: dict):
    symbol = request.get("symbol", "AAPL")
    volatility = random.uniform(0.1, 0.5)
    expected_return = random.uniform(0.05, 0.3)
    risk_category = "High" if volatility > 0.4 else "Medium" if volatility > 0.2 else "Low"
    recommendation = (
        f"{symbol} shows {risk_category.lower()} volatility and "
        f"{expected_return*100:.1f}% expected return. "
        f"Suitable for {risk_category.lower()}-risk investors."
    )
    return {
        "symbol": symbol,
        "volatility": round(volatility, 3),
        "expected_return": round(expected_return, 3),
        "risk_category": risk_category,
        "ai_recommendation": recommendation,
    }
