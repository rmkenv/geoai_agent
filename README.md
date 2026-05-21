# GeoAI Intelligence Feed

An autonomous AI agent that researches, summarizes, and publishes daily GeoAI content to a public-facing website. Built for [IQSpatial](https://iqspatial.com).

## How it works

1. **Nightly GitHub Actions** job runs `agent/run.py` at 02:00 UTC
2. The agent fetches recent papers from **arXiv** across 6 GeoAI topic queries
3. Each paper is sent to **Ollama Cloud** for editorial enrichment (headline, TL;DR, significance, tags)
4. Results are written to `data/feed.json` and committed back to the repo
5. The commit triggers **Vercel** to rebuild and deploy the **Next.js** static site

```
geoai-agent/
├── agent/
│   └── run.py              # AI agent orchestrator
├── data/
│   └── feed.json           # Flat-file data store (committed to repo)
├── site/                   # Next.js frontend
│   └── src/
│       ├── app/            # Pages + global CSS
│       ├── components/     # FeedClient (search, filter, sort)
│       └── lib/            # feed.ts data utility
├── .github/workflows/
│   └── nightly.yml         # Cron + commit workflow
└── vercel.json             # Vercel build config
```

## Setup

### 1. Clone and push to GitHub

```bash
git clone <this-repo>
cd geoai-agent
git remote set-url origin https://github.com/YOUR_ORG/geoai-agent.git
git push -u origin main
```

### 2. Set GitHub Secrets

Go to **Settings → Secrets → Actions** and add:

| Secret | Value |
|---|---|
| `OLLAMA_API_URL` | `https://ollama.com/api/chat` |
| `OLLAMA_MODEL`   | Your model name (e.g. `gpt-oss:20b`, `llama3`, `mistral`) |
| `OLLAMA_TOKEN`   | Your Ollama Cloud Bearer token |

### 3. Deploy to Vercel

1. Import the repo in [vercel.com/new](https://vercel.com/new)
2. Vercel auto-detects `vercel.json` — no additional config needed
3. Set **Auto-deploy on push** — each nightly commit triggers a rebuild

### 4. Trigger the first run

```bash
# Via GitHub UI: Actions → "GeoAI Agent — nightly run" → Run workflow
# Or locally for testing:
OLLAMA_API_URL=https://ollama.com/api/chat \
OLLAMA_MODEL=llama3 \
OLLAMA_TOKEN=your_token \
python agent/run.py
```

## Customising

### Change arXiv topics
Edit `ARXIV_TOPICS` in `agent/run.py` — any free-text query works.

### Change the tag vocabulary
Edit `TAGS_VOCAB` in `agent/run.py`. The LLM is instructed to only use tags from this list.

### Adjust volume
- `MAX_NEW_TODAY` — articles enriched per nightly run (default 8)
- `MAX_ITEMS` — rolling window size in `feed.json` (default 40)

### Add more sources
Implement a new fetch function alongside `fetch_arxiv()` (e.g. RSS feeds, Semantic Scholar API) and call it in `collect_candidates()`.

## Local development

```bash
# Run the agent (dry run without pushing)
python agent/run.py

# Run the site
cd site
npm install
npm run dev      # http://localhost:3000
```

## Tech stack

| Layer | Tool |
|---|---|
| Agent language | Python 3.11 (stdlib only, no pip deps) |
| LLM | Ollama Cloud (configurable model) |
| Research source | arXiv API |
| Data store | Flat JSON file in repo |
| CI/CD | GitHub Actions |
| Frontend | Next.js 14 (static export) |
| Hosting | Vercel |
