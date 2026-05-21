import path from "path";
import fs from "fs";

export interface FeedItem {
  uid: string;
  source: string;
  url: string;
  arxiv_id: string;
  title: string;
  authors: string[];
  published: string;
  curated_at: string;
  headline: string;
  tldr: string;
  significance: string;
  tags: string[];
  readtime: number;
  difficulty: "introductory" | "intermediate" | "advanced";
}

export function getFeed(): FeedItem[] {
  // walk up from site/ to repo root to find data/feed.json
  const feedPath = path.resolve(process.cwd(), "..", "data", "feed.json");
  if (!fs.existsSync(feedPath)) return [];
  const raw = fs.readFileSync(feedPath, "utf-8");
  return JSON.parse(raw) as FeedItem[];
}
