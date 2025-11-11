// NexaVest AI Backend — Node.js 22 (Vercel Serverless)
// Provides live analysis for stocks, crypto, and forex

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization",
};

// Utility to send JSON response
function send(res, status, data) {
  res.writeHead(status, { "Content-Type": "application/json", ...CORS_HEADERS });
  res.end(JSON.stringify(data));
}

// Utility to parse JSON body
async function getBody(req) {
  return new Promise((resolve) => {
    let body = "";
    req.on("data", (chunk) => (body += chunk));
    req.on("end", () => {
      try {
        resolve(body ? JSON.parse(body) : {});
      } catch {
        resolve({});
      }
    });
  });
}

// Detect type based on user input
function detectType(input) {
  const q = input.toLowerCase().trim();
  if (q.includes("/")) return "forex";
  if (
    ["btc", "bitcoin", "eth", "ethereum", "doge", "bnb", "sol", "solana"].some((x) => q.includes(x))
  )
    return "crypto";
  return "stock";
}

// Fetch stock symbol from company name
async function findStockSymbol(name) {
  const url = `https://query2.finance.yahoo.com/v1/finance/search?q=${encodeURIComponent(name)}`;
  const res = await fetch(url);
  const data = await res.json();
  const quotes = data?.quotes || [];
  return quotes.length ? quotes[0].symbol : null;
}

// Get stock price
async function getStockPrice(symbol) {
  const url = `https://query1.finance.yahoo.com/v7/finance/quote?symbols=${encodeURIComponent(symbol)}`;
  const res = await fetch(url);
  const data = await res.json();
  const q = data?.quoteResponse?.result?.[0];
  if (!q || !q.regularMarketPrice) return null;
  return {
    name: q.longName || symbol,
    symbol: q.symbol,
    price: q.regularMarketPrice,
    currency: q.currency || "USD",
  };
}

// Get crypto price
async function getCryptoPrice(symbol) {
  const search = await fetch(
    `https://api.coingecko.com/api/v3/search?query=${encodeURIComponent(symbol)}`
  );
  const sdata = await search.json();
  const coin = sdata.coins?.[0];
  if (!coin) return null;
  const id = coin.id;
  const priceRes = await fetch(
    `https://api.coingecko.com/api/v3/simple/price?ids=${id}&vs_currencies=usd`
  );
  const p = await priceRes.json();
  return {
    name: coin.name,
    symbol: coin.symbol.toUpperCase(),
    price: p[id]?.usd || null,
    currency: "USD",
  };
}

// Get forex rate
async function getForexRate(pair) {
  let normalized = pair.toUpperCase().replace(/\s+/g, "");
  if (!normalized.includes("/") && normalized.length === 6) {
    normalized = normalized.slice(0, 3) + "/" + normalized.slice(3);
  }
  const [base, quote] = normalized.split("/");
  const url = `https://api.exchangerate.host/latest?base=${base}&symbols=${quote}`;
  const res = await fetch(url);
  const data = await res.json();
  const rate = data?.rates?.[quote];
  return rate ? { pair: `${base}/${quote}`, price: rate, currency: quote } : null;
}

// Risk and holding logic
function riskAndHold(type) {
  if (type === "crypto") return { risk: "High", expected_return: "8%", hold: "Short-term" };
  if (type === "forex") return { risk: "Medium", expected_return: "2%", hold: "6-12 months" };
  return { risk: "Low", expected_return: "5%", hold: "12+ months" };
}

// --- Serverless Function Entry ---
module.exports = async (req, res) => {
  if (req.method === "OPTIONS") {
    res.writeHead(204, CORS_HEADERS);
    res.end();
    return;
  }

  if (req.method === "GET" && req.url.startsWith("/api/ping")) {
    return send(res, 200, { ok: true, time: new Date().toISOString() });
  }

  if (req.method === "POST" && req.url.startsWith("/api/analyze")) {
    try {
      const body = await getBody(req);
      const asset = (body.asset || "").trim();
      const amount = Number(body.amount || 0);

      if (!asset || isNaN(amount) || amount <= 0) {
        return send(res, 400, { error: "Enter valid asset name and amount" });
      }

      const type = detectType(asset);
      let info = null;

      if (type === "forex") info = await getForexRate(asset);
      else if (type === "crypto") info = await getCryptoPrice(asset);
      else {
        const symbol = await findStockSymbol(asset);
        info = symbol ? await getStockPrice(symbol) : null;
      }

      if (!info || !info.price) {
        return send(res, 404, { error: "Asset not found or no price data" });
      }

      const { risk, expected_return, hold } = riskAndHold(type);
      const est_value = +(amount * (1 + parseFloat(expected_return) / 100)).toFixed(2);

      return send(res, 200, {
        asset: info.name || asset,
        symbol: info.symbol || asset,
        type,
        current_price: info.price,
        currency: info.currency,
        risk,
        expected_return,
        holding_period: hold,
        estimated_value: est_value,
        summary: `${info.name || asset} (${info.symbol || asset}) is a ${type} asset with ${risk} risk and expected return of ${expected_return}.`,
        disclaimer: "This analysis is informational only. Not financial advice.",
      });
    } catch (err) {
      console.error("Error:", err);
      return send(res, 500, { error: "Server error", details: String(err) });
    }
  }

  // Default route
  return send(res, 404, { error: "Not Found" });
};
