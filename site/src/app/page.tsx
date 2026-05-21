import { getFeed, FeedItem } from "@/lib/feed";
import FeedClient from "@/components/FeedClient";

export default function Home() {
  const items = getFeed();
  return <FeedClient items={items} />;
}
