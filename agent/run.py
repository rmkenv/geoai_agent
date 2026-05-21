"""
GeoAI Content Agent — nightly runner
Sources:
  1. arXiv API       — recent academic papers
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
MAX_NEW_TODAY  = 12
LOOKBACK_DAYS  = 14

ARXIV_TOPICS = [
    "geospatial artificial intelligence",
    "remote sensing deep learning segmentation",
    "satellite image foundation model",
    "spatial machine learning geographic",
    "large language model geospatial",
    "SAR flood mapping neural network",
    "NDVI crop yield prediction",
    "urban heat island detection satellite",
    "change detection multispectral",
    "point cloud lidar classification",
]

WEB_QUERIES = [
    "GeoAI geospatial AI news",
    "remote sensing AI open source release",
    "satellite imagery machine learning tool",
    "geospatial foundation model release",
    "ESRI NASA ESA AI geospatial announcement",
]

# domains to skip — paywalls, social, noise
SKIP_DOMAINS = {
    "twitter.com", "x.com", "facebook.com", "linkedin.com",
    "reddit.com", "youtube.com", "instagram.com",
    "researchgate.net",   # just paper stubs
    "semanticscholar.org",
}

TAGS_VOCAB = [
    "foundation-models", "remote-sensing", "satellite-imagery", "urban-AI",
    "crop-monitoring", "flood-detection", "change-detection", "object-detection",
    "segmentation", "time-series", "point-cloud", "LiDAR", "SAR",
    "spatial-reasoning", "LLM", "diffusion-models", "vector-tiles",
    "open-source", "benchmark", "real-time",
]


# ── Validate secrets ──────────────────────────────────────────────────────────

def validate_config():
    missing = []
    if not OLLAMA_API_URL:
        missing.append("OLLAMA_API_URL")
    if not OLLAMA_MODEL:
        missing.append("OLLAMA_MODEL")
    if missing:
        print(f"[agent] ERROR: missing env vars: {', '.join(missing)}")
        print("[agent] Add them under repo → Settings → Secrets and variables → Actions")
        sys.exit(1)
    print(f"[agent] config ok — model={OLLAMA_MODEL}")


# ── ArXiv ─────────────────────────────────────────────────────────────────────

def fetch_arxiv(query: str, max_results: int = 10) -> list[dict]:
    q = urllib.parse.quote(query)
    url = (
        f"http://export.arxiv.org/api/query"
        f"?search_query=all:{q}&sortBy=submittedDate&sortOrder=descending"
        f"&max_results={max_results}"
    )
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            xml = resp.read().decode()
    except Exception as e:
        print(f"[arxiv] error for '{query}': {e}")
        return []

    cutoff  = (datetime.date.today() - datetime.timedelta(days=LOOKBACK_DAYS)).isoformat()
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
                "snippet":   summary[:600],
                "authors":   authors[:3],
                "published": published,
                "url":       f"https://arxiv.org/abs/{arxiv_id}",
                "source":    "arxiv",
            })
    return entries


# ── DuckDuckGo web search ─────────────────────────────────────────────────────

DDG_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

def _ddg_get_vqd(query: str) -> str:
    """Fetch the vqd token DDG requires for its JSON search endpoint."""
    url  = "https://duckduckgo.com/?" + urllib.parse.urlencode({"q": query})
    req  = urllib.request.Request(url, headers=DDG_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode(errors="ignore")
    except Exception as e:
        print(f"[ddg] vqd fetch error: {e}")
        return ""
    m = re.search(r'vqd=(["\'])([^"\']+)\1', html)
    return m.group(2) if m else ""


def fetch_ddg(query: str, max_results: int = 8) -> list[dict]:
    """
    Uses DDG's internal /d.js endpoint (unofficial but stable).
    Returns list of {title, url, snippet, source, published}.
    """
    vqd = _ddg_get_vqd(query)
    if not vqd:
        print(f"[ddg] could not get vqd for '{query}' — skipping")
        return []

    params = urllib.parse.urlencode({
        "q":   query,
        "vqd": vqd,
        "df":  "w",        # past week
        "kl":  "us-en",
        "o":   "json",
    })
    url = "https://links.duckduckgo.com/d.js?" + params
    req = urllib.request.Request(url, headers=DDG_HEADERS)

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode(errors="ignore")
    except Exception as e:
        print(f"[ddg] search error for '{query}': {e}")
        return []

    # DDG wraps JSON in a JS callback — extract the array
    m = re.search(r'\[.*\]', raw, re.DOTALL)
    if not m:
        print(f"[ddg] no results parsed for '{query}'")
        return []

    try:
        items = json.loads(m.group(0))
    except json.JSONDecodeError:
        print(f"[ddg] JSON parse error for '{query}'")
        return []

    results = []
    for item in items[:max_results]:
        if not isinstance(item, dict):
            continue
        url_val = item.get("u") or item.get("url", "")
        title   = item.get("t") or item.get("title", "")
        snippet = item.get("a") or item.get("snippet", "")

        if not url_val or not title:
            continue

        # filter unwanted domains
        try:
            domain = urllib.parse.urlparse(url_val).netloc.lstrip("www.")
        except Exception:
            continue
        if domain in SKIP_DOMAINS:
            continue

        # dedupe with arxiv by skipping arxiv URLs
        if "arxiv.org" in url_val:
            continue

        results.append({
            "id":        hashlib.md5(url_val.encode()).hexdigest()[:12],
            "title":     title,
            "snippet":   snippet[:600],
            "authors":   [],
            "published": datetime.date.today().isoformat(),
            "url":       url_val,
            "source":    "web",
        })

    return results


# ── Collect all candidates ────────────────────────────────────────────────────

def collect_candidates() -> list[dict]:
    seen, candidates = set(), []

    # 1. arXiv
    print("[agent] --- arXiv ---")
    for topic in ARXIV_TOPICS:
        results = fetch_arxiv(topic, max_results=10)
        added   = 0
        for paper in results:
            uid = hashlib.md5(paper["id"].encode()).hexdigest()
            if uid not in seen:
                seen.add(uid)
                paper["uid"] = uid
                candidates.append(paper)
                added += 1
        print(f"[arxiv]  '{topic[:45]}' → {len(results)} results, {added} new")
        time.sleep(3)

    # 2. DuckDuckGo web
    print("[agent] --- DuckDuckGo ---")
    for query in WEB_QUERIES:
        results = fetch_ddg(query, max_results=8)
        added   = 0
        for item in results:
            uid = hashlib.md5(item["url"].encode()).hexdigest()
            if uid not in seen:
                seen.add(uid)
                item["uid"] = uid
                candidates.append(item)
                added += 1
        print(f"[ddg]    '{query[:45]}' → {len(results)} results, {added} new")
        time.sleep(2)

    return candidates


# ── Ollama ────────────────────────────────────────────────────────────────────

def ollama_chat(messages: list[dict], max_tokens: int = 600) -> str:
    payload = json.dumps({
        "model":    OLLAMA_MODEL,
        "messages": messages,
        "stream":   False,
        "options":  {"num_predict": max_tokens},
    }).encode()

    headers = {"Content-Type": "application/json"}
    if OLLAMA_TOKEN:
        headers["Authorization"] = f"Bearer {OLLAMA_TOKEN}"

    req = urllib.request.Request(OLLAMA_API_URL, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
        return data.get("message", {}).get("content", "").strip()
    except Exception as e:
        print(f"[ollama] error: {e}")
        return ""


SYSTEM_PROMPT = """You are the GeoAI Content Agent for IQSpatial.
Your job: read a paper abstract or web article snippet and produce structured editorial
content for a professional GeoAI intelligence feed. Be precise, technically accurate,
and concise. Audience: geospatial data scientists, remote sensing engineers, climate-tech
practitioners."""


def enrich_item(item: dict) -> dict | None:
    source_label = "academic paper abstract" if item["source"] == "arxiv" else "web article snippet"
    authors_line = f"Authors: {', '.join(item['authors'])}\n" if item["authors"] else ""

    prompt = f"""Title: {item['title']}
{authors_line}Published: {item['published']}
Source: {item['url']}
{source_label.capitalize()}: {item['snippet']}

