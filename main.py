# main.py
from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import yfinance as yf
import pandas as pd
import numpy as np
import re
import os

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "NexaVest Backend is Live", "version": "1.0"})

@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"ok": True, "service": "nexavest-backend"})

# ---------- Helpers ----------

def yahoo_search(query):
    try:
        url = f"https://query1.finance.yahoo.com/v1/finance/search?q={requests.utils.requote_uri(query)}"
        r = requests.get(url, timeout=6)
        if r.status_code != 200:
            return None
        obj = r.json()
        quotes = obj.get("quotes", []) + obj.get("news", [])
        if len(quotes) == 0:
            return None
        # prefer equities
        for q in quotes:
            if q.get("quoteType") in ("EQUITY","ETF","MUTUALFUND"):
                return q
        return quotes[0]
    except Exception:
        return None

def detect_crypto(query):
    """Return coin_id, name, symbol or None"""
    try:
        url = f"https://api.coingecko.com/api/v3/search?query={requests.utils.requote_uri(query)}"
        r = requests.get(url, timeout=6)
        if r.status_code != 200:
            return None
        obj = r.json()
        coins = obj.get("coins", [])
        if not coins:
            return None
        return coins[0]  # first match: {id,name,symbol}
    except Exception:
        return None

def is_forex_pair(q):
    """Detect forex pair like EURUSD or USD/INR or USDINR"""
    q2 = q.replace(" ", "").upper()
    # direct XX/YY style
    if "/" in q:
        a,b = q2.split("/",1)
        if len(a)==3 and len(b)==3:
            return f"{a}/{b}"
    # 6-letter like USDINR
    if re.fullmatch(r"[A-Z]{6}", q2):
        return f"{q2[:3]}/{q2[3:]}"
    return None

def get_forex_rate(pair):
    """Use exchangerate.host to get latest rate base A -> B"""
    try:
        base,quote = pair.split("/")
        r = requests.get(f"https://api.exchangerate.host/latest?base={base}&symbols={quote}", timeout=5)
        if r.status_code != 200:
            return None
        data = r.json()
        rate = data.get("rates", {}).get(quote)
        return rate
    except Exception:
        return None

def compute_stock_metrics(symbol):
    """Return dict with last_price, volatility, expected_return"""
    try:
        t = yf.Ticker(symbol)
        # get 90 days daily
        hist = t.history(period="90d", interval="1d")
        if hist is None or hist.empty:
            return None
        close = hist["Close"].dropna()
        if close.empty:
            return None
        last_price = float(close.iloc[-1])
        returns = close.pct_change().dropna()
        if returns.empty:
            volatility = 0.0
            exp_return = 0.0
        else:
            volatility = float(returns.std())  # daily std
            exp_return = float(returns.mean())  # daily mean
        # For user-friendly output show annualized volatility ~ sqrt(252)
        vol_annual = volatility * (252 ** 0.5)
        exp_annual = exp_return * 252
        return {"last_price": last_price, "volatility_daily": volatility,
                "volatility_annual": vol_annual, "expected_return_daily": exp_return,
                "expected_return_annual": exp_annual, "close_series": close}
    except Exception:
        return None

def risk_label(vol_annual):
    if vol_annual < 0.2:
        return "Low"
    if vol_annual < 0.6:
        return "Medium"
    return "High"

def holding_period_suggestion(asset_type, risk_label):
    # simple rules
    if asset_type == "crypto":
        return "Short (days to weeks) — crypto is highly volatile"
    if asset_type == "forex":
        return "Short to medium (days to months) depending on pair"
    # for stocks
    if risk_label == "Low":
        return "12+ months"
    if risk_label == "Medium":
        return "6 - 12 months"
    return "Short to Medium (months) — higher risk"

# ---------- API ----------

