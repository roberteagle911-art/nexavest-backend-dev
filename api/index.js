// api/index.js
// NexaVest live analysis — Vercel serverless (Node 22)
// Handles: GET /api/ping and POST /api/analyze
// Fetches live prices from Yahoo / CoinGecko / exchangerate.host
// Detects company name, ticker, crypto, and forex pairs.

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization",
};

// helper: JSON response + CORS
function sendJson(res, status, payload) {
  res.writeHead(status, { "Content-Type": "application/json", ...CORS_HEADERS });
  res.end(JSON.stringify(payload));
}

// parse body safely
async function parseBody(req) {
  return new Promise((resolve) => {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => {
      try { resolve(body ? JSON.parse(body) : {}); }
      catch { resolve({}); }
    });
  });
}

// detect probable type
function detectType(input) {
  const q = input.toLowerCase().trim();
  if (q.includes("/")) return "forex";
  const cryptoClues = ["btc","bitcoin","eth","ethereum","bnb","doge","dogecoin","sol","solana","ada","matic","ltc","avax"];
  if (cryptoClues.some(c => q === c || q.includes(c))) return "crypto";
  return "stock";
}

// search Yahoo Finance for a symbol by company name
async function yahooSearchSymbol(name) {
  const url = `https://query2.finance.yahoo.com/v1/finance/search?q=${encodeURIComponent(name)}`;
  const res = await fetch(url, { timeout: 10000 });
  if (!res.ok) return null;
  const j = await res.json();
  const quotes = j?.quotes || [];
  if (!quotes.length) return null;
  // prefer equities, ETFs
  for (const q of quotes) {
    if (q.quoteType && ["EQUITY","ETF"].includes(q.quoteType)) return q.symbol;
  }
  return quotes[0].symbol;
}

// get Yahoo quote
async function yahooQuote(symbol) {
  const url = `https://query1.finance.yahoo.com/v7/finance/quote?symbols=${encodeURIComponent(symbol)}`;
  const res = await fetch(url, { timeout: 10000 });
  if (!res.ok) return null;
  const j = await res.json();
  const q = j?.quoteResponse?.result?.[0];
  return q || null;
}

// get coingecko price & meta
async function coingeckoData(query) {
  const searchUrl = `https://api.coingecko.com/api/v3/search?query=${encodeURIComponent(query)}`;
  const s = await fetch(searchUrl, { timeout: 10000 });
  if (!s.ok) return null;
  const sj = await s.json();
  const coin = sj?.coins?.[0];
  if (!coin) return null;
  const id = coin.id;
  const priceUrl = `https://api.coingecko.com/api/v3/simple/price?ids=${encodeURIComponent(id)}&vs_currencies=usd`;
  const p = await fetch(priceUrl, { timeout: 10000 });
  if (!p.ok) return null;
  const pj = await p.json();
  return { id, name: coin.name, symbol: coin.symbol.toUpperCase(), price: pj[id]?.usd ?? null };
}

// get forex rate
async function forexRate(pair) {
  let p = pair.toUpperCase().replace(/\s+/g, "");
  if (!p.includes("/") && p.length === 6) p = p.slice(0,3) + "/" + p.slice(3);
  if (!p.includes("/")) return null;
  const [base, quote] = p.split("/");
  const url = `https://api.exchangerate.host/latest?base=${base}&symbols=${quote}`;
  const r = await fetch(url, { timeout: 10000 });
  if (!r.ok) return null;
  const j = await r.json();
  const rate = j?.rates?.[quote];
  if (!rate) return null;
  return { pair: `${base}/${quote}`, rate, currency: quote };
}

// risk/holding logic
function riskLabel(vol) {
  if (vol == null) return "Unknown";
  if (vol >= 0.06) return "High";
  if (vol >= 0.02) return "Medium";
  return "Low";
}
function holdingSuggestion(type, risk) {
  if (type === "crypto") return "Short (days-weeks)";
  if (type === "forex") return "Short to medium (days-months)";
  if (risk === "Low") return "12+ months";
  if (risk === "Medium") return "6-12 months";
  return "Short to medium";
}

