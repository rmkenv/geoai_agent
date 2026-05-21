"""
GeoAI Content Agent — nightly runner
Sources:
  1. arXiv API (single batched query) — rate-limit safe
  2. DuckDuckGo HTML — blog posts, GitHub releases, industry news
Summarizes via Ollama Cloud, writes to data/feed.json.
"""

import os
import sys
import json
import time
import datetime
import hashlib
import urllib.request
import urllib.error
import urllib.parse
import re
from pathlib import Path

# ── Config ───────────────────────────────────────────────────────────────────
OLLAMA_API_URL = os.environ.get("OLLAMA_API_URL", "").strip()
OLLAMA_MODEL   = os.environ.get("OLLAMA_MODEL",   "").strip()
OLLAMA_TOKEN   = os.environ.get("OLLAMA_TOKEN",   "").strip()

FEED_PATH      = Path(__file__).parent.parent / "data" / "feed.json"
MAX_ITEMS      = 60
MAX_NEW_TODAY  = 15
LOOKBACK_DAYS  = 30

# Single OR-joined arXiv query — one request instead of 10
ARXIV_QUERY = (
    "geospatial+AI+OR+remote+sensing+deep+learning"
    "+OR+satellite+image+foundation+model"
    "+OR+spatial+machine+learning"
    "+OR+SAR+flood+detection"
    "+OR+NDVI+crop+yield"
    "+OR+LiDAR+point+cloud+classification"
)
ARXIV_MAX_RESULTS = 60  # pull more in one shot

WEB_QUERIES = [
    "GeoAI geospatial AI news 2025",
    "remote sensing AI open source tool 2025",
    "satellite imagery machine learning 2025",
]

SKIP_DOMAINS = {
    "twitter.com", "x.com", "facebook.com", "linkedin.com",
    "reddit.com", "youtube.com", "instagram.com", "researchgate.net",
}

TAGS_VOCAB = [
    "foundation-models", "remote-sensing", "satellite-imagery", "urban-AI",
    "crop-monitoring", "flood-detection", "change-detection", "object-detection",
    "segmentation", "time-series", "point-cloud", "LiDAR", "SAR",
    "spatial-reasoning", "LLM", "diffusion-models", "vector-tiles",
    "open-source", "benchmark", "real-time",
]

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


# ── Validate secrets ──────────────────────────────────────────────────────────

def validate_config():
    missing = []
    if not OLLAMA_API_URL:
        missing.append("OLLAMA_API_URL")
    if not OLLAMA_MODEL:
        missing.append("OLLAMA_MODEL")
    if missing:
        print(f"[agent] ERROR: missing env vars: {', '.join(missing)}")
        sys.exit(1)
    print(f"[agent] config ok — model={OLLAMA_MODEL}")


# ── ArXiv — single batched request ───────────────────────────────────────────