@app.route("/analyze", methods=["POST"])
def analyze():
    try:
        payload = request.get_json(force=True)
        query = str(payload.get("query", "")).strip()
        amount = payload.get("amount", None)
        if amount is None:
            amount = 0.0
        try:
            amount = float(amount)
        except Exception:
            amount = 0.0

        if not query:
            return jsonify({"error":"No query provided"}), 400

        # 1) Check forex pairs first
        fx = is_forex_pair(query)
        if fx:
            rate = get_forex_rate(fx)
            if rate is None:
                return jsonify({"error":"Forex pair not found or external API error"}), 404
            est_value = amount * (1 if fx.split("/")[1]=="USD" else 1)  # amount assumed already in base currency
            response = {
                "asset": fx,
                "type": "forex",
                "symbol": fx.replace("/",""),
                "market": "FX",
                "currency_pair": fx,
                "current_rate": round(rate, 6),
                "risk": "Medium",
                "holding_period": holding_period_suggestion("forex","Medium"),
                "est_value": round(amount * rate, 4),
                "gain_loss": None,
                "disclaimer": "This is a suggestion only. Not financial advice."
            }
            return jsonify(response)

        # 2) Try stock search (Yahoo)
        stock_info = yahoo_search(query)
        if stock_info:
            symbol = stock_info.get("symbol")
            shortname = stock_info.get("shortname") or stock_info.get("longname") or query
            quote_type = stock_info.get("quoteType", "").lower()
            # ensure symbol present
            if symbol:
                metrics = compute_stock_metrics(symbol)
                if not metrics:
                    # Maybe the symbol is foreign; attempt small fallback
                    return jsonify({"error":"No historical price data found for symbol", "symbol": symbol}), 404
                vol_ann = metrics["volatility_annual"]
                exp_ann = metrics["expected_return_annual"]
                risk = risk_label(vol_ann)
                est_value = amount * (1 + exp_ann)  # simple expected growth formula
                gain_loss = est_value - amount
                currency = "INR" if symbol.endswith(".NS") or symbol.endswith(".BO") else "USD"
                resp = {
                    "asset": shortname,
                    "type": "stock",
                    "symbol": symbol,
                    "market": stock_info.get("exchDisp") or stock_info.get("exchange") or "Unknown",
                    "currency": currency,
                    "current_price": round(metrics["last_price"], 4),
                    "volatility_annual": round(vol_ann, 4),
                    "expected_return_annual": round(exp_ann, 4),
                    "risk": risk,
                    "holding_period": holding_period_suggestion("stock", risk),
                    "est_value": round(est_value, 2),
                    "gain_loss": round(gain_loss, 2),
                    "explanation": f"{shortname} shows {risk} risk (annual volatility ~ {round(vol_ann,3)}). This is an estimate based on historical data.",
                    "disclaimer": "Informational only — not investment advice."
                }
                return jsonify(resp)

        # 3) Try crypto via CoinGecko
        coin = detect_crypto(query)
        if coin:
            coin_id = coin.get("id")
            # fetch coin data
            r = requests.get(f"https://api.coingecko.com/api/v3/coins/{coin_id}", timeout=6)
            if r.status_code == 200:
                c = r.json()
                price_usd = c.get("market_data", {}).get("current_price", {}).get("usd")
                if price_usd is None:
                    return jsonify({"error":"Crypto price not available"}), 404
                # volatility estimate from 30d prices if present
                market_chart = requests.get(f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart?vs_currency=usd&days=30", timeout=6)
                vol = None
                if market_chart.status_code == 200:
                    data = market_chart.json()
                    prices = [p[1] for p in data.get("prices", [])]
                    if len(prices) > 1:
                        arr = pd.Series(prices).pct_change().dropna()
                        vol = float(arr.std() * (365 ** 0.5))  # annualized
                vol = vol if vol is not None else 0.0
                risk = risk_label(vol)
                est_value = amount * (1 + 0.0)  # no prediction for crypto
                resp = {
                    "asset": c.get("name"),
                    "type": "crypto",
                    "symbol": c.get("symbol").upper(),
                    "market": "CoinGecko",
                    "currency": "USD",
                    "current_price": round(price_usd, 6),
                    "volatility_annual": round(vol, 4),
                    "expected_return_annual": 0.0,
                    "risk": risk,
                    "holding_period": holding_period_suggestion("crypto", risk),
                    "est_value": round(est_value, 2),
                    "gain_loss": None,
                    "explanation": f"{c.get('name')} detected as crypto. Prices and volatility from CoinGecko.",
                    "disclaimer": "Informational only — not investment advice."
                }
                return jsonify(resp)

        # If nothing matched
        return jsonify({"error":"Asset not found"}), 404

    except Exception as e:
        return jsonify({"error": "Server error", "details": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
