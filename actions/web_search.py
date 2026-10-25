#web_search.py
import json
import sys
from pathlib import Path


def _public_http_url(url: str) -> bool:
    """Reject non-web and private-network targets before fetching search results."""
    import ipaddress
    import socket
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return False
        host = parsed.hostname
        try:
            addresses = [ipaddress.ip_address(host)]
        except ValueError:
            addresses = [ipaddress.ip_address(item[4][0]) for item in socket.getaddrinfo(host, None)]
        return bool(addresses) and all(address.is_global for address in addresses)
    except Exception:
        return False


def _scrape_page(result: dict) -> dict:
    """Fetch and extract readable text from one public search result page."""
    import requests
    from bs4 import BeautifulSoup

    url = result.get("url", "")
    base = {"title": result.get("title", ""), "url": url, "snippet": result.get("snippet", "")}
    if not _public_http_url(url):
        return base
    try:
        response = requests.get(
            url, timeout=(0.8, 1.5), allow_redirects=False, stream=True,
            headers={"User-Agent": "SAM Assistant/1.0 (web page reader)"},
        )
        if response.is_redirect:
            from urllib.parse import urljoin
            target = urljoin(url, response.headers.get("Location", ""))
            response.close()
            if not _public_http_url(target):
                return base
            response = requests.get(
                target, timeout=(0.8, 1.5), allow_redirects=False, stream=True,
                headers={"User-Agent": "SAM Assistant/1.0 (web page reader)"},
            )
            if response.is_redirect:
                response.close()
                return base
            url = target
        if response.status_code != 200 or "html" not in response.headers.get("Content-Type", "").lower():
            response.close()
            return base
        chunks, size = [], 0
        for chunk in response.iter_content(65536):
            size += len(chunk)
            if size > 400_000:
                break
            chunks.append(chunk)
        encoding = response.encoding or "utf-8"
        response.close()
        soup = BeautifulSoup(b"".join(chunks), "html.parser", from_encoding=encoding)
        title = soup.title.get_text(" ", strip=True) if soup.title else base["title"]
        for node in soup(["script", "style", "noscript", "nav", "footer", "header", "aside", "form", "svg"]):
            node.decompose()
        main = soup.find("main") or soup.find("article") or soup.body or soup
        text = " ".join(main.stripped_strings)
        return {"title": title[:300], "url": url, "snippet": base["snippet"], "content": text[:1800]}
    except Exception:
        return base


def _web_scrape(query: str, max_results: int = 3) -> list[dict]:
    """Search and read a few public result pages; snippets remain as fallback."""
    from concurrent.futures import ThreadPoolExecutor

    try:
        results = _ddg_search(query, max_results=min(max_results, 2))
    except Exception as exc:
        print(f"[WebSearch] Search provider unavailable: {exc}")
        return []
    if not results:
        return []
    with ThreadPoolExecutor(max_workers=min(2, max(1, len(results)))) as pool:
        return list(pool.map(_scrape_page, results))


def _format_scraped(query: str, results: list[dict]) -> str:
    if not results:
        return f"No web results found for: {query}"
    lines = [f"Scraped web findings for: {query}"]
    for i, result in enumerate(results[:2], 1):
        lines.append(f"{i}. {result.get('title') or 'Web result'}")
        lines.append(result.get("content") or result.get("snippet") or "No readable page text was available.")
        if result.get("url"):
            lines.append(f"Source: {result['url']}")
        lines.append("")
    return "\n".join(lines).strip()

def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR        = _get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"


def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]


def _get_gemini_model() -> str:
    try:
        with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get("gemini_model", "gemini-3.5-flash")
    except Exception:
        return "gemini-3.5-flash"


def _gemini_search(query: str) -> str:
    from google import genai

    client   = genai.Client(api_key=_get_api_key())
    response = client.models.generate_content(
        model=_get_gemini_model(),
        contents=query,
        config={"tools": [{"google_search": {}}]},
    )

    text = ""
    for part in response.candidates[0].content.parts:
        if hasattr(part, "text") and part.text:
            text += part.text

    text = text.strip()
    if not text:
        raise ValueError("Gemini returned an empty response.")
    return text


def _clean_query(query: str) -> str:
    import re
    cleaned = re.sub(r"^(?:what(?:'s|\s+is)?|tell\s+me|find|search(?:\s+for)?|give\s+me|show\s+me)\s+(?:the\s+)?", "", query, flags=re.I)
    cleaned = re.sub(r"\b(?:please|can\s+you|could\s+you)\b", "", cleaned, flags=re.I)
    cleaned = cleaned.strip(" ?.,!\n\t")
    return cleaned or query


