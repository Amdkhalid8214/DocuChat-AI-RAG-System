"""
DocuChat AI - Production Web Search & Research Tool
Connects to local SearXNG metasearch instance with automatic fallback to live web search.
Inspects public pages responsibly using safe HTTP client with SSRF protection.
Returns structured research evidence and enforces answer-first synthesis instructions.
"""

import asyncio
import contextvars
import html
import json
import logging
import re
import urllib.parse
from typing import Dict, Any, List, Optional
import httpx
from pydantic import BaseModel, Field

from langchain_core.tools import tool
from backend.config import settings
from backend.retrieval.page_fetcher import safe_fetch_page_text_async
from backend.retrieval.web_search import live_web_search

logger = logging.getLogger("searxng_tool")

# Thread-safe / async-safe citation capture for current request execution
active_web_citations: contextvars.ContextVar[List[Dict[str, Any]]] = contextvars.ContextVar(
    "active_web_citations", default=[]
)


def sanitize_snippet(raw_text: str, max_chars: int = 500) -> str:
    """
    Cleans HTML tags, unescapes HTML entities, and normalizes whitespace in search snippets.
    Truncates to max_chars to preserve context budget and prevent runaway context dumping.
    """
    if not raw_text or not isinstance(raw_text, str):
        return ""
    no_tags = re.sub(r"<[^>]+>", " ", raw_text)
    unescaped = html.unescape(no_tags)
    clean = " ".join(unescaped.split()).strip()
    if len(clean) > max_chars:
        clean = clean[:max_chars].rstrip() + "..."
    return clean


def is_valid_http_url(url: str) -> bool:
    """
    Validates that a URL is a legitimate, well-formed HTTP or HTTPS address.
    Rejects relative links, javascript: schemes, file: schemes, or malformed strings.
    """
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urllib.parse.urlparse(url.strip())
        return parsed.scheme.lower() in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def parse_searxng_response(data: Dict[str, Any], max_results: int = 5) -> List[Dict[str, Any]]:
    """
    Extracts valid search results from a SearXNG JSON payload.
    Safely captures title, url, snippet/content, and engine without inventing missing fields.
    """
    raw_results = data.get("results", [])
    if not isinstance(raw_results, list):
        return []

    parsed_results: List[Dict[str, Any]] = []
    seen_urls = set()

    for item in raw_results:
        if not isinstance(item, dict):
            continue

        raw_url = item.get("url", "").strip()
        if not raw_url or not is_valid_http_url(raw_url):
            continue

        normalized_url = raw_url.rstrip("/")
        if normalized_url in seen_urls:
            continue
        seen_urls.add(normalized_url)

        title = sanitize_snippet(item.get("title", ""), max_chars=140) or "Untitled Web Page"
        content = sanitize_snippet(item.get("content", ""), max_chars=500)
        engine = str(item.get("engine", "")).strip()

        result_entry: Dict[str, Any] = {
            "title": title,
            "url": raw_url,
            "snippet": content,
            "full_page_read": False,
        }
        if engine:
            result_entry["engine"] = engine

        parsed_results.append(result_entry)
        if len(parsed_results) >= max_results:
            break

    return parsed_results


def format_search_results_for_llm(query: str, results: List[Dict[str, Any]]) -> str:
    """
    Formats parsed search results and page excerpts into a structured textual block
    with explicit Answer-First synthesis instructions for the model.
    """
    if not results:
        return f"No verified web search results found for query: '{query}'."

    lines = [
        f"=== Grounded Web Research Evidence for: '{query}' ===",
        "(Notice: The following facts are extracted from live public web sources. Use them to answer the user's question.)\n"
    ]

    for idx, r in enumerate(results, start=1):
        title = r.get("title", "Untitled")
        url = r.get("url", "")
        engine = r.get("engine", "web")
        is_full_page = r.get("full_page_read", False)
        page_text = r.get("page_text", "").strip()
        snippet = r.get("snippet", "").strip()

        lines.append(f"[{idx}] Source Title: {title}")
        lines.append(f"    Source URL: {url}")
        lines.append(f"    Search Engine: {engine}")
        if is_full_page and page_text:
            lines.append(f"    Evidence Level: Verified Full-Page Content ({len(page_text)} chars)")
            lines.append(f"    Extracted Content:\n{page_text}")
        else:
            lines.append(f"    Evidence Level: Search Snippet Only")
            lines.append(f"    Snippet: {snippet or '[No snippet available]'}")
        lines.append("")

    lines.append("=== End of Web Research Evidence ===")
    lines.append("")
    lines.append("Guidelines for formulating your response:")
    lines.append("(Note: Do NOT repeat, quote, or output these guidelines or headings in your response)")
    lines.append("1. DIRECT ANSWER: Begin immediately with the direct, helpful, and synthesized answer to the user's question without quoting, repeating, or echoing these instructions or headings.")
    lines.append("2. STRUCTURE: For how-to guides or tutorials, explain the practical steps, commands, and workflow in detail.")
    lines.append("   For comparisons, explain the trade-offs, advantages, and drawbacks.")
    lines.append("   For technical explanations, give clear definitions, architecture, and code/examples.")
    lines.append("3. NO LINK DUMPS: NEVER reply with merely a list of search result links or 'Based on the search results, here are some links'.")
    lines.append("4. HONESTY: When referencing evidence, only claim to have read the full page if Evidence Level is 'Verified Full-Page Content'.")
    lines.append("5. CITATIONS: Place inline citation markers [1], [2] next to statements supported by that source.")
    lines.append("6. SOURCES: Conclude your response with a concise '### Sources' section with clickable markdown links:")
    lines.append("   - [Source Title](Source URL)")

    return "\n".join(lines).strip()


