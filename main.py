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


def search_ticker(query):
    """Search for a ticker symbol using Yahoo Finance’s autocomplete."""
    try:
        url = f"https://query1.finance.yahoo.com/v1/finance/search?q={query}"
        res = requests.get(url, timeout=5)
        data = res.json()

        if "quotes" in data and len(data["quotes"]) > 0:
            best_match = data["quotes"][0]
            symbol = best_match.get("symbol", "")
            shortname = best_match.get("shortname", "")
            exch = best_match.get("exchDisp", "")
            return symbol, shortname, exch
        return None, None, None
    except Exception:
        return None, None, None


def detect_crypto(query):
    """Try to detect crypto coin ID using CoinGecko search."""
    try:
        search_url = f"https://api.coingecko.com/api/v3/search?query={query}"
        res = requests.get(search_url, timeout=5)
        data = res.json()
        if "coins" in data and len(data["coins"]) > 0:
            coin_id = data["coins"][0]["id"]
            name = data["coins"][0]["name"]
            symbol = data["coins"][0]["symbol"]
            return coin_id, name, symbol
        return None, None, None
    except Exception:
        return None, None, None


@app.route("/analyze", methods=["POST"])
def analyze():
    try:
        data = request.get_json()
        query = data.get("query", "").strip()
        amount = float(data.get("amount", 0))

        if not query:
            return jsonify({"error": "No asset provided"}), 400

        # Step 1: Try to auto-detect ticker or crypto
        symbol, shortname, exch = search_ticker(query)

        if not symbol:
            # Try crypto if no stock found
            coin_id, cname, csymbol = detect_crypto(query)
            if coin_id:
                cg = requests.get(
                    f"https://api.coingecko.com/api/v3/coins/{coin_id}", timeout=5
                )
                if cg.status_code == 200:
                    info = cg.json()
                    price = info["market_data"]["current_price"]["usd"]
                    return jsonify({
                        "asset": cname,
                        "type": "crypto",
                        "symbol": csymbol.upper(),
                        "currency": "USD",
                        "current_price": round(price, 2),
                        "risk": "High",
                        "message": f"{cname} ({csymbol.upper()}) is a high-volatility crypto asset."
                    })
            return jsonify({"error": "Asset not found"}), 404

        # Step 2: Get market data from Yahoo Finance
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="1mo")
        if hist.empty:
            return jsonify({"error": "No price data found"}), 404

        last_price = hist["Close"].iloc[-1]
        returns = hist["Close"].pct_change().dropna()
        volatility = returns.std()
        expected_return = returns.mean()

        # Risk logic
        risk_level = (
            "Low" if volatility < 0.015 else
            "Medium" if volatility < 0.03 else
            "High"
        )
        est_value = amount * (1 + expected_return)
        gain_loss = est_value - amount

        currency = "INR" if symbol.endswith(".NS") else "USD"

        return jsonify({
            "asset": shortname or query,
            "type": "stock",
            "symbol": symbol,
            "market": exch or "Unknown",
            "currency": currency,
            "current_price": round(last_price, 2),
            "volatility": round(volatility, 3),
            "expected_return": round(expected_return, 3),
            "risk": risk_level,
            "est_value": round(est_value, 2),
            "gain_loss": round(gain_loss, 2)
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True)
