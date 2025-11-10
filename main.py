from flask import Flask, request, jsonify
from flask_cors import CORS
import yfinance as yf
import requests

app = Flask(__name__)
CORS(app)

@app.route('/ping', methods=['GET'])
def ping():
    return jsonify({"ok": True, "service": "nexavest-backend"})

@app.route('/analyze', methods=['POST'])
def analyze():
    try:
        data = request.get_json()
        query = data.get("query", "").strip()
        amount = float(data.get("amount", 0))

        if not query:
            return jsonify({"error": "No query provided"}), 400

        # Try yfinance first
        try:
            ticker = yf.Ticker(query)
            hist = ticker.history(period="1mo")
            if not hist.empty:
                last_price = hist["Close"].iloc[-1]
                returns = hist["Close"].pct_change().dropna()
                volatility = returns.std()
                expected_return = returns.mean()
                risk_level = (
                    "Low" if volatility < 0.015 else
                    "Medium" if volatility < 0.03 else
                    "High"
                )
                est_value = amount * (1 + expected_return)
                gain_loss = est_value - amount

                return jsonify({
                    "asset": query,
                    "type": "stock",
                    "symbol": query.upper(),
                    "currency": "USD",
                    "current_price": round(last_price, 2),
                    "volatility": round(volatility, 3),
                    "expected_return": round(expected_return, 3),
                    "risk": risk_level,
                    "est_value": round(est_value, 2),
                    "gain_loss": round(gain_loss, 2)
                })
        except Exception:
            pass

        # Try CoinGecko if yfinance failed
        try:
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
                    "message": f"{query} is a highly volatile crypto asset."
                })
        except Exception:
            pass

        return jsonify({"error": "Unable to detect or analyze this asset"}), 404

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True)
