import type { Metadata, Viewport } from "next";
import { Geist } from "next/font/google";
import { preconnect } from "react-dom";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const description =
  "Traffic signs detected in Panoramax pictures, drawn where they stand: triangulated from the pictures that see them.";

export const metadata: Metadata = {
  // absolute URLs for the og:image / twitter:image tags
  metadataBase: new URL(process.env.SITE_URL ?? "https://panoloc.jdecorte.com"),
  title: "panoloc — sign map",
  description,
  openGraph: {
    type: "website",
    siteName: "panoloc",
    title: "panoloc — sign map",
    description,
  },
  twitter: {
    card: "summary_large_image",
    title: "panoloc — sign map",
    description,
  },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#0a0a0b" },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  // the hosts the map and the 360° view ask first: their connections open early
  preconnect("https://tiles.openfreemap.org", { crossOrigin: "anonymous" });
  preconnect("https://api.panoramax.xyz", { crossOrigin: "anonymous" });
  return (
    <html lang="en" className={`${geistSans.variable} h-full antialiased`}>
      <body className="h-full">{children}</body>
    </html>
  );
}