Produce JSON ONLY (no markdown fences) with these fields:
- headline: string — punchy 10-15 word headline for a GeoAI feed
- tldr: string — 2-sentence plain-English summary of the key contribution or finding
- significance: string — 1 sentence on why this matters for geospatial practitioners
- tags: array of 2-4 strings chosen ONLY from: {json.dumps(TAGS_VOCAB)}
- readtime: integer — estimated read time in minutes (1-5)
- difficulty: string — one of "introductory", "intermediate", "advanced"

Return only the JSON object, nothing else."""

    raw = ollama_chat(
        [{"role": "system", "content": SYSTEM_PROMPT},
         {"role": "user",   "content": prompt}],
        max_tokens=400,
    )
    if not raw:
        return None

    raw = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()

    try:
        enriched = json.loads(raw)
    except json.JSONDecodeError:
        print(f"[enrich] JSON parse failed: {item['title'][:60]}")
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
        "readtime":     enriched.get("readtime", 3),
        "difficulty":   enriched.get("difficulty", "intermediate"),
    }


# ── Feed I/O ──────────────────────────────────────────────────────────────────

def load_feed() -> list[dict]:
    if FEED_PATH.exists():
        return json.loads(FEED_PATH.read_text())
    return []


def save_feed(items: list[dict]) -> None:
    FEED_PATH.parent.mkdir(parents=True, exist_ok=True)
    FEED_PATH.write_text(json.dumps(items, indent=2, ensure_ascii=False))
    print(f"[feed] saved {len(items)} items → {FEED_PATH}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    validate_config()

    existing      = load_feed()
    existing_real = [i for i in existing if not i["uid"].startswith("seed-")]
    existing_uids = {item["uid"] for item in existing_real}

    candidates = collect_candidates()
    new_items   = [c for c in candidates if c["uid"] not in existing_uids]
    print(f"\n[agent] {len(candidates)} total candidates, {len(new_items)} new → enriching up to {MAX_NEW_TODAY}")

    enriched = []
    for item in new_items[:MAX_NEW_TODAY]:
        label = "arxiv" if item["source"] == "arxiv" else "web  "
        print(f"[{label}] enriching: {item['title'][:65]}")
        result = enrich_item(item)
        if result:
            enriched.append(result)
        time.sleep(2)

    combined = enriched + existing_real
    combined = combined[:MAX_ITEMS]
    save_feed(combined)

    arxiv_count = sum(1 for e in enriched if e["source"] == "arxiv")
    web_count   = sum(1 for e in enriched if e["source"] == "web")
    print(f"[agent] done. added={len(enriched)} (arxiv={arxiv_count}, web={web_count}), total={len(combined)}")


if __name__ == "__main__":
    main()
