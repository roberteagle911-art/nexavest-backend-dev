// api/index.js
// Vercel serverless function for NexaVest live analysis
// Uses global fetch (Node 18+ on Vercel). No extra native deps required.

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization",
};

function sendJson(res, status, obj) {
  res.writeHead(status, { "Content-Type": "application/json", ...CORS_HEADERS });
  res.end(JSON.stringify(obj));
}

async function yahooSearch(query) {
  const url = `https://query2.finance.yahoo.com/v1/finance/search?q=${encodeURIComponent(query)}`;
  const r = await fetch(url, { timeout: 10000 });
  if (!r.ok) return null;
  const j = await r.json();
  const quotes = j?.quotes || [];
  if (quotes.length === 0) return null;
  return quotes[0].symbol;
}

async function yahooQuote(symbol) {
  const url = `https://query1.finance.yahoo.com/v7/finance/quote?symbols=${encodeURIComponent(symbol)}`;
  const r = await fetch(url, { timeout: 10000 });
  if (!r.ok) return null;
  const j = await r.json();
  const q = j?.quoteResponse?.result?.[0];
  return q || null;
}

async function coingeckoSearchPrice(q) {
  // Try search to get coin id
  const searchUrl = `https://api.coingecko.com/api/v3/search?query=${encodeURIComponent(q)}`;
  const r = await fetch(searchUrl, { timeout: 10000 });
  if (!r.ok) return null;
  const j = await r.json();
  const coin = (j.coins && j.coins[0]) || null;
  if (!coin) return null;
  const id = coin.id;
  const priceUrl = `https://api.coingecko.com/api/v3/simple/price?ids=${encodeURIComponent(id)}&vs_currencies=usd`;
  const p = await fetch(priceUrl, { timeout: 10000 });
  if (!p.ok) return null;
  const pj = await p.json();
  return { id, name: coin.name, symbol: coin.symbol, price_usd: pj[id]?.usd ?? null };
}

async function forexRate(pair) {
  // Accept "USD/INR" or "USDINR"
  let normalized = pair.replace(/\s+/g, "").toUpperCase();
  if (!normalized.includes("/")) {
    if (normalized.length === 6) normalized = normalized.slice(0,3) + "/" + normalized.slice(3);
    else return null;
  }
  const [base, quote] = normalized.split("/");
  const url = `https://api.exchangerate.host/latest?base=${base}&symbols=${quote}`;
  const r = await fetch(url, { timeout: 10000 });
  if (!r.ok) return null;
  const j = await r.json();
  const rate = j?.rates?.[quote];
  if (!rate) return null;
  return { pair: `${base}/${quote}`, rate };
}

function detectTypeFromInput(q) {
  const s = q.toLowerCase().trim();
  if (s.includes("/")) return "forex";
  const cryptoClues = ["bitcoin","btc","ethereum","eth","bnb","doge","dogecoin","sol","matic","matic","ltc","avax"];
  if (cryptoClues.some(c => s.includes(c) || s === c)) return "crypto";
  // if purely alphabetic and short (1-5 chars), might be ticker, but we will search Yahoo anyway
  return "unknown"; // we'll attempt crypto, forex, then stock search
}

function riskLabel(vol) {
  if (vol == null) return "Unknown";
  if (vol >= 0.06) return "High";
  if (vol >= 0.02) return "Medium";
  return "Low";
}

function holdingSuggestion(type, risk) {
  if (type === "crypto") return "Short (days-weeks) — high volatility";
  if (type === "forex") return "Short to medium (days-months)";
  if (risk === "Low") return "12+ months";
  if (risk === "Medium") return "6-12 months";
  return "Short to medium (months)";
}

