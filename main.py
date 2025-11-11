from fastapi import FastAPI
from datetime import datetime

app = FastAPI()

@app.get("/ping")
def ping():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}

@app.post("/analyze")
def analyze(payload: dict):
    return {"received": payload, "message": "Backend is working!"}
