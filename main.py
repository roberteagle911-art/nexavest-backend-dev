from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import requests
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="NexaVest Backend - Real Data Version")

# ✅ Allow frontend (your Vercel app) to access backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # for now allow all, can restrict later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🧩 Replace with your real API key
FINNHUB_API_KEY = "d47qudpr01qk80bi464gd47qudpr01qk80bi4650"
FINNHUB_URL = "https://finnhub.io/api/v1/quote"

# ✅ Data model for request body
class AnalyzeRequest(BaseModel):
    symbol: str
    amount: float

@app.get("/")
def home():
    return {"status": "ok", "message": "Welcome to NexaVest Backend (Live Data Model)"}

@app.post("/analyze")
def analyze_stock(request: AnalyzeRequest):
    symbol = request.symbol.upper()
    amount = request.amount

    # 🔍 Fetch real stock data
    response = requests.get(f"{FINNHUB_URL}?symbol={symbol}&token={FINNHUB_API_KEY}")

    if response.status_code != 200:
        raise HTTPException(status_code=400, detail="Error fetching data from Finnhub API")

    data = response.json()
    if not data or "c" not in data or data["c"] == 0:
        raise HTTPException(status_code=404, detail="Invalid stock symbol or missing data")

    current_price = data["c"]
    open_price = data["o"]
    high = data["h"]
    low = data["l"]
    prev_close = data["pc"]

    # 📊 Real calculations
    volatility = round((high - low) / current_price, 3)
    expected_return = round((current_price - prev_close) / prev_close, 3)

    # 🎯 Risk categorization
    if volatility < 0.02:
        risk = "Low"
    elif volatility < 0.05:
        risk = "Medium"
    else:
        risk = "High"

    result = {
        "symbol": symbol,
        "volatility": volatility,
        "expected_return": expected_return,
        "risk_category": risk
    }
    return result

@app.post("/ai_recommend")
def ai_recommend(request: AnalyzeRequest):
    # Call /analyze internally
    analysis = analyze_stock(request)

    symbol = analysis["symbol"]
    risk = analysis["risk_category"]
    expected_return = analysis["expected_return"] * 100

    if risk == "Low":
        rec = f"{symbol} shows low volatility and {expected_return:.1f}% expected return. Ideal for conservative investors."
    elif risk == "Medium":
        rec = f"{symbol} shows moderate volatility and {expected_return:.1f}% expected return. Suitable for balanced portfolios."
    else:
        rec = f"{symbol} shows high volatility and {expected_return:.1f}% expected return. Suitable only for high-risk investors."

    analysis["ai_recommendation"] = rec
    return analysis