// main handler
module.exports = async (req, res) => {
  // handle CORS preflight
  if (req.method === "OPTIONS") {
    res.writeHead(204, CORS_HEADERS);
    res.end();
    return;
  }

  // ping
  if (req.method === "GET" && (req.url === "/api/ping" || req.url === "/api/ping/")) {
    return sendJson(res, 200, { ok: true, time: new Date().toISOString() });
  }

  // analyze
  if (req.method === "POST" && (req.url === "/api/analyze" || req.url === "/api/analyze/")) {
    try {
      const body = await parseBody(req);
      const raw = (body.asset || body.query || "").toString().trim();
      const amount = Number(body.amount || body.value || 0);

      if (!raw || isNaN(amount) || amount <= 0) {
        return sendJson(res, 400, { error: "Provide valid asset/company name and positive amount" });
      }

      const typeHint = detectType(raw);
      let info = null;
      let assetType = null;

      // Try forex first if input looks like pair
      if (typeHint === "forex") {
        const fx = await forexRate(raw);
        if (!fx) return sendJson(res, 404, { error: "Forex pair not found" });
        assetType = "forex";
        const current_price = fx.rate;
        const vol = 0.02;
        const risk = riskLabel(vol);
        const expectedReturnPct = 0.02;
        const est_value = +(amount * (1 + expectedReturnPct)).toFixed(2);
        return sendJson(res, 200, {
          asset: fx.pair,
          type: assetType,
          currency: fx.currency,
          current_price,
          volatility: vol,
          expected_return: `${(expectedReturnPct*100).toFixed(2)}%`,
          risk,
          holding_period: holdingSuggestion(assetType, risk),
          estimated_value: est_value,
          summary: `${fx.pair} live rate ${current_price}.`,
          disclaimer: "Informational only — not financial advice."
        });
      }

      // Try crypto via CoinGecko
      const cg = await coingeckoData(raw);
      if (cg && cg.price != null) {
        assetType = "crypto";
        const current_price = cg.price;
        const vol = 0.08;
        const expectedReturnPct = 0.08;
        const risk = riskLabel(vol);
        const est_value = +(amount * (1 + expectedReturnPct)).toFixed(2);
        return sendJson(res, 200, {
          asset: cg.name,
          symbol: cg.symbol,
          type: assetType,
          currency: "USD",
          current_price,
          volatility: vol,
          expected_return: `${(expectedReturnPct*100).toFixed(2)}%`,
          risk,
          holding_period: holdingSuggestion(assetType, risk),
          estimated_value: est_value,
          summary: `${cg.name} price ${current_price} USD (CoinGecko).`,
          disclaimer: "Informational only — not financial advice."
        });
      }

      // Stock/company search -> quote
      const symbol = await yahooSearchSymbol(raw);
      if (!symbol) return sendJson(res, 404, { error: "Asset not found" });
      const quote = await yahooQuote(symbol);
      if (!quote) return sendJson(res, 404, { error: "No quote data for symbol" });

      const current_price = quote.regularMarketPrice ?? quote.regularMarketPreviousClose ?? null;
      const currency = quote.currency ?? "USD";
      assetType = (quote.quoteType || "EQUITY").toLowerCase() === "etf" ? "etf" : "stock";
      // approximate volatility from percent change if available
      const pct = Number(quote.regularMarketChangePercent) || 0.02;
      const vol = Math.abs(pct) / 100 || 0.02;
      const expectedReturnPct = 0.05;
      const risk = riskLabel(vol);
      const est_value = +(amount * (1 + expectedReturnPct)).toFixed(2);

      return sendJson(res, 200, {
        asset: quote.longName || symbol,
        symbol,
        type: assetType,
        currency,
        current_price,
        volatility: vol,
        expected_return: `${(expectedReturnPct*100).toFixed(2)}%`,
        risk,
        holding_period: holdingSuggestion(assetType, risk),
        estimated_value: est_value,
        summary: `${quote.longName || symbol} price ${current_price} ${currency}.`,
        disclaimer: "Informational only — not financial advice."
      });

    } catch (err) {
      console.error("analyze error:", err && err.stack ? err.stack : err);
      return sendJson(res, 500, { error: "Server error", details: String(err) });
    }
  }

  // fallback
  return sendJson(res, 404, { error: "Not Found" });
};
