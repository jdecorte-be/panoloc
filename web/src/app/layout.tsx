import type { Metadata, Viewport } from "next";
import { Noto_Sans } from "next/font/google";
import { preconnect } from "react-dom";
import "./globals.css";

// the font of the basemap's labels: the panel reads as part of the map
const notoSans = Noto_Sans({
  variable: "--font-noto-sans",
  subsets: ["latin"],
});

const TITLE = "Panoloc · Traffic signs located from Panoramax pictures";
const description =
  "Traffic signs detected in Panoramax pictures, drawn where they stand: triangulated from the pictures that see them.";

export const metadata: Metadata = {
  // absolute URLs for the og:image / twitter:image tags
  metadataBase: new URL(process.env.SITE_URL ?? "https://panoloc.jdecorte.com"),
  title: TITLE,
  description,
  openGraph: {
    type: "website",
    siteName: "Panoloc",
    title: TITLE,
    description,
  },
  twitter: {
    card: "summary_large_image",
    title: TITLE,
    description,
  },
};

export const viewport: Viewport = {
  themeColor: "#ffffff",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  // the hosts the map and the 360° view ask first: their connections open early
  preconnect("https://tiles.openfreemap.org", { crossOrigin: "anonymous" });
  preconnect("https://api.panoramax.xyz", { crossOrigin: "anonymous" });
  return (
    <html lang="en" className={`${notoSans.variable} h-full antialiased`}>
      {/* browser extensions add their classes to <body> before React (Vimium C: vc-init):
          only this tag's attributes are let differ from the server's */}
      <body className="h-full" suppressHydrationWarning>
        {children}
      </body>
    </html>
  );
}