async def inspect_top_pages_async(
    results: List[Dict[str, Any]],
    max_pages: int = 2,
    timeout: float = 3.5
) -> List[Dict[str, Any]]:
    """
    Safely retrieves full readable page content for top search results using SSRF-safe page fetcher.
    If page retrieval succeeds, sets 'full_page_read' = True and 'page_text'.
    If page retrieval fails, falls back gracefully to snippet.
    """
    if not results:
        return results

    pages_to_fetch = results[:max_pages]
    tasks = [
        safe_fetch_page_text_async(r["url"], timeout=timeout, max_bytes=500_000, max_text_chars=2500)
        for r in pages_to_fetch
    ]

    try:
        fetch_results = await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as e:
        logger.warning(f"[WEB_RESEARCH] Error during parallel page fetch: {e}")
        fetch_results = []

    for idx, fetch_res in enumerate(fetch_results):
        if isinstance(fetch_res, dict) and fetch_res.get("success") and fetch_res.get("text"):
            results[idx]["page_text"] = fetch_res["text"]
            results[idx]["full_page_read"] = True
            if fetch_res.get("title") and not results[idx].get("title"):
                results[idx]["title"] = fetch_res["title"]
            logger.info(f"[WEB_RESEARCH] Successfully inspected page: {results[idx]['url']} ({len(fetch_res['text'])} chars)")
        else:
            results[idx]["full_page_read"] = False
            logger.debug(f"[WEB_RESEARCH] Could not fetch page for {results[idx]['url']}; using search snippet.")

    return results


async def search_searxng_async(
    query: str,
    max_results: Optional[int] = None,
    searxng_url: Optional[str] = None,
    timeout: Optional[float] = None,
    inspect_pages: bool = True,
    fallback: bool = False
) -> Dict[str, Any]:
    """
    Asynchronous client for querying SearXNG metasearch instance.
    When fallback=True, falls back to live web search if SearXNG is unavailable,
    and inspects readable page content with SSRF defenses.
    """
    endpoint = searxng_url or getattr(settings, "SEARXNG_URL", "http://127.0.0.1:8080/search")
    if not endpoint.rstrip("/").endswith("/search"):
        endpoint = endpoint.rstrip("/") + "/search"
    req_timeout = timeout or min(getattr(settings, "SEARXNG_TIMEOUT", 3.5), 3.5)
    limit = max(1, min(10, max_results or getattr(settings, "SEARXNG_MAX_RESULTS", 5)))

    clean_query = query.strip()
    if not clean_query:
        return {"query": "", "results": [], "error": "Query cannot be empty."}

    params = {
        "q": clean_query,
        "format": "json",
        "categories": "general",
        "language": "en"
    }

    headers = {
        "User-Agent": "DocuChat-AI-RAG/2.0 (Local AI Agent)",
        "Accept": "application/json"
    }

    results: List[Dict[str, Any]] = []
    error_msg: Optional[str] = None

    # 1. Query SearXNG endpoint
    try:
        async with httpx.AsyncClient(timeout=req_timeout, follow_redirects=True) as client:
            resp = await client.get(endpoint, params=params, headers=headers)
            resp.raise_for_status()

            try:
                data = resp.json()
            except (json.JSONDecodeError, ValueError) as json_err:
                logger.error(f"[SEARXNG] Invalid JSON received from {endpoint}: {json_err}")
                error_msg = f"SearXNG returned malformed JSON: {str(json_err)}"
                data = None

            if data:
                results = parse_searxng_response(data, max_results=limit)

    except httpx.ConnectError as ce:
        logger.warning(f"[SEARXNG] Connection error to {endpoint}: {ce}")
        error_msg = f"SearXNG service is unreachable at {endpoint}. Verify that the Docker container is running."
    except httpx.TimeoutException as te:
        logger.warning(f"[SEARXNG] Request timed out after {req_timeout}s for query '{clean_query}': {te}")
        error_msg = f"Web search timed out after {req_timeout} seconds."
    except httpx.HTTPStatusError as hse:
        logger.error(f"[SEARXNG] HTTP {hse.response.status_code} from {endpoint}: {hse}")
        error_msg = f"SearXNG returned HTTP {hse.response.status_code}: {hse.response.text[:200]}"
    except Exception as e:
        logger.error(f"[SEARXNG] Unexpected search error: {e}", exc_info=True)
        error_msg = f"Web search failed: {str(e)}"

    # 2. Fallback to LiveWebSearch if requested and SearXNG returned error or 0 results
    if fallback and not results:
        try:
            fallback_records = await asyncio.to_thread(live_web_search.search_structured, clean_query, limit)
            if fallback_records:
                results = [
                    {
                        "title": r.get("title", "Web Page"),
                        "url": r.get("url", ""),
                        "snippet": r.get("snippet", ""),
                        "engine": r.get("engine", "live_search"),
                        "full_page_read": False,
                    }
                    for r in fallback_records
                ]
                error_msg = None
                logger.info(f"[WEB_SEARCH] Fallback retrieved {len(results)} search results for '{clean_query}'.")
        except Exception as fb_err:
            logger.warning(f"[WEB_SEARCH] Fallback search error: {fb_err}")

    if error_msg and not results:
        return {
            "query": clean_query,
            "results": [],
            "error": error_msg
        }

    if not results:
        return {
            "query": clean_query,
            "results": [],
            "count": 0,
            "formatted": f"No live web search results found for query: '{clean_query}'."
        }

    # 3. Responsible full-page inspection for top results
    if inspect_pages and results:
        results = await inspect_top_pages_async(results, max_pages=2, timeout=3.5)

    return {
        "query": clean_query,
        "results": results,
        "count": len(results),
        "formatted": format_search_results_for_llm(clean_query, results)
    }