module.exports = async (req, res) => {
  // CORS preflight
  if (req.method === "OPTIONS") {
    res.writeHead(204, CORS_HEADERS);
    res.end();
    return;
  }

  const url = req.url || "";
  // route handling
  if (req.method === "GET" && (url === "/api/ping" || url === "/api/ping/")) {
    return sendJson(res, 200, { ok: true, time: new Date().toISOString() });
  }

  if (req.method === "POST" && (url === "/api/analyze" || url === "/api/analyze/")) {
    try {
      let body = "";
      await new Promise((resolve) => {
        req.on("data", chunk => body += chunk);
        req.on("end", resolve);
      });
      const data = body ? JSON.parse(body) : {};
      const rawAsset = (data.asset || data.query || "").toString().trim();
      const amount = Number(data.amount || data.investment || data.value || 0);

      if (!rawAsset || isNaN(amount) || amount <= 0) {
        return sendJson(res, 400, { error: "Provide valid asset (name/ticker/crypto/pair) and positive amount" });
      }

      const detected = detectTypeFromInput(rawAsset);

      // 1) forex
      if (detected === "forex") {
        const fx = await forexRate(rawAsset);
        if (!fx) return sendJson(res, 404, { error: "Forex pair not found" });
        const current_price = fx.rate;
        const type = "forex";
        const expected_return = 0.02;
        const volatility = 0.02;
        const risk = riskLabel(volatility);
        const est_value = +(amount * (1 + expected_return)).toFixed(2);
        return sendJson(res, 200, {
          asset: fx.pair,
          type,
          currency: fx.pair.split("/")[1],
          current_price,
          expected_return: `${(expected_return*100).toFixed(2)}%`,
          volatility,
          risk,
          holding_period: holdingSuggestion(type, risk),
          estimated_value: est_value,
          summary: `${fx.pair} live rate ${current_price}.`,
          disclaimer: "Informational only — not financial advice."
        });
      }

      // 2) crypto: try coinGecko search
      const cg = await coingeckoSearchPrice(rawAsset);
      if (cg && cg.price_usd != null) {
        const type = "crypto";
        const current_price = cg.price_usd;
        const expected_return = 0.08;
        const volatility = 0.08;
        const risk = riskLabel(volatility);
        const est_value = +(amount * (1 + expected_return)).toFixed(2);
        return sendJson(res, 200, {
          asset: cg.name,
          symbol: cg.symbol.toUpperCase(),
          type,
          currency: "USD",
          current_price,
          expected_return: `${(expected_return*100).toFixed(2)}%`,
          volatility,
          risk,
          holding_period: holdingSuggestion(type, risk),
          estimated_value: est_value,
          summary: `${cg.name} price from CoinGecko: ${current_price} USD.`,
          disclaimer: "Informational only — not financial advice."
        });
      }

      // 3) stock/company name: use Yahoo search then quote
      const symbol = await yahooSearch(rawAsset);
      if (!symbol) {
        return sendJson(res, 404, { error: "Asset not found via search" });
      }
      const quote = await yahooQuote(symbol);
      if (!quote) return sendJson(res, 404, { error: "No quote data for symbol" });

      const current_price = quote.regularMarketPrice ?? quote.regularMarketPreviousClose ?? quote.postMarketPrice ?? null;
      const currency = quote.currency ?? "USD";
      const type = (quote.quoteType || "EQUITY").toLowerCase() === "etf" ? "etf" : "stock";

      // Basic volatility estimate: use daily change pct if provided
      let volatility = null;
      try {
        const change = Number(quote.regularMarketChangePercent) / 100;
        volatility = Math.abs(change) || 0.02;
      } catch (e) {
        volatility = 0.02;
      }
      const expected_return = 0.05;
      const risk = riskLabel(volatility);
      const est_value = +(amount * (1 + expected_return)).toFixed(2);

      return sendJson(res, 200, {
        asset: quote.longName || symbol,
        symbol,
        type,
        currency,
        current_price,
        expected_return: `${(expected_return*100).toFixed(2)}%`,
        volatility,
        risk,
        holding_period: holdingSuggestion(type, risk),
        estimated_value: est_value,
        summary: `${quote.longName || symbol} (${symbol}) price ${current_price} ${currency}.`,
        disclaimer: "Informational only — not financial advice."
      });

    } catch (err) {
      console.error("analyze error:", err && err.stack ? err.stack : err);
      return sendJson(res, 500, { error: "Server error", details: String(err) });
    }
  }

  // default: Not Found
  sendJson(res, 404, { error: "Not Found" });
};
