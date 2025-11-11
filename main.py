from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/ping")
def ping():
    return {"message": "pong"}

@app.post("/analyze")
def analyze(data: dict):
    asset = data.get("asset", "").upper()
    amount = data.get("amount", 0)
    return {
        "asset": asset,
        "type": "stock",
        "market": "NYSE",
        "currency": "USD",
        "current_price": 250,
        "expected_return": "2%",
        "risk": "Low",
        "holding_period": "12+ months",
        "summary": f"{asset} is considered stable with low volatility."
    }