def _ddg_search(query: str, max_results: int = 6) -> list[dict]:
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS

    cleaned = _clean_query(query)
    results = []
    for q_attempt in ([cleaned, query] if cleaned != query else [cleaned]):
        try:
            with DDGS(timeout=8) as ddgs:
                for r in ddgs.text(q_attempt, max_results=max_results):
                    results.append({
                        "title":   r.get("title",  ""),
                        "snippet": r.get("body",   ""),
                        "url":     r.get("href",   ""),
                    })
            if results:
                break
        except Exception as e:
            print(f"[WebSearch] DDG text attempt failed for {q_attempt!r}: {e}")
    return results


def _ddg_news(query: str, max_results: int = 8) -> list[dict]:
    """DDG news search — returns actual articles, not website homepages."""
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS

    cleaned = _clean_query(query)
    results = []
    try:
        with DDGS(timeout=8) as ddgs:
            for r in ddgs.news(cleaned, max_results=max_results):
                results.append({
                    "title":   r.get("title",  ""),
                    "snippet": r.get("body",   ""),
                    "url":     r.get("url",    ""),
                    "source":  r.get("source", ""),
                })
    except Exception as e:
        print(f"[WebSearch] ⚠️ DDG news() failed ({e}) — falling back to text search")
        results = _ddg_search(cleaned, max_results=max_results)
    return results


def _format_ddg(query: str, results: list[dict]) -> str:
    if not results:
        return f"No results found for: {query}"

    lines = [f"Search results for: {query}\n"]
    for i, r in enumerate(results, 1):
        if r.get("title"):   lines.append(f"{i}. {r['title']}")
        if r.get("snippet"): lines.append(f"   {r['snippet']}")
        if r.get("url"):     lines.append(f"   Source: {r['url']}")
        lines.append("")
    return "\n".join(lines).strip()


def _format_news(query: str, results: list[dict]) -> str:
    if not results:
        return f"No news found for: {query}"

    lines = [f"Latest news: {query}\n"]
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        if not title:
            continue
        src = f"  [{r['source']}]" if r.get("source") else ""
        lines.append(f"{i}. {title}{src}")
        if r.get("snippet"):
            lines.append(f"   {r['snippet'][:140]}")
        if r.get("url"):
            lines.append(f"   {r['url']}")
        lines.append("")
    return "\n".join(lines).strip()


# ── Briefing helper ────────────────────────────────────────────────────────────

def _gemini_headlines(n: int = 5) -> tuple[list[str], str]:
    """
    Fetches current headlines via Gemini grounded search.
    Optimised for speed: minimal prompt + strict token cap.
    Returns (headline_list, raw_text_for_display).
    """
    import re
    from google import genai

    client = genai.Client(api_key=_get_api_key())
    response = client.models.generate_content(
        model=_get_gemini_model(),
        contents=f"Current world news: {n} headlines. Numbered list, titles only.",
        config={"tools": [{"google_search": {}}]},
    )

    raw = ""
    for part in response.candidates[0].content.parts:
        if hasattr(part, "text") and part.text:
            raw += part.text

    headlines = []
    for line in raw.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        # Only accept lines that begin with a number — skips preamble/closing sentences
        if not re.match(r'^[\d]+[.\)\-]', line):
            continue
        clean = re.sub(r'^[\d]+[.\)\-]\s*', '', line)
        clean = re.sub(r'^\*+\s*',          '', clean).strip()
        if clean and len(clean) > 10:
            headlines.append(clean)

    return headlines[:n], raw.strip()


# ── Modes ──────────────────────────────────────────────────────────────────────

def _search(query: str) -> str:
    """Default search reads up to two public result pages, with snippets as fallback."""
    try:
        results = _web_scrape(query, max_results=2)
        if results and any(r.get("content") or r.get("snippet") for r in results):
            return _format_scraped(query, results)
    except Exception as e:
        print(f"[WebSearch] Page reading failed ({e}) — using search snippets...")

    try:
        results = _ddg_search(query, max_results=4)
        if results:
            return _format_ddg(query, results)
    except Exception as e:
        print(f"[WebSearch] Snippet fallback failed: {e}")

    return "Web search is temporarily unavailable. Please try again shortly."


