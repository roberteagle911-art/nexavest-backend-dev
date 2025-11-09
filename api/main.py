# api/main.py
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import yfinance as yf
from typing import Optional

app = FastAPI(title="NexaVest Backend (Vercel)")

# Allow frontend to call this backend (dev/prod)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # ok for dev; lock this down to your frontend domain in prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Replace with your Finnhub API key (you posted it earlier)
FINNHUB_API_KEY = "d47qudpr01qk80bi464gd47qudpr01qk80bi4650"
FINNHUB_URL = "https://finnhub.io/api/v1/quote"

class AnalyzeRequest(BaseModel):
    symbol: str
    amount: float

@app.get("/")
def home():
    return {"status": "ok", "message": "NexaVest Backend running on Vercel"}

def fetch_finnhub_price(symbol: str) -> Optional[dict]:
    """Try Finnhub first (works for many global tickers)."""
    try:
        resp = requests.get(f"{FINNHUB_URL}?symbol={symbol}&token={FINNHUB_API_KEY}", timeout=8)
        if resp.status_code != 200:
            return None
        data = resp.json()
        # Finnhub returns "c" (current), "o" (open), "h","l","pc" previous close
        if not data or "c" not in data or data["c"] is None:
            return None
        return {
            "current": float(data["c"]),
            "open": float(data.get("o", data["c"])),
            "high": float(data.get("h", data["c"])),
            "low": float(data.get("l", data["c"])),
            "prev_close": float(data.get("pc", data["c"]))
        }
    except Exception:
        return None

def fetch_yfinance_price(symbol: str) -> Optional[dict]:
    """Fallback to yfinance (works widely incl. .NS tickers for India)."""
    try:
        # If symbol already ends with .NS or .BO etc, pass as-is
        ticker = symbol
        # yfinance expects some tickers without suffix for US (e.g. AAPL)
        yf_t = yf.Ticker(ticker)
        hist = yf_t.history(period="5d")
        if hist is None or hist.empty:
            return None
        # use last close as current and prev close
        current = float(hist["Close"].iloc[-1])
        prev_close = float(hist["Close"].iloc[-2]) if len(hist["Close"]) >= 2 else current
        high = float(hist["High"].iloc[-1]) if "High" in hist.columns else current
        low = float(hist["Low"].iloc[-1]) if "Low" in hist.columns else current
        return {
            "current": current,
            "open": float(hist["Open"].iloc[-1]) if "Open" in hist.columns else current,
            "high": high,
            "low": low,
            "prev_close": prev_close
        }
    except Exception:
        return None

@app.post("/api/analyze")
def analyze_stock(req: AnalyzeRequest):
    symbol = req.symbol.strip().upper()
    amount = float(req.amount or 0)

    if not symbol:
        raise HTTPException(status_code=400, detail="Symbol required")

    # Try Finnhub first
    data = fetch_finnhub_price(symbol)

    # If Finnhub unavailable or returns nothing, try yfinance
    if data is None:
        data = fetch_yfinance_price(symbol)
        if data is None:
            raise HTTPException(status_code=502, detail="Unable to fetch price data for symbol")

    current_price = data["current"]
    prev_close = data["prev_close"]
    high = data.get("high", current_price)
    low = data.get("low", current_price)

    # Calculations
    # volatility = (high - low) / current  (simple)
    try:
        volatility = round((high - low) / current_price, 3) if current_price != 0 else 0.0
    except Exception:
        volatility = 0.0

    try:
        expected_return = round((current_price - prev_close) / prev_close, 3) if prev_close != 0 else 0.0
    except Exception:
        expected_return = 0.0

    # risk categorization
    if volatility < 0.02:
        risk = "Low"
    elif volatility < 0.05:
        risk = "Medium"
    else:
        risk = "High"

    # Simple recommendation text
    if risk == "Low":
        rec = f"{symbol} shows low volatility and appears relatively stable — may suit conservative investors."
    elif risk == "Medium":
        rec = f"{symbol} shows moderate volatility; a reasonable short- to mid-term option with moderate risk."
    else:
        rec = f"{symbol} shows high volatility — suitable for aggressive traders; watch position sizing carefully."

    # Estimate value if user invests `amount`
    est_value = round(amount * (1 + expected_return), 2)
    gain_loss = round(est_value - amount, 2)
    gain_loss_str = f"{gain_loss}"

    # Create a result payload
    result = {
        "symbol": symbol,
        "current_price": round(current_price, 2),
        "volatility": volatility,
        "expected_return": expected_return,
        "risk_category": risk,
        "ai_recommendation": rec,
        "estimated_value": est_value,
        "gain_loss": gain_loss_str
    }

    return result
