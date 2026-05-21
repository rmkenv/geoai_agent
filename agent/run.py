"""
GeoAI Content Agent — nightly runner
Fetches recent GeoAI content, summarizes via Ollama Cloud,
writes structured JSON to data/feed.json.
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
from pathlib import Path

# ── Config (from environment) ────────────────────────────────────────────────
OLLAMA_API_URL = os.environ.get("OLLAMA_API_URL", "").strip()
OLLAMA_MODEL   = os.environ.get("OLLAMA_MODEL",   "").strip()
OLLAMA_TOKEN   = os.environ.get("OLLAMA_TOKEN",   "").strip()

FEED_PATH      = Path(__file__).parent.parent / "data" / "feed.json"
MAX_ITEMS      = 60
MAX_NEW_TODAY  = 10
LOOKBACK_DAYS  = 14   # only consider papers from the last N days

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

TAGS_VOCAB = [
    "foundation-models", "remote-sensing", "satellite-imagery", "urban-AI",
    "crop-monitoring", "flood-detection", "change-detection", "object-detection",
    "segmentation", "time-series", "point-cloud", "LiDAR", "SAR",
    "spatial-reasoning", "LLM", "diffusion-models", "vector-tiles",
    "open-source", "benchmark", "real-time",
]


# ── Validate secrets up front ─────────────────────────────────────────────────

def validate_config():
    missing = []
    if not OLLAMA_API_URL:
        missing.append("OLLAMA_API_URL")
    if not OLLAMA_MODEL:
        missing.append("OLLAMA_MODEL")
    if missing:
        print(f"[agent] ERROR: missing required environment variables: {', '.join(missing)}")
        print("[agent] Set them as GitHub Secrets:")
        print("  Repo → Settings → Secrets and variables → Actions → New repository secret")
        sys.exit(1)
    print(f"[agent] config ok — model={OLLAMA_MODEL} url={OLLAMA_API_URL}")


# ── ArXiv fetch ───────────────────────────────────────────────────────────────

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
        print(f"[arxiv] fetch error for '{query}': {e}")
        return []

    cutoff = (datetime.date.today() - datetime.timedelta(days=LOOKBACK_DAYS)).isoformat()

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

        # skip papers older than the lookback window
        if published < cutoff:
            continue

        authors = []
        for chunk in entry_xml.split("<author>")[1:]:
            name_s = chunk.find("<name>") + 6
            name_e = chunk.find("</name>")
            if name_s > 5:
                authors.append(chunk[name_s:name_e].strip())

        if title and arxiv_id:
            entries.append({
                "id":        arxiv_id,
                "title":     title,
                "summary":   summary[:800],
                "authors":   authors[:3],
                "published": published,
                "url":       f"https://arxiv.org/abs/{arxiv_id}",
                "source":    "arxiv",
            })
    return entries


def collect_candidates() -> list[dict]:
    seen, candidates = set(), []
    for topic in ARXIV_TOPICS:
        results = fetch_arxiv(topic, max_results=10)
        added = 0
        for paper in results:
            uid = hashlib.md5(paper["id"].encode()).hexdigest()
            if uid not in seen:
                seen.add(uid)
                paper["uid"] = uid
                candidates.append(paper)
                added += 1
        print(f"[arxiv] '{topic[:40]}' → {len(results)} results, {added} new unique")
        time.sleep(3)   # arxiv asks for 3s between requests
    return candidates


# ── Ollama Cloud call ─────────────────────────────────────────────────────────

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


# ── Summarise & enrich one paper ─────────────────────────────────────────────

SYSTEM_PROMPT = """You are the GeoAI Content Agent for IQSpatial.
Your job: read an academic paper abstract and produce structured editorial content for a
professional GeoAI intelligence feed. Be precise, technically accurate, and concise.
Audience: geospatial data scientists, remote sensing engineers, climate-tech practitioners."""


def enrich_paper(paper: dict) -> dict | None:
    prompt = f"""Paper title: {paper['title']}
Authors: {', '.join(paper['authors'])}
Published: {paper['published']}
Abstract excerpt: {paper['summary']}

Produce JSON ONLY (no markdown fences) with these fields:
- headline: string — punchy 10-15 word headline for a GeoAI feed
- tldr: string — 2-sentence plain-English summary of the key contribution
- significance: string — 1 sentence on why this matters for geospatial practitioners
- tags: array of 2-4 strings chosen ONLY from this vocabulary: {json.dumps(TAGS_VOCAB)}
- readtime: integer — estimated read time in minutes (1-5)
- difficulty: string — one of "introductory", "intermediate", "advanced"

Return only the JSON object, nothing else."""

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": prompt},
    ]

    raw = ollama_chat(messages, max_tokens=400)
    if not raw:
        return None

    raw = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()

    try:
        enriched = json.loads(raw)
    except json.JSONDecodeError:
        print(f"[enrich] JSON parse failed for: {paper['title'][:60]}")
        return None

    return {
        "uid":          paper["uid"],
        "source":       paper["source"],
        "url":          paper["url"],
        "arxiv_id":     paper.get("id", ""),
        "title":        paper["title"],
        "authors":      paper["authors"],
        "published":    paper["published"],
        "curated_at":   datetime.date.today().isoformat(),
        "headline":     enriched.get("headline", paper["title"]),
        "tldr":         enriched.get("tldr", ""),
        "significance": enriched.get("significance", ""),
        "tags":         enriched.get("tags", []),
        "readtime":     enriched.get("readtime", 3),
        "difficulty":   enriched.get("difficulty", "intermediate"),
    }


# ── Load / save feed ──────────────────────────────────────────────────────────

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
    # exclude the placeholder seed item from dedup so it gets replaced
    existing_real = [i for i in existing if not i["uid"].startswith("seed-")]
    existing_uids = {item["uid"] for item in existing_real}

    candidates = collect_candidates()
    new_papers  = [p for p in candidates if p["uid"] not in existing_uids]
    print(f"[agent] {len(candidates)} candidates in last {LOOKBACK_DAYS} days, {len(new_papers)} not yet in feed")

    enriched = []
    for paper in new_papers[:MAX_NEW_TODAY]:
        print(f"[agent] enriching: {paper['title'][:70]}")
        result = enrich_paper(paper)
        if result:
            enriched.append(result)
        time.sleep(2)

    combined = enriched + existing_real   # drop seed on first real run
    combined = combined[:MAX_ITEMS]
    save_feed(combined)

    print(f"[agent] done. added={len(enriched)}, total={len(combined)}")


if __name__ == "__main__":
    main()
