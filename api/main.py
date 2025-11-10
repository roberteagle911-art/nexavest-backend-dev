# main.py
from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import yfinance as yf
import math
import re

app = Flask(__name__)
CORS(app, origins="*")

COINGECKO_API = "https://api.coingecko.com/api/v3"

def is_crypto_guess(q):
    ql = q.lower()
    # heuristics: contains 'coin', 'token', 'btc', 'eth', or endswith 'coin' etc
    return any(x in ql for x in ["coin", "token", "btc", "eth", "bch", "doge", "usdt", "usdc", "matic", "ltc", "avax", "sol"])

def normalize_symbol_for_india(q):
    # If symbol already has .NS or .BO etc, leave it
    if re.search(r"\.(NS|BO|NSE|BSE|L|NSM|BOM)$", q, re.IGNORECASE):
        return q
    # If it's obvious a pure ticker (all letters and length <=6) add .NS as default assumption for Indian names
    if re.fullmatch(r"[A-Za-z0-9\-\.]{1,7}", q):
        return q + ".NS"
    return q

def try_yfinance(symbol):
    try:
        t = yf.Ticker(symbol)
        info = t.info if hasattr(t, "info") else {}
        price = None
        # try common keys
        for k in ("regularMarketPrice", "currentPrice", "last_price", "previousClose"):
            if info.get(k) is not None:
                price = info.get(k)
                break
        # fallback: history
        if price is None:
            hist = t.history(period="1d")
            if not hist.empty:
                price = float(hist['Close'].iloc[-1])
        return {
            "source": "yfinance",
            "price": price,
            "info": info
        }
    except Exception as e:
        return {"error": str(e)}

def coingecko_search_price(query):
    try:
        # search coins
        q = query.lower()
        s = requests.get(f"{COINGECKO_API}/search", params={"query": q}, timeout=10).json()
        coins = s.get("coins", [])
        if not coins:
            return {"error": "no coin match"}
        coin = coins[0]
        coin_id = coin.get("id")
        # price in usd
        p = requests.get(f"{COINGECKO_API}/simple/price", params={"ids": coin_id, "vs_currencies":"usd,inr"}, timeout=10).json()
        price_usd = p.get(coin_id, {}).get("usd")
        price_inr = p.get(coin_id, {}).get("inr")
        return {
            "source": "coingecko",
            "coin_id": coin_id,
            "symbol": coin.get("symbol"),
            "name": coin.get("name"),
            "price_usd": price_usd,
            "price_inr": price_inr
        }
    except Exception as e:
        return {"error": str(e)}

def simple_volatility_and_return_from_history(symbol):
    # Very small, approximate placeholder using last 30 days pct returns if possible
    try:
        t = yf.Ticker(symbol)
        hist = t.history(period="60d")  # fetch 60 days to be safe
        if hist.empty or len(hist) < 5:
            return {"volatility": 0.0, "expected_return": 0.0}
        closes = hist['Close'].astype(float)
        rets = closes.pct_change().dropna()
        vol = float(rets.std())
        avg_ret = float(rets.mean())
        # normalize to reasonable short-term expected return
        return {"volatility": round(vol, 3), "expected_return": round(avg_ret, 3)}
    except Exception:
        return {"volatility": 0.0, "expected_return": 0.0}

@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"ok": True, "service": "nexavest-backend"}), 200

@app.route("/analyze", methods=["POST"])
def analyze():
    try:
        data = request.get_json(force=True)
        query = (data.get("query") or "").strip()
        amount = data.get("amount", None)
        if not query:
            return jsonify({"error": "query required"}), 400

        # Prepare response scaffold
        resp = {
            "query": query,
            "detected_type": None,
            "symbol": None,
            "market": None,
            "currency": None,
            "current_price": None,
            "volatility": None,
            "expected_return": None,
            "estimated_value": None,
            "gain_loss": None,
            "notes": [],
        }

        # Decide crypto vs stock via heuristics
        if is_crypto_guess(query):
            # treat as crypto search on coingecko
            cg = coingecko_search_price(query)
            if cg.get("error"):
                resp["notes"].append("CoinGecko search failed: " + cg.get("error"))
                resp["detected_type"] = "unknown"
                return jsonify(resp), 200
            resp["detected_type"] = "crypto"
            resp["symbol"] = cg.get("symbol") or query
            resp["market"] = "CoinGecko"
            # prefer USD price, provide INR if available
            price = cg.get("price_usd") if cg.get("price_usd") is not None else cg.get("price_inr")
            resp["current_price"] = price
            resp["currency"] = "USD" if cg.get("price_usd") is not None else "INR"
            resp["volatility"] = 0.07  # placeholder high for crypto
            resp["expected_return"] = 0.0  # placeholder
        else:
            # Try as ticker: attempt direct yfinance, if that fails and no exchange suffix, try adding .NS
            # First try exactly as provided
            try_sym = query.upper().replace(" ", "")
            yf_try = try_yfinance(try_sym)
            if yf_try.get("error") or yf_try.get("price") is None:
                # Try Indian suffix
                try_sym2 = normalize_symbol_for_india(try_sym)
                yf_try2 = try_yfinance(try_sym2)
                if not yf_try2.get("error") and yf_try2.get("price") is not None:
                    chosen = yf_try2
                    symbol_used = try_sym2
                else:
                    # fallback: try raw query as name search via yfinance ticker lookup (yfinance can accept company names occasionally)
                    chosen = yf_try
                    symbol_used = try_sym
            else:
                chosen = yf_try
                symbol_used = try_sym

            if chosen.get("error") or chosen.get("price") is None:
                # If still no price, mark unknown
                # Optionally, we could attempt other sources, but return graceful message
                resp["detected_type"] = "stock"
                resp["symbol"] = symbol_used
                resp["market"] = "unknown"
                resp["currency"] = "USD"
                resp["notes"].append("Could not fetch price for symbol via yfinance. Check ticker symbol or use exact exchange suffix (e.g., RELIANCE.NS)")
                return jsonify(resp), 200

            resp["detected_type"] = "stock"
            resp["symbol"] = symbol_used
            resp["market"] = "yfinance"
            resp["current_price"] = chosen.get("price")
            # If the symbol endswith .NS assume INR
            if symbol_used.upper().endswith(".NS") or symbol_used.upper().endswith(".BSE") or symbol_used.upper().endswith(".BO"):
                resp["currency"] = "INR"
            else:
                resp["currency"] = "USD"

            vol_ret = simple_volatility_and_return_from_history(symbol_used)
            resp["volatility"] = vol_ret.get("volatility", 0.0)
            resp["expected_return"] = vol_ret.get("expected_return", 0.0)

        # Calculate estimated value and gain/loss if amount provided
        try:
            if amount is not None:
                # amount is money invested in the asset's currency (we assume that)
                # estimated_value = amount * (1 + expected_return)
                expected = float(resp.get("expected_return") or 0.0)
                est_val = float(amount) * (1 + expected)
                gain_loss = est_val - float(amount)
                resp["estimated_value"] = round(est_val, 2)
                resp["gain_loss"] = round(gain_loss, 2)
            else:
                resp["estimated_value"] = None
                resp["gain_loss"] = None
        except Exception as e:
            resp["notes"].append("Calculation error: " + str(e))

        return jsonify(resp), 200

    except Exception as e:
        return jsonify({"error": "server error", "detail": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8080)
