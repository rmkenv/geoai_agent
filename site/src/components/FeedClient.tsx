"use client";

import { useState, useMemo } from "react";
import { FeedItem } from "@/lib/feed";

const ALL_TAGS = [
  "foundation-models", "remote-sensing", "satellite-imagery", "urban-AI",
  "crop-monitoring", "flood-detection", "change-detection", "SAR",
  "spatial-reasoning", "LLM", "open-source",
];

function diffClass(d: string) {
  if (d === "introductory") return "difficulty-badge diff-introductory";
  if (d === "advanced")     return "difficulty-badge diff-advanced";
  return "difficulty-badge diff-intermediate";
}

function Card({ item }: { item: FeedItem }) {
  return (
    <article className="card">
      <div className="card-top">
        <span className="card-date">{item.curated_at}</span>
        <span className={diffClass(item.difficulty)}>{item.difficulty}</span>
      </div>

      <h2 className="card-headline">{item.headline}</h2>

      <p className="card-tldr">{item.tldr}</p>

      {item.significance && (
        <p className="card-significance">{item.significance}</p>
      )}

      <div className="card-tags">
        {item.tags.map((t) => (
          <span key={t} className="tag">{t}</span>
        ))}
      </div>

      <div className="card-footer">
        <span className="card-authors">{item.authors.join(", ")}</span>
        <span className="card-readtime">{item.readtime} min</span>
        <a href={item.url} target="_blank" rel="noopener noreferrer" className="card-link">
          Paper ↗
        </a>
      </div>
    </article>
  );
}

export default function FeedClient({ items }: { items: FeedItem[] }) {
  const [query,   setQuery]   = useState("");
  const [tag,     setTag]     = useState("all");
  const [sort,    setSort]    = useState<"curated" | "published">("curated");

  const filtered = useMemo(() => {
    let out = [...items];

    if (query.trim()) {
      const q = query.toLowerCase();
      out = out.filter(
        (i) =>
          i.headline.toLowerCase().includes(q) ||
          i.tldr.toLowerCase().includes(q) ||
          i.title.toLowerCase().includes(q) ||
          i.tags.some((t) => t.includes(q))
      );
    }

    if (tag !== "all") {
      out = out.filter((i) => i.tags.includes(tag));
    }

    out.sort((a, b) => {
      const ka = sort === "curated" ? a.curated_at : a.published;
      const kb = sort === "curated" ? b.curated_at : b.published;
      return kb.localeCompare(ka);
    });

    return out;
  }, [items, query, tag, sort]);

  // collect only tags that appear in current items
  const activeTags = useMemo(() => {
    const s = new Set(items.flatMap((i) => i.tags));
    return ALL_TAGS.filter((t) => s.has(t));
  }, [items]);

  const latestDate = items[0]?.curated_at ?? "—";

  return (
    <div className="shell">
      <header>
        <div className="header-inner">
          <div className="brand">
            <span className="brand-name">IQSpatial</span>
            <h1 className="feed-title">GeoAI Intelligence Feed</h1>
          </div>
          <div className="header-meta">
            <span className="agent-badge">AI agent · live</span>
            <span className="update-time">Last update: {latestDate}</span>
          </div>
        </div>
      </header>

      <div className="controls">
        <div className="search-wrap">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
          </svg>
          <input
            className="search-input"
            type="search"
            placeholder="Search headlines, tags…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>

        <div className="pill-group">
          <button className={`pill ${tag === "all" ? "active" : ""}`} onClick={() => setTag("all")}>
            all
          </button>
          {activeTags.map((t) => (
            <button
              key={t}
              className={`pill ${tag === t ? "active" : ""}`}
              onClick={() => setTag(tag === t ? "all" : t)}
            >
              {t}
            </button>
          ))}
        </div>

        <select
          className="sort-select"
          value={sort}
          onChange={(e) => setSort(e.target.value as "curated" | "published")}
        >
          <option value="curated">Sort: curated date</option>
          <option value="published">Sort: published date</option>
        </select>
      </div>

      <div className="stats-bar">
        Showing <span>{filtered.length}</span> of <span>{items.length}</span> items
        {tag !== "all" && <> · tag: <span>{tag}</span></>}
        {query && <> · query: <span>"{query}"</span></>}
      </div>

      <div className="feed-grid">
        {filtered.length === 0 ? (
          <div className="empty">No results — try a different search or tag.</div>
        ) : (
          filtered.map((item) => <Card key={item.uid} item={item} />)
        )}
      </div>

      <footer>
        <span>
          GeoAI Intelligence Feed · <a href="https://iqspatial.com" target="_blank">IQSpatial</a>
        </span>
        <span>Autonomous curation by AI agent · Powered by Ollama Cloud · Nightly via GitHub Actions</span>
      </footer>
    </div>
  );
}