def _news(query: str) -> str:
    """
    Runs Gemini grounded search AND DDG news in parallel.
    Returns whichever delivers a valid result first; cancels the other.
    """
    import threading

    gemini_query = f"latest news today: {query}" if query else "top world news today"
    ddg_query    = query if query else "world news today"

    result_box  = [None]   # first valid result lands here
    lock        = threading.Lock()
    done_evt    = threading.Event()
    failures    = [0]

    def _store(r: str) -> None:
        if r and len(r) > 60:
            with lock:
                if result_box[0] is None:
                    result_box[0] = r
            done_evt.set()
        else:
            with lock:
                failures[0] += 1
                if failures[0] >= 2:   # both failed — unblock caller
                    done_evt.set()

    def _try_gemini():
        try:
            _store(_gemini_search(gemini_query))
        except Exception as e:
            print(f"[WebSearch] ⚠️ Gemini news failed ({e})")
            _store("")

    def _try_ddg():
        try:
            results = _ddg_news(ddg_query, max_results=8)
            _store(_format_news(ddg_query, results))
        except Exception as e:
            print(f"[WebSearch] ⚠️ DDG news failed ({e})")
            _store("")

    threading.Thread(target=_try_gemini, daemon=True).start()
    threading.Thread(target=_try_ddg,    daemon=True).start()

    done_evt.wait(timeout=10.0)
    return result_box[0] or f"No news found for: {query}"


def _research(query: str) -> str:
    """
    Deep dive — asks Gemini for a comprehensive answer with context.
    Falls back to a wider DDG fetch.
    """
    research_query = (
        f"Comprehensive, detailed explanation of: {query}. "
        "Include background context, key facts, current state, and important nuances."
    )
    try:
        return _gemini_search(research_query)
    except Exception as e:
        print(f"[WebSearch] ⚠️ Research Gemini failed ({e}) — DDG fallback...")
        results = _ddg_search(query, max_results=10)
        return _format_ddg(query, results)


def _price(query: str) -> str:
    """Product price lookup — searches for current market prices."""
    price_query = f"current price of {query} — how much does it cost today"
    try:
        return _gemini_search(price_query)
    except Exception as e:
        print(f"[WebSearch] ⚠️ Price Gemini failed ({e}) — DDG fallback...")
        results = _ddg_search(f"{query} price buy", max_results=6)
        return _format_ddg(query, results)


def _compare(items: list[str], aspect: str) -> str:
    query = (
        f"Compare {', '.join(items)} in terms of {aspect}. "
        "Give specific facts and data."
    )
    try:
        return _gemini_search(query)
    except Exception as e:
        print(f"[WebSearch] ⚠️ Gemini compare failed: {e} — falling back to DDG")

    all_results: dict[str, list] = {}
    for item in items:
        try:
            all_results[item] = _ddg_search(f"{item} {aspect}", max_results=3)
        except Exception:
            all_results[item] = []

    lines = [f"Comparison — {aspect.upper()}", "─" * 40]
    for item in items:
        lines.append(f"\n▸ {item}")
        for r in all_results.get(item, [])[:2]:
            if r.get("snippet"):
                lines.append(f"  • {r['snippet']}")
            if r.get("url"):
                lines.append(f"    {r['url']}")
    return "\n".join(lines)


# ── Public entry point ─────────────────────────────────────────────────────────

def web_search(
    parameters:     dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params = parameters if isinstance(parameters, dict) else {}
    query  = params.get("query", "").strip()
    mode   = params.get("mode",  "search").lower().strip()
    items  = params.get("items", [])
    aspect = params.get("aspect", "general").strip() or "general"

    if not query and not items:
        return "Please provide a search query."

    if items and mode not in ("compare",):
        mode = "compare"
    elif mode == "search" and query and any(w in query.lower() for w in ("news", "headline", "headlines", "breaking")):
        mode = "news"

    if player:
        player.write_log(f"[Search:{mode}] {query or ', '.join(items)}")

    print(f"[WebSearch] 🔍 mode={mode!r}  query={query!r}")

    # Visually pop open the browser tab for the user
    try:
        import webbrowser
        import urllib.parse
        search_term = query if query else " ".join(items)
        if search_term:
            url = f"https://www.google.com/search?q={urllib.parse.quote(search_term)}"
            webbrowser.open(url)
    except Exception:
        pass

    try:
        if mode == "compare" and items:
            return _compare(items, aspect)
        if mode == "news":
            return _news(query)
        if mode == "research":
            return _research(query)
        if mode == "price":
            return _price(query)
        return _search(query)

    except Exception as e:
        print(f"[WebSearch] ❌ All backends failed: {e}")
        return f"Search failed: {e}"
