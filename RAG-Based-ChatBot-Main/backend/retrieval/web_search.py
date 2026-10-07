import urllib.request
import urllib.parse
import json
import re
import html
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

def clean_snippet(text: str) -> str:
    """Cleans HTML tags, unescapes entities, and normalizes spaces."""
    unescaped = html.unescape(text)
    no_tags = re.sub(r"<[^>]+>", "", unescaped)
    return " ".join(no_tags.split()).strip()

# Common stock tickers mapping
POPULAR_TICKERS = {
    "apple": "AAPL",
    "aapl": "AAPL",
    "nvidia": "NVDA",
    "nvda": "NVDA",
    "microsoft": "MSFT",
    "msft": "MSFT",
    "google": "GOOGL",
    "alphabet": "GOOGL",
    "googl": "GOOGL",
    "amazon": "AMZN",
    "amzn": "AMZN",
    "tesla": "TSLA",
    "tsla": "TSLA",
    "meta": "META",
    "facebook": "META",
    "netflix": "NFLX",
    "nflx": "NFLX",
    "tata": "TTM",
    "reliance": "RELIANCE.NS",
}

class LiveWebSearch:
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        }

    def get_stock_data(self, query: str) -> Optional[str]:
        """Fetches live stock price if query mentions stocks/tickers."""
        q_lower = query.lower()
        symbol = None

        for name, sym in POPULAR_TICKERS.items():
            if re.search(rf"\b{name}\b", q_lower):
                symbol = sym
                break

        # Check for explicit ticker like $NVDA, AAPL stock
        ticker_match = re.search(r"\$([A-Za-z]{1,5})\b", query)
        if ticker_match:
            symbol = ticker_match.group(1).upper()

        if not symbol and any(w in q_lower for w in ["stock", "share price", "market price", "trading at"]):
            words = re.findall(r"\b[A-Za-z]+\b", query)
            for w in words:
                w_up = w.upper()
                if w_up in ["AAPL", "NVDA", "MSFT", "TSLA", "AMZN", "META", "GOOGL", "NFLX", "AMD", "INTC", "SPY", "QQQ"]:
                    symbol = w_up
                    break

        if not symbol:
            return None

        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?interval=1d&range=1d"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                meta = data["chart"]["result"][0]["meta"]
                price = meta.get("regularMarketPrice")
                prev_close = meta.get("chartPreviousClose")
                currency = meta.get("currency", "USD")
                change = round(price - prev_close, 2) if price and prev_close else 0.0
                pct = round((change / prev_close) * 100, 2) if prev_close else 0.0
                sign = "+" if change >= 0 else ""
                return f"[LIVE STOCK DATA] {symbol.upper()} is currently trading at {price} {currency} ({sign}{change} / {sign}{pct}% from previous close of {prev_close} {currency})."
        except Exception as e:
            logger.debug(f"Stock fetch error for {symbol}: {e}")
            return None

    def search_duckduckgo(self, query: str, max_results: int = 3) -> List[str]:
        """Searches DuckDuckGo HTML / Lite for current web results."""
        clean_q = re.sub(r"[^\w\s-]", " ", query).strip()
        results = []

        # Try DDG HTML
        try:
            url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(clean_q)}"
            req = urllib.request.Request(url, headers=self.headers)
            with urllib.request.urlopen(req, timeout=4) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
                snippets = re.findall(r'class="result__snippet[^"]*"[^>]*>(.*?)</a>', html, re.DOTALL)
                for s in snippets[:max_results]:
                    clean = clean_snippet(s)
                    if clean and len(clean) > 20:
                        results.append(clean)
        except Exception:
            pass

        if results:
            return results

        # Try DDG Lite
        try:
            url = "https://lite.duckduckgo.com/lite/"
            data = urllib.parse.urlencode({"q": clean_q}).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers=self.headers)
            with urllib.request.urlopen(req, timeout=4) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
                snippets = re.findall(r'<td class="result-snippet"[^>]*>(.*?)</td>', html, re.DOTALL)
                for s in snippets[:max_results]:
                    clean = clean_snippet(s)
                    if clean and len(clean) > 20:
                        results.append(clean)
        except Exception:
            pass

        return results

    def search_wikipedia(self, query: str, max_results: int = 2) -> List[str]:
        """Fetches concise Wikipedia entries for topics, figures, movies, etc."""
        url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={urllib.parse.quote(query)}&utf8=&format=json"
        req = urllib.request.Request(url, headers={"User-Agent": "DocuChatAI/2.0"})
        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                results = data.get("query", {}).get("search", [])
                snippets = []
                for r in results[:max_results]:
                    title = r.get("title", "")
                    clean = clean_snippet(r.get("snippet", ""))
                    if clean and len(clean) > 15:
                        snippets.append(f"{title}: {clean}")
                return snippets
        except Exception:
            return []

    def get_live_context(self, query: str) -> str:
        """
        Gathers live real-time information for movies, stocks, sports, politics, etc.
        Returns a concise context string to feed to the LLM.
        """
        context_parts = []

        # 1. Check live stock market data
        stock_info = self.get_stock_data(query)
        if stock_info:
            context_parts.append(stock_info)

        # 2. Check DuckDuckGo web results
        web_snippets = self.search_duckduckgo(query, max_results=3)
        if web_snippets:
            context_parts.append("Web Search Updates:\n" + "\n".join(f"- {s}" for s in web_snippets))

        # 3. If web snippets are scarce, augment with Wikipedia
        if len(web_snippets) < 2:
            wiki_snippets = self.search_wikipedia(query, max_results=2)
            if wiki_snippets:
                context_parts.append("Encyclopedia Context:\n" + "\n".join(f"- {s}" for s in wiki_snippets))

        return "\n\n".join(context_parts)

live_web_search = LiveWebSearch()
