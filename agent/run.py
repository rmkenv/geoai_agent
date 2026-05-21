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
LOOKBACK_DAYS  = 30   # widened to 30 days

ARXIV_TOPICS = [
    "geospatial artificial intelligence",
    "remote sensing deep learning",
    "satellite image segmentation",
    "spatial machine learning",
    "large language model geospatial",
    "SAR flood detection",
    "NDVI crop prediction",
    "urban heat island satellite",
    "change detection multispectral",
    "point cloud lidar deep learning",
]

WEB_QUERIES = [
    "GeoAI geospatial AI 2025",
    "remote sensing AI open source 2025",
    "satellite imagery machine learning release 2025",
    "geospatial foundation model 2025",
    "planetary computer earth observation AI 2025",
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
        print("[agent] Repo → Settings → Secrets and variables → Actions → New repository secret")
        sys.exit(1)
    print(f"[agent] config ok — model={OLLAMA_MODEL} url={OLLAMA_API_URL}")


# ── ArXiv ─────────────────────────────────────────────────────────────────────

def fetch_arxiv(query: str, max_results: int = 10) -> list[dict]:
    q = urllib.parse.quote(query)
    url = (
        f"http://export.arxiv.org/api/query"
        f"?search_query=all:{q}&sortBy=submittedDate&sortOrder=descending"
        f"&max_results={max_results}"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "GeoAI-Agent/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            xml = resp.read().decode()
    except Exception as e:
        print(f"  [arxiv] ERROR fetching '{query}': {e}")
        return []

    cutoff  = (datetime.date.today() - datetime.timedelta(days=LOOKBACK_DAYS)).isoformat()
    entries = []
    raw_count = len(xml.split("<entry>")) - 1
    print(f"  [arxiv] raw XML entries: {raw_count}, cutoff: {cutoff}")

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
            print(f"  [arxiv] skip (old {published}): {title[:50]}")
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


# ── DuckDuckGo HTML scrape ────────────────────────────────────────────────────

def fetch_ddg(query: str, max_results: int = 6) -> list[dict]:
    """
    Scrapes DDG HTML results page — no API key, no vqd token needed.
    Parses result links and snippets directly from the HTML.
    """
    params = urllib.parse.urlencode({"q": query, "kl": "us-en"})
    url    = f"https://html.duckduckgo.com/html/?{params}"
    req    = urllib.request.Request(url, headers=BROWSER_HEADERS)

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            html = resp.read().decode(errors="ignore")
    except Exception as e:
        print(f"  [ddg] ERROR fetching '{query}': {e}")
        return []

    results = []

    # DDG HTML results have this structure:
    # <a class="result__a" href="...">title</a>
    # <a class="result__snippet">snippet</a>
    result_blocks = re.findall(
        r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?class="result__snippet"[^>]*>(.*?)</a>',
        html, re.DOTALL
    )

    print(f"  [ddg] raw blocks found: {len(result_blocks)} for '{query[:40]}'")

    for href, title_html, snippet_html in result_blocks[:max_results]:
        # DDG wraps real URLs in a redirect — extract the uddg param
        m = re.search(r'uddg=([^&"]+)', href)
        real_url = urllib.parse.unquote(m.group(1)) if m else href

        title   = re.sub(r'<[^>]+>', '', title_html).strip()
        snippet = re.sub(r'<[^>]+>', '', snippet_html).strip()

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

    print("\n[agent] ── arXiv ──────────────────────────────────")
    for topic in ARXIV_TOPICS:
        print(f"[arxiv] querying: '{topic}'")
        results = fetch_arxiv(topic, max_results=10)
        added = 0
        for paper in results:
            uid = hashlib.md5(paper["id"].encode()).hexdigest()
            if uid not in seen:
                seen.add(uid)
                paper["uid"] = uid
                candidates.append(paper)
                added += 1
        print(f"  → {len(results)} within {LOOKBACK_DAYS} days, {added} unique new")
        time.sleep(3)

    print(f"\n[agent] ── DuckDuckGo ─────────────────────────────")
    for query in WEB_QUERIES:
        print(f"[ddg] querying: '{query}'")
        results = fetch_ddg(query, max_results=6)
        added = 0
        for item in results:
            uid = hashlib.md5(item["url"].encode()).hexdigest()
            if uid not in seen:
                seen.add(uid)
                item["uid"] = uid
                candidates.append(item)
                added += 1
        print(f"  → {len(results)} results, {added} unique new")
        time.sleep(2)

    print(f"\n[agent] total candidates: {len(candidates)}")
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
        print(f"  [ollama] ERROR: {e}")
        return ""


SYSTEM_PROMPT = """You are the GeoAI Content Agent for IQSpatial.
Your job: read a paper abstract or web article snippet and produce structured editorial
content for a professional GeoAI intelligence feed. Be precise, technically accurate,
and concise. Audience: geospatial data scientists, remote sensing engineers, climate-tech
practitioners."""


def enrich_item(item: dict) -> dict | None:
    authors_line = f"Authors: {', '.join(item['authors'])}\n" if item["authors"] else ""
    source_label = "academic paper abstract" if item["source"] == "arxiv" else "web article snippet"

    prompt = f"""Title: {item['title']}
{authors_line}Published: {item['published']}
Source: {item['url']}
{source_label.capitalize()}: {item['snippet']}

Produce JSON ONLY (no markdown fences) with these exact fields:
- headline: string — punchy 10-15 word headline for a GeoAI feed
- tldr: string — 2-sentence plain-English summary
- significance: string — 1 sentence on why this matters for geospatial practitioners
- tags: array of 2-4 strings ONLY from: {json.dumps(TAGS_VOCAB)}
- readtime: integer — estimated read time 1-5 minutes
- difficulty: string — "introductory", "intermediate", or "advanced"

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
        print(f"  [enrich] JSON parse failed: {item['title'][:60]}")
        print(f"  [enrich] raw response: {raw[:200]}")
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
    print(f"[feed] loading from: {FEED_PATH}")
    if FEED_PATH.exists():
        data = json.loads(FEED_PATH.read_text())
        print(f"[feed] loaded {len(data)} existing items")
        return data
    print("[feed] no existing feed found — starting fresh")
    return []


def save_feed(items: list[dict]) -> None:
    FEED_PATH.parent.mkdir(parents=True, exist_ok=True)
    FEED_PATH.write_text(json.dumps(items, indent=2, ensure_ascii=False))
    print(f"[feed] saved {len(items)} items → {FEED_PATH}")
    # sanity check
    verify = json.loads(FEED_PATH.read_text())
    print(f"[feed] verified: {len(verify)} items on disk")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"[agent] ── GeoAI Agent starting {datetime.date.today()} ──")
    validate_config()

    existing      = load_feed()
    existing_real = [i for i in existing if not str(i.get("uid","")).startswith("seed-")]
    existing_uids = {item["uid"] for item in existing_real}
    print(f"[agent] {len(existing_real)} real existing items, {len(existing_uids)} UIDs to skip")

    candidates = collect_candidates()
    new_items  = [c for c in candidates if c["uid"] not in existing_uids]
    print(f"[agent] {len(new_items)} new items to enrich (capped at {MAX_NEW_TODAY})")

    if not new_items:
        print("[agent] nothing new found — feed unchanged")
        # still save so the commit step sees no diff and exits cleanly
        save_feed(existing_real)
        return

    enriched = []
    for item in new_items[:MAX_NEW_TODAY]:
        src = item["source"].upper()
        print(f"\n[{src}] enriching: {item['title'][:70]}")
        result = enrich_item(item)
        if result:
            enriched.append(result)
            print(f"  ✓ headline: {result['headline'][:60]}")
        else:
            print(f"  ✗ enrichment failed — skipping")
        time.sleep(2)

    combined = enriched + existing_real
    combined = combined[:MAX_ITEMS]

    arxiv_n = sum(1 for e in enriched if e["source"] == "arxiv")
    web_n   = sum(1 for e in enriched if e["source"] == "web")
    print(f"\n[agent] ── done ──")
    print(f"[agent] added={len(enriched)} (arxiv={arxiv_n}, web={web_n}), total={len(combined)}")
    save_feed(combined)


if __name__ == "__main__":
    main()