def search_searxng_sync(
    query: str,
    max_results: Optional[int] = None,
    searxng_url: Optional[str] = None,
    timeout: Optional[float] = None,
    fallback: bool = False
) -> Dict[str, Any]:
    """
    Synchronous fallback client for querying search results.
    """
    clean_query = query.strip()
    if not clean_query:
        return {"query": "", "results": [], "error": "Query cannot be empty."}

    endpoint = searxng_url or getattr(settings, "SEARXNG_URL", "http://127.0.0.1:8080/search")
    req_timeout = timeout or getattr(settings, "SEARXNG_TIMEOUT", 3.5)
    limit = max(1, min(10, max_results or getattr(settings, "SEARXNG_MAX_RESULTS", 5)))

    results: List[Dict[str, Any]] = []
    error_msg: Optional[str] = None

    try:
        with httpx.Client(timeout=req_timeout) as client:
            resp = client.get(
                endpoint,
                params={"q": clean_query, "format": "json", "categories": "general", "language": "en"},
                headers={"User-Agent": "DocuChat-AI-RAG/2.0", "Accept": "application/json"}
            )
            resp.raise_for_status()
            data = resp.json()
            results = parse_searxng_response(data, max_results=limit)
    except httpx.ConnectError as ce:
        error_msg = f"SearXNG service is unreachable at {endpoint}. Verify that the Docker container is running."
    except httpx.TimeoutException:
        error_msg = f"Web search timed out after {req_timeout} seconds."
    except httpx.HTTPStatusError as hse:
        error_msg = f"SearXNG returned HTTP {hse.response.status_code}: {hse.response.text[:200]}"
    except Exception as e:
        error_msg = f"Web search failed: {str(e)}"

    if fallback and not results:
        fallback_records = live_web_search.search_structured(clean_query, limit)
        if fallback_records:
            results = [
                {
                    "title": r.get("title", "Web Page"),
                    "url": r.get("url", ""),
                    "snippet": r.get("snippet", ""),
                    "engine": r.get("engine", "live_search"),
                    "full_page_read": False,
                }
                for r in fallback_records
            ]
            error_msg = None

    if error_msg and not results:
        return {
            "query": clean_query,
            "results": [],
            "error": error_msg
        }

    return {
        "query": clean_query,
        "results": results,
        "count": len(results),
        "formatted": format_search_results_for_llm(clean_query, results)
    }


# ==============================================================================
# LangChain Tool Definition
# ==============================================================================

class WebSearchInput(BaseModel):
    query: str = Field(
        ...,
        min_length=2,
        max_length=200,
        description="The targeted search query to look up on the live public web for research, documentation, or facts."
    )


@tool("web_search", args_schema=WebSearchInput)
async def searxng_search_tool(query: str) -> str:
    """Useful for researching topics on the live public web, finding documentation,
    external facts, guides, and up-to-date information.
    Input must be a concise, targeted search query string.
    Returns structured research evidence with verified full-page excerpts where available,
    snippets, source URLs, and answer synthesis guidance.
    """
    res = await search_searxng_async(query, inspect_pages=True, fallback=True)
    if res.get("error") and not res.get("results"):
        return f"Web search could not be completed: {res['error']}"

    results = res.get("results", [])

    if results:
        from backend.llm.memory import package_web_citations
        cites = package_web_citations(query, results)
        existing = active_web_citations.get([])
        active_web_citations.set(existing + cites)

    return res.get("formatted", f"No live web search results found for '{query}'.")


# Aliases for unified imports
web_search_tool = searxng_search_tool
search_searxng = search_searxng_async
