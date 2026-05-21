import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "GeoAI Intelligence Feed",
  description:
    "Daily curated research briefings on geospatial AI — satellite imagery, remote sensing, spatial ML, and more. Powered by an autonomous AI agent.",
  openGraph: {
    title: "GeoAI Intelligence Feed",
    description: "Daily curated geospatial AI research briefings",
    type: "website",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