def fetch_arxiv_batch() -> list[dict]:
    """One request with an OR query — avoids 429s from rapid sequential calls."""
    url = (
        f"http://export.arxiv.org/api/query"
        f"?search_query=all:{ARXIV_QUERY}"
        f"&sortBy=submittedDate&sortOrder=descending"
        f"&max_results={ARXIV_MAX_RESULTS}"
    )
    print(f"[arxiv] single batch request, max_results={ARXIV_MAX_RESULTS}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "GeoAI-Agent/1.0 (research bot)"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            xml = resp.read().decode()
    except Exception as e:
        print(f"[arxiv] ERROR: {e}")
        return []

    cutoff     = (datetime.date.today() - datetime.timedelta(days=LOOKBACK_DAYS)).isoformat()
    raw_count  = len(xml.split("<entry>")) - 1
    print(f"[arxiv] got {raw_count} raw entries, cutoff={cutoff}")

    entries = []
    for entry_xml in xml.split("<entry>")[1:]:
        def tag(t):
            s = entry_xml.find(f"<{t}>")
            e = entry_xml.find(f"</{t}>")
            return entry_xml[s + len(t) + 2:e].strip() if s != -1 else ""

        arxiv_id  = tag("id").split("/abs/")[-1].strip()
        title     = tag("title").replace("\n", " ").strip()
        summary   = tag("summary").replace("\n", " ").strip()
        published = tag("published")[:10]

        if published < cutoff:
            continue

        authors = []
        for chunk in entry_xml.split("<author>")[1:]:
            ns = chunk.find("<name>") + 6
            ne = chunk.find("</name>")
            if ns > 5:
                authors.append(chunk[ns:ne].strip())

        if title and arxiv_id:
            entries.append({
                "id":        arxiv_id,
                "title":     title,
                "snippet":   summary[:800],
                "authors":   authors[:3],
                "published": published,
                "url":       f"https://arxiv.org/abs/{arxiv_id}",
                "source":    "arxiv",
            })

    print(f"[arxiv] {len(entries)} entries within {LOOKBACK_DAYS} days")
    return entries


# ── DuckDuckGo HTML scrape ────────────────────────────────────────────────────

def fetch_ddg(query: str, max_results: int = 6) -> list[dict]:
    params = urllib.parse.urlencode({"q": query, "kl": "us-en"})
    url    = f"https://html.duckduckgo.com/html/?{params}"
    req    = urllib.request.Request(url, headers=BROWSER_HEADERS)

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            html = resp.read().decode(errors="ignore")
    except Exception as e:
        print(f"  [ddg] ERROR fetching '{query}': {e}")
        return []

    result_blocks = re.findall(
        r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?class="result__snippet"[^>]*>(.*?)</a>',
        html, re.DOTALL
    )
    print(f"  [ddg] '{query[:45]}' → {len(result_blocks)} raw blocks")

    results = []
    for href, title_html, snippet_html in result_blocks[:max_results]:
        m        = re.search(r'uddg=([^&"]+)', href)
        real_url = urllib.parse.unquote(m.group(1)) if m else href
        title    = re.sub(r'<[^>]+>', '', title_html).strip()
        # decode HTML entities
        title    = title.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&#39;", "'").replace("&quot;", '"')
        snippet  = re.sub(r'<[^>]+>', '', snippet_html).strip()

        if not real_url.startswith("http") or not title:
            continue
        try:
            domain = urllib.parse.urlparse(real_url).netloc.lstrip("www.")
        except Exception:
            continue
        if domain in SKIP_DOMAINS or "arxiv.org" in real_url:
            continue

        results.append({
            "id":        hashlib.md5(real_url.encode()).hexdigest()[:12],
            "title":     title,
            "snippet":   snippet[:600],
            "authors":   [],
            "published": datetime.date.today().isoformat(),
            "url":       real_url,
            "source":    "web",
        })
    return results


# ── Collect all candidates ────────────────────────────────────────────────────

def collect_candidates() -> list[dict]:
    seen, candidates = set(), []

    # arXiv — one request
    for paper in fetch_arxiv_batch():
        uid = hashlib.md5(paper["id"].encode()).hexdigest()
        if uid not in seen:
            seen.add(uid)
            paper["uid"] = uid
            candidates.append(paper)

    # DDG — a few queries with polite gaps
    print(f"\n[agent] ── DuckDuckGo ──")
    for query in WEB_QUERIES:
        results = fetch_ddg(query, max_results=6)
        added = 0
        for item in results:
            uid = hashlib.md5(item["url"].encode()).hexdigest()
            if uid not in seen:
                seen.add(uid)
                item["uid"] = uid
                candidates.append(item)
                added += 1
        print(f"  → {len(results)} results, {added} new unique")
        time.sleep(3)

    print(f"\n[agent] total candidates: {len(candidates)}")
    return candidates


# ── Ollama ────────────────────────────────────────────────────────────────────

def ollama_chat(messages: list[dict], max_tokens: int = 800) -> str:
    payload = json.dumps({
        "model":    OLLAMA_MODEL,
        "messages": messages,
        "stream":   False,
        "options":  {"num_predict": max_tokens, "temperature": 0.3},
    }).encode()

    headers = {"Content-Type": "application/json"}
    if OLLAMA_TOKEN:
        headers["Authorization"] = f"Bearer {OLLAMA_TOKEN}"

    req = urllib.request.Request(OLLAMA_API_URL, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read())
        return data.get("message", {}).get("content", "").strip()
    except Exception as e:
        print(f"  [ollama] ERROR: {e}")
        return ""


# Keep the prompt short so the model has room to complete the JSON
SYSTEM_PROMPT = (
    "You are a GeoAI content editor. "
    "Always respond with a single valid JSON object and nothing else. "
    "No markdown, no explanation, no trailing text."
)

ENRICH_TMPL = """\
Title: {title}
Snippet: {snippet}

Return this JSON object with all fields filled in:
{{"headline":"<10-15 word headline>","tldr":"<2 sentences>","significance":"<1 sentence>","tags":[<2-4 from {tags}>],"readtime":<1-5>,"difficulty":"<introductory|intermediate|advanced>"}}"""


def enrich_item(item: dict) -> dict | None:
    prompt = ENRICH_TMPL.format(
        title   = item["title"][:200],
        snippet = item["snippet"][:400],   # keep input short
        tags    = json.dumps(TAGS_VOCAB),
    )

    raw = ollama_chat(
        [{"role": "system", "content": SYSTEM_PROMPT},
         {"role": "user",   "content": prompt}],
        max_tokens=800,  # plenty of room to finish
    )
    if not raw:
        return None

    # strip any accidental fences
    raw = re.sub(r'^```[a-z]*\n?', '', raw.strip())
    raw = re.sub(r'\n?```$',       '', raw.strip())
    raw = raw.strip()

    # extract first { ... } block in case model adds preamble
    m = re.search(r'\{.*\}', raw, re.DOTALL)
    if not m:
        print(f"  [enrich] no JSON object found in response")
        print(f"  [enrich] raw: {raw[:200]}")
        return None

    try:
        enriched = json.loads(m.group(0))
    except json.JSONDecodeError as ex:
        print(f"  [enrich] JSON parse failed: {ex}")
        print(f"  [enrich] raw: {raw[:200]}")
        return None

    return {
        "uid":          item["uid"],
        "source":       item["source"],
        "url":          item["url"],
        "arxiv_id":     item.get("id", "") if item["source"] == "arxiv" else "",
        "title":        item["title"],
        "authors":      item.get("authors", []),
        "published":    item["published"],
        "curated_at":   datetime.date.today().isoformat(),
        "headline":     enriched.get("headline", item["title"]),
        "tldr":         enriched.get("tldr", ""),
        "significance": enriched.get("significance", ""),
        "tags":         enriched.get("tags", []),
        "readtime":     int(enriched.get("readtime", 3)),
        "difficulty":   enriched.get("difficulty", "intermediate"),
    }


# ── Feed I/O ──────────────────────────────────────────────────────────────────

def load_feed() -> list[dict]:
    print(f"[feed] loading from {FEED_PATH}")
    if FEED_PATH.exists():
        data = json.loads(FEED_PATH.read_text())
        print(f"[feed] {len(data)} existing items")
        return data
    print("[feed] no existing feed — starting fresh")
    return []


def save_feed(items: list[dict]) -> None:
    FEED_PATH.parent.mkdir(parents=True, exist_ok=True)
    FEED_PATH.write_text(json.dumps(items, indent=2, ensure_ascii=False))
    verify = json.loads(FEED_PATH.read_text())
    print(f"[feed] saved & verified: {len(verify)} items on disk")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"[agent] ── GeoAI Agent {datetime.date.today()} ──")
    validate_config()

    existing      = load_feed()
    existing_real = [i for i in existing if not str(i.get("uid", "")).startswith("seed-")]

    # expire items older than LOOKBACK_DAYS so they don't permanently block re-discovery
    cutoff        = (datetime.date.today() - datetime.timedelta(days=LOOKBACK_DAYS)).isoformat()
    existing_live = [i for i in existing_real if i.get("curated_at", "9999") >= cutoff]
    expired_count = len(existing_real) - len(existing_live)
    if expired_count:
        print(f"[agent] expired {expired_count} items older than {LOOKBACK_DAYS} days")

    existing_uids = {i["uid"] for i in existing_live}
    print(f"[agent] {len(existing_live)} live items, {len(existing_uids)} UIDs to skip")

    candidates = collect_candidates()
    new_items  = [c for c in candidates if c["uid"] not in existing_uids]
    print(f"[agent] {len(new_items)} new to enrich (cap={MAX_NEW_TODAY})")

    if not new_items:
        print("[agent] nothing new — feed unchanged")
        save_feed(existing_live)
        return

    enriched = []
    for item in new_items[:MAX_NEW_TODAY]:
        src = item["source"].upper()
        print(f"\n[{src}] {item['title'][:70]}")
        result = enrich_item(item)
        if result:
            enriched.append(result)
            print(f"  ✓ {result['headline'][:65]}")
        else:
            print(f"  ✗ failed")
        time.sleep(2)

    combined = (enriched + existing_live)[:MAX_ITEMS]
    arxiv_n  = sum(1 for e in enriched if e["source"] == "arxiv")
    web_n    = sum(1 for e in enriched if e["source"] == "web")
    print(f"\n[agent] added={len(enriched)} (arxiv={arxiv_n} web={web_n}) total={len(combined)}")
    save_feed(combined)


if __name__ == "__main__":
    main()
