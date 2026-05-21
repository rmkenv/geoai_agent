# GeoAI Intelligence Feed

An autonomous AI agent that researches, summarizes, and publishes daily GeoAI content. Built for [IQSpatial](https://iqspatial.com).

## Repo structure

```
geoai-agent/
├── agent/
│   └── run.py              # AI agent — arXiv fetch + Ollama enrichment
├── data/
│   └── feed.json           # Flat-file data store (auto-committed nightly)
├── src/                    # Next.js app (at repo root)
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx
│   │   └── globals.css
│   ├── components/
│   │   └── FeedClient.tsx  # Search, filter, sort UI
│   └── lib/
│       └── feed.ts         # Reads data/feed.json at build time
├── .github/workflows/
│   └── nightly.yml         # Cron job + git commit
├── next.config.js
├── package.json
├── tsconfig.json
└── vercel.json
```

## How it works

1. **Nightly GitHub Actions** runs `agent/run.py` at 02:00 UTC
2. Agent fetches new papers from **arXiv** across GeoAI topic queries
3. Each paper is sent to **Ollama Cloud** for editorial enrichment (headline, TL;DR, tags, difficulty)
4. Results committed to `data/feed.json` → triggers **Vercel** rebuild
5. Next.js reads `data/feed.json` at build time and renders the static site

## Setup

### 1. Push to GitHub

```bash
git init && git add .
git commit -m "init: GeoAI agent + feed site"
git remote add origin https://github.com/rmkenv/geoai_agent.git
git push -u origin main
```

### 2. Add GitHub Secrets

Go to **repo → Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Value |
|---|---|
| `OLLAMA_API_URL` | `https://ollama.com/api/chat` |
| `OLLAMA_MODEL` | your model name (e.g. `gpt-oss:20b`, `llama3`) |
| `OLLAMA_TOKEN` | your Ollama Cloud Bearer token |

The **Actions tab** appears automatically once `.github/workflows/nightly.yml` is pushed.

### 3. Deploy on Vercel

1. Go to [vercel.com/new](https://vercel.com/new) → Import `rmkenv/geoai_agent`
2. **Root Directory**: leave as `/` (package.json is at repo root)
3. **Framework**: Next.js (auto-detected)
4. Deploy — done

Each nightly commit triggers an automatic redeploy.

### 4. Trigger first run manually

In GitHub: **Actions tab → "GeoAI Agent — nightly run" → Run workflow**

Or locally:
```bash
OLLAMA_API_URL=https://ollama.com/api/chat \
OLLAMA_MODEL=llama3 \
OLLAMA_TOKEN=your_token \
python agent/run.py
```

## Customising

**Topics**: edit `ARXIV_TOPICS` in `agent/run.py`  
**Tags**: edit `TAGS_VOCAB` — the LLM only uses tags from this list  
**Volume**: `MAX_NEW_TODAY` (articles per run), `MAX_ITEMS` (rolling window)  
**Sources**: add new fetch functions alongside `fetch_arxiv()` in `collect_candidates()`

## Local dev

```bash
# Agent
python agent/run.py

# Site
npm install
npm run dev   # http://localhost:3000
```
