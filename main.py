from flask import Flask, jsonify, request
from flask_cors import CORS
import yfinance as yf
import requests

app = Flask(__name__)
CORS(app)

@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "NexaVest Backend is Live ✅"})

@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"ok": True, "service": "nexavest-backend"})

@app.route("/analyze", methods=["POST"])
def analyze():
    try:
        data = request.get_json()
        query = data.get("query", "").strip()
        amount = float(data.get("amount", 0))
        if not query:
            return jsonify({"error": "No asset name provided"}), 400

        # Try stock data first
        ticker = yf.Ticker(query)
        hist = ticker.history(period="1mo")
        if not hist.empty:
            last_price = hist["Close"].iloc[-1]
            returns = hist["Close"].pct_change().dropna()
            vol = returns.std()
            exp_ret = returns.mean()
            risk = (
                "Low" if vol < 0.015 else
                "Medium" if vol < 0.03 else
                "High"
            )
            est_val = amount * (1 + exp_ret)
            gain_loss = est_val - amount
            return jsonify({
                "asset": query,
                "type": "stock",
                "symbol": query.upper(),
                "currency": "USD",
                "current_price": round(last_price, 2),
                "volatility": round(vol, 3),
                "expected_return": round(exp_ret, 3),
                "risk": risk,
                "est_value": round(est_val, 2),
                "gain_loss": round(gain_loss, 2)
            })

        # Try CoinGecko if no stock data
        cg = requests.get(
            f"https://api.coingecko.com/api/v3/coins/{query.lower()}",
            timeout=5
        )
        if cg.status_code == 200:
            info = cg.json()
            price_usd = info["market_data"]["current_price"]["usd"]
            return jsonify({
                "asset": query,
                "type": "crypto",
                "symbol": query.lower(),
                "currency": "USD",
                "current_price": price_usd,
                "risk": "High",
                "message": f"{query} is a high volatility crypto."
            })

        return jsonify({"error": "Asset not found"}), 404

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True)
